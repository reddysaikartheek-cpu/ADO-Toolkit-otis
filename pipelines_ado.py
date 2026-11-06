# -*- coding: utf-8 -*-

"""
Azure Pipelines helpers for the Azure DevOps Toolkit.

- Build runs per pipeline (with branch and date filters)
- Test result summary for a build
- Classic release and YAML environment deployments
- Queueing a pipeline run on a branch
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import requests

from link_tests_to_epic import AUTH, ORG

PIPELINES_PROJECT = "SmartSystems"
PROJECT_URL = f"https://dev.azure.com/{ORG}/{PIPELINES_PROJECT}/_apis"
RELEASE_URL = f"https://vsrm.dev.azure.com/{ORG}/{PIPELINES_PROJECT}/_apis/release"


def _get(url: str, params: Optional[Dict[str, object]] = None, api_version: str = "7.1") -> dict:
    response = requests.get(
        url,
        params={"api-version": api_version, **(params or {})},
        auth=AUTH,
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    cleaned = re.sub(r"(\.\d{6})\d+", r"\1", value).replace("Z", "+00:00")
    return datetime.fromisoformat(cleaned)


def _list_all(url: str, api_version: str = "7.1") -> List[Dict[str, object]]:
    items: List[Dict[str, object]] = []
    token: Optional[str] = None
    while True:
        params: Dict[str, object] = {"api-version": api_version, "$top": 1000}
        if token:
            params["continuationToken"] = token
        response = requests.get(url, params=params, auth=AUTH, timeout=60)
        response.raise_for_status()
        items.extend(response.json().get("value", []))
        token = response.headers.get("x-ms-continuationtoken")
        if not token:
            return items


def list_pipeline_definitions() -> List[Dict[str, object]]:
    definitions: Dict[int, Dict[str, object]] = {}
    for item in _list_all(f"{PROJECT_URL}/build/definitions") + _list_all(f"{PROJECT_URL}/pipelines"):
        definitions[int(item["id"])] = {"id": item["id"], "name": item["name"]}
    return sorted(definitions.values(), key=lambda d: str(d["name"]).lower())


def list_builds(definition_id: Optional[int], branch: str, days: int) -> List[Dict[str, object]]:
    params: Dict[str, object] = {
        "$top": 500,
        "queryOrder": "queueTimeDescending",
        "minTime": (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if definition_id:
        params["definitions"] = definition_id
    if branch:
        params["branchName"] = f"refs/heads/{branch}"

    rows: List[Dict[str, object]] = []
    for build in _get(f"{PROJECT_URL}/build/builds", params).get("value", []):
        start = _parse_time(build.get("startTime"))
        finish = _parse_time(build.get("finishTime"))
        queued = _parse_time(build.get("queueTime"))
        rows.append(
            {
                "Build ID": build["id"],
                "Pipeline": (build.get("definition") or {}).get("name", ""),
                "Build number": build.get("buildNumber", ""),
                "Branch": (build.get("sourceBranch") or "").replace("refs/heads/", ""),
                "Status": build.get("status", ""),
                "Result": build.get("result") or build.get("status", ""),
                "Requested by": (build.get("requestedFor") or {}).get("displayName", ""),
                "Date": queued.date().isoformat() if queued else None,
                "Duration (min)": round((finish - start).total_seconds() / 60, 1) if start and finish else None,
            }
        )
    return rows


def get_build_test_summary(build_id: int) -> Dict[str, object]:
    runs = _get(f"{PROJECT_URL}/test/runs", {"buildUri": f"vstfs:///Build/Build/{build_id}"}).get("value", [])
    total = 0
    passed = 0
    failing: List[str] = []
    for run in runs:
        total += run.get("totalTests", 0)
        passed += run.get("passedTests", 0)
        results = _get(f"{PROJECT_URL}/test/runs/{run['id']}/results", {"$top": 1000}).get("value", [])
        failing.extend(
            (result.get("testCase") or {}).get("name") or result.get("testCaseTitle", "")
            for result in results
            if result.get("outcome") == "Failed"
        )
    return {
        "Build ID": build_id,
        "Total": total,
        "Passed": passed,
        "Failed": len(failing),
        "Other": total - passed - len(failing),
        "Failing tests": failing,
    }


def list_deployments(top: int = 100) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for deployment in _get(f"{RELEASE_URL}/deployments", {"$top": top, "queryOrder": "descending"}).get("value", []):
        rows.append(
            {
                "Type": "Classic release",
                "Pipeline": (deployment.get("releaseDefinition") or {}).get("name", ""),
                "Release": (deployment.get("release") or {}).get("name", ""),
                "Environment": (deployment.get("releaseEnvironment") or {}).get("name", ""),
                "Status": deployment.get("deploymentStatus", ""),
                "Operation": deployment.get("operationStatus", ""),
                "Requested by": (deployment.get("requestedFor") or {}).get("displayName", ""),
                "Completed": deployment.get("completedOn", ""),
            }
        )
    for environment in _get(f"{PROJECT_URL}/pipelines/environments", api_version="7.1-preview.1").get("value", []):
        records = _get(
            f"{PROJECT_URL}/pipelines/environments/{environment['id']}/environmentdeploymentrecords",
            {"top": top},
            api_version="7.1-preview.1",
        ).get("value", [])
        for record in records:
            rows.append(
                {
                    "Type": "YAML environment",
                    "Pipeline": (record.get("definition") or {}).get("name", ""),
                    "Release": (record.get("resource") or {}).get("name", ""),
                    "Environment": environment.get("name", ""),
                    "Status": record.get("result", ""),
                    "Operation": "",
                    "Requested by": (record.get("owner") or {}).get("displayName", ""),
                    "Completed": record.get("finishTime", ""),
                }
            )
    return rows


def queue_build(definition_id: int, branch: str) -> Dict[str, object]:
    response = requests.post(
        f"{PROJECT_URL}/build/builds",
        params={"api-version": "7.1"},
        json={"definition": {"id": definition_id}, "sourceBranch": f"refs/heads/{branch}"},
        auth=AUTH,
        headers={"Content-Type": "application/json"},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()
