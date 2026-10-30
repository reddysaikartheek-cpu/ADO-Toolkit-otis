# -*- coding: utf-8 -*-

"""
Link Azure DevOps Test Cases to an Epic in bulk.

- Selects Test Case work items under an Area Path (includes child area paths)
- Adds a "Tests" (Microsoft.VSTS.Common.TestedBy-Reverse) link from each Test Case to the Epic
- Skips test cases that are already linked to the Epic
- Set AZDO_PAT in the environment before running
"""

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional

import requests
from requests.auth import HTTPBasicAuth

# =====================================================
# CONFIGURATION
# =====================================================

ORG = "utcbis"
PROJECT_NAME = "Otis ONE Platform"

API_VERSION = "7.1"
BASE_URL = f"https://dev.azure.com/{ORG}/{PROJECT_NAME}/_apis/wit"
LINK_REL = "Microsoft.VSTS.Common.TestedBy-Reverse"

PAT = os.getenv("AZDO_PAT")
if not PAT:
    print("ERROR: AZDO_PAT environment variable not set")
    print('Windows (PowerShell):   [Environment]::SetEnvironmentVariable("AZDO_PAT","<your_pat>", "User")')
    print('macOS/Linux (bash/zsh):  export AZDO_PAT="<your_pat>"')
    sys.exit(1)

AUTH = HTTPBasicAuth("", PAT)


# =====================================================
# AZURE DEVOPS HELPERS
# =====================================================

def get_test_case_ids_by_area_path(area_path: str) -> List[int]:
    """Run a WIQL query for Test Cases under the given Area Path (including children)."""
    escaped_area = area_path.replace("'", "''")
    query = (
        "SELECT [System.Id] FROM WorkItems "
        "WHERE [System.WorkItemType] = 'Test Case' "
        f"AND [System.AreaPath] UNDER '{escaped_area}' "
        "ORDER BY [System.Id]"
    )
    response = requests.post(
        f"{BASE_URL}/wiql?api-version={API_VERSION}",
        json={"query": query},
        auth=AUTH,
        headers={"Content-Type": "application/json"},
        timeout=60,
    )
    response.raise_for_status()
    return [item["id"] for item in response.json().get("workItems", [])]


def get_test_case_ids_by_suite(plan_id: int, suite_id: int) -> List[int]:
    """Return the test case IDs in a test suite (folder) of a test plan."""
    response = requests.get(
        f"https://dev.azure.com/{ORG}/{PROJECT_NAME}/_apis/testplan/Plans/{plan_id}"
        f"/Suites/{suite_id}/TestCase?api-version=7.1",
        auth=AUTH,
        timeout=60,
    )
    response.raise_for_status()
    ids: List[int] = []
    for item in response.json().get("value", []):
        work_item = item.get("workItem") or {}
        if work_item.get("id"):
            ids.append(int(work_item["id"]))
    return sorted(set(ids))


def get_epic(epic_id: int) -> Dict[str, str]:
    """Return the URL and title of the Epic or Feature work item."""
    response = requests.get(
        f"{BASE_URL}/workitems/{epic_id}?api-version={API_VERSION}",
        auth=AUTH,
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    fields = data.get("fields", {})
    if fields.get("System.WorkItemType") not in COVERAGE_TYPES:
        raise ValueError(f"Work item {epic_id} is not an Epic or Feature")
    return {"url": data["url"], "title": fields.get("System.Title", ""), "type": fields["System.WorkItemType"]}


def is_already_linked(test_case_id: int, target_url: str) -> bool:
    """Check whether the test case already has a Tests link to the target work item."""
    return get_test_case_details(test_case_id, target_url)["already_linked"]


def get_test_case_details(test_case_id: int, target_url: str) -> Dict[str, object]:
    """Return the title and whether the test case already has a Tests link to the target work item."""
    response = requests.get(
        f"{BASE_URL}/workitems/{test_case_id}?$expand=relations&api-version={API_VERSION}",
        auth=AUTH,
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    already_linked = any(
        relation.get("rel") == LINK_REL and relation.get("url") == target_url
        for relation in data.get("relations", []) or []
    )
    return {
        "id": test_case_id,
        "title": data.get("fields", {}).get("System.Title", ""),
        "already_linked": already_linked,
    }


def link_test_case_to_epic(test_case_id: int, epic_url: str) -> None:
    """Add a Tests link from the test case to the Epic."""
    patch_document = [
        {
            "op": "add",
            "path": "/relations/-",
            "value": {"rel": LINK_REL, "url": epic_url},
        }
    ]
    response = requests.patch(
        f"{BASE_URL}/workitems/{test_case_id}?api-version={API_VERSION}",
        json=patch_document,
        auth=AUTH,
        headers={"Content-Type": "application/json-patch+json"},
        timeout=60,
    )
    response.raise_for_status()


COVERAGE_TYPES = ("Epic", "Feature")
TESTED_BY_RELS = {LINK_REL, LINK_REL.replace("-Reverse", "-Forward")}


def run_wiql(query_text: str) -> List[int]:
    """Run WIQL text and return the matching work item IDs."""
    response = requests.post(
        f"{BASE_URL}/wiql?api-version={API_VERSION}",
        json={"query": query_text},
        auth=AUTH,
        headers={"Content-Type": "application/json"},
        timeout=60,
    )
    response.raise_for_status()
    return [item["id"] for item in response.json().get("workItems", [])]


def get_work_items_expanded(ids: List[int]) -> List[dict]:
    """Fetch work items with fields and relations, in parallel batches of 200."""
    batches = [ids[start : start + 200] for start in range(0, len(ids), 200)]

    def fetch(batch: List[int]) -> List[dict]:
        response = requests.get(
            f"{BASE_URL}/workitems?ids={','.join(str(i) for i in batch)}&$expand=all&api-version={API_VERSION}",
            auth=AUTH,
            timeout=60,
        )
        response.raise_for_status()
        return response.json().get("value", [])

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(fetch, batches))
    return [item for batch_items in results for item in batch_items]


def find_coverage_gaps(ids: List[int]) -> Dict[str, object]:
    """Read-only: among Epics and Features in ids, return those with no linked test cases."""
    checked = ignored = 0
    unlinked: List[Dict[str, object]] = []
    for item in get_work_items_expanded(ids):
        fields = item.get("fields", {})
        item_type = fields.get("System.WorkItemType")
        if item_type not in COVERAGE_TYPES:
            ignored += 1
            continue
        checked += 1
        has_tests = any(rel.get("rel") in TESTED_BY_RELS for rel in item.get("relations") or [])
        if not has_tests:
            unlinked.append(
                {
                    "id": item["id"],
                    "type": item_type,
                    "title": fields.get("System.Title", ""),
                    "url": f"https://dev.azure.com/{ORG}/{PROJECT_NAME}/_workitems/edit/{item['id']}",
                }
            )
    return {"checked": checked, "ignored": ignored, "unlinked": unlinked}


def get_epics_and_features(ids: List[int]) -> List[Dict[str, object]]:
    """Return the Epics and Features among the given work item IDs."""
    items: List[Dict[str, object]] = []
    for item in get_work_items_expanded(ids):
        fields = item.get("fields", {})
        if fields.get("System.WorkItemType") in COVERAGE_TYPES:
            items.append({"id": item["id"], "type": fields["System.WorkItemType"], "title": fields.get("System.Title", "")})
    return items


def get_linked_test_cases(work_item_id: int) -> List[Dict[str, object]]:
    """Return the Test Cases linked to an Epic or Feature."""
    response = requests.get(
        f"{BASE_URL}/workitems/{work_item_id}?$expand=relations&api-version={API_VERSION}",
        auth=AUTH,
        timeout=60,
    )
    response.raise_for_status()
    linked_ids = sorted(
        {
            int(relation["url"].rsplit("/", 1)[-1])
            for relation in response.json().get("relations") or []
            if relation.get("rel") in TESTED_BY_RELS
        }
    )
    if not linked_ids:
        return []
    return [
        {"id": item["id"], "title": item.get("fields", {}).get("System.Title", "")}
        for item in get_work_items_expanded(linked_ids)
        if item.get("fields", {}).get("System.WorkItemType") == "Test Case"
    ]


def create_static_suite(plan_id: int, parent_suite_id: int, name: str, test_case_ids: List[int]) -> int:
    """Create a static suite under the parent suite and add the given test cases to it."""
    response = requests.post(
        f"https://dev.azure.com/{ORG}/{PROJECT_NAME}/_apis/testplan/Plans/{plan_id}/Suites?api-version={API_VERSION}",
        json={
            "suiteType": "StaticTestSuite",
            "name": name,
            "parentSuite": {"id": parent_suite_id},
        },
        auth=AUTH,
        headers={"Content-Type": "application/json"},
        timeout=60,
    )
    if not response.ok:
        raise RuntimeError(f"{response.status_code} {response.reason}: {response.text[:500]}")
    suite_id = int(response.json()["id"])

    response = requests.post(
        f"https://dev.azure.com/{ORG}/{PROJECT_NAME}/_apis/testplan/Plans/{plan_id}/Suites/{suite_id}/TestCase?api-version={API_VERSION}",
        json=[{"workItem": {"id": str(test_case_id)}} for test_case_id in test_case_ids],
        auth=AUTH,
        headers={"Content-Type": "application/json"},
        timeout=60,
    )
    if not response.ok:
        raise RuntimeError(f"Suite {suite_id} created but adding test cases failed: {response.status_code} {response.reason}: {response.text[:500]}")
    if not response.json().get("value"):
        raise RuntimeError(f"Suite {suite_id} created but no test cases were added: {response.text[:500]}")
    return suite_id


# =====================================================
# MAIN
# =====================================================

def print_progress(done: int, total: int, linked: int, skipped: int, failed: int) -> None:
    """Redraw a single progress line in place."""
    width = 30
    filled = int(width * done / total) if total else width
    bar = "█" * filled + "░" * (width - filled)
    sys.stdout.write(
        f"\r[LINKING] [{bar}] {done}/{total} | linked: {linked} | skipped: {skipped} | failed: {failed}"
    )
    sys.stdout.flush()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Link Test Cases under an Area Path to an Epic.")
    parser.add_argument("--epic-id", type=int, help="Epic work item ID")
    parser.add_argument("--area-path", help="Area Path, e.g. 'Otis ONE Platform\\Dhruva'")
    args = parser.parse_args()
    if args.epic_id is None:
        args.epic_id = int(input("Enter Epic ID: ").strip())
    if not args.area_path:
        args.area_path = input("Enter Area Path: ").strip()
    return args


def preview_link(epic_id: int, area_path: str) -> Dict[str, object]:
    """Read-only: list the Epic and the test cases under the Area Path, with their titles and link status."""
    return preview_test_cases(epic_id, get_test_case_ids_by_area_path(area_path))


def preview_test_cases(epic_id: int, test_case_ids: List[int]) -> Dict[str, object]:
    """Read-only: list the Epic and the given test cases, with their titles and link status."""
    epic = get_epic(epic_id)
    with ThreadPoolExecutor(max_workers=8) as executor:
        details = list(executor.map(lambda tc_id: get_test_case_details(tc_id, epic["url"]), test_case_ids))
    return {
        "epic_id": epic_id,
        "epic_title": epic["title"],
        "epic_type": epic["type"],
        "epic_url": epic["url"],
        "test_cases": details,
    }


def run_link(
    epic_url: str,
    test_case_ids: List[int],
    on_progress: Optional[Callable[[int, int, int, int, int], None]] = None,
) -> Dict[str, object]:
    total = len(test_case_ids)
    linked = skipped = failed = 0
    errors: List[str] = []
    for index, test_case_id in enumerate(test_case_ids, start=1):
        try:
            if is_already_linked(test_case_id, epic_url):
                skipped += 1
            else:
                link_test_case_to_epic(test_case_id, epic_url)
                linked += 1
        except requests.HTTPError as exc:
            failed += 1
            errors.append(f"test case {test_case_id}: {exc} - {exc.response.text[:300]}")
        if on_progress:
            on_progress(index, total, linked, skipped, failed)

    return {
        "total": total,
        "linked": linked,
        "skipped": skipped,
        "failed": failed,
        "errors": errors,
    }


def main() -> None:
    args = parse_args()
    preview = preview_link(args.epic_id, args.area_path)
    pending = [tc["id"] for tc in preview["test_cases"] if not tc["already_linked"]]

    print(f"Epic {preview['epic_id']}: {preview['epic_title']}")
    for tc in preview["test_cases"]:
        status = "already linked" if tc["already_linked"] else "will link"
        print(f"  {tc['id']} - {status}")
    print(f"Total: {len(preview['test_cases'])}, to link: {len(pending)}")

    if not pending:
        print("Nothing to link.")
        return
    if input("Proceed with linking? (y/N): ").strip().lower() != "y":
        print("Cancelled.")
        return

    result = run_link(
        preview["epic_url"],
        pending,
        on_progress=lambda d, t, l, s, f: print_progress(d, t, l, s, f),
    )

    print()
    for error in result["errors"]:
        print(f"ERROR: {error}")
    print(
        f"Done. Total: {result['total']}, linked: {result['linked']}, "
        f"already linked: {result['skipped']}, failed: {result['failed']}"
    )


if __name__ == "__main__":
    main()
