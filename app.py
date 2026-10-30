# -*- coding: utf-8 -*-

"""
Azure DevOps Toolkit (Streamlit)

- Export Heatmap: runs the WIQL export and offers the Excel file for download
- Link Tests: links Test Cases under an Area Path to an Epic

PAT is read from config.json (git-ignored) next to this file, or from AZDO_PAT if set.
"""

import json
import os
import re
import sys
from pathlib import Path

import streamlit as st

BASE_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
DEFAULT_QUERY_PATH = BASE_DIR / "default_query.wiql"

if not os.getenv("AZDO_PAT") and CONFIG_PATH.exists():
    os.environ["AZDO_PAT"] = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("pat", "")

st.set_page_config(page_title="Azure DevOps Toolkit", layout="wide")
st.markdown(
    "<style>div[data-testid='InputInstructions'], [data-testid='stAppDeployButton'] {display: none;} div[data-testid='stMainBlockContainer'] {padding-top: 2rem; padding-left: 3rem; padding-right: 3rem;}</style>",
    unsafe_allow_html=True,
)
st.title("Azure DevOps Toolkit")

if not os.getenv("AZDO_PAT"):
    st.error(f"No PAT found. Add \"pat\" to {CONFIG_PATH.name} or set AZDO_PAT.")
    st.stop()

import link_tests_to_epic as link  # noqa: E402
import AzureDevOpsHeatmap_improved_fixed as heatmap  # noqa: E402


@st.cache_data(ttl=300, show_spinner=False)
def cached_query_ids(query_text: str) -> list:
    return link.run_wiql(query_text)


@st.cache_data(ttl=300, show_spinner=False)
def cached_saved_query_ids(query_id: str) -> list:
    return link.run_wiql(heatmap.fetch_wiql_by_id(query_id))

export_tab, link_tab, gaps_tab, suite_tab = st.tabs(["Generate Heatmap", "Link Test Cases to Epic/Feature", "List of Epics/Features with no linked Test cases", "Create New Test Suite by Epics/Feature"])

EXPORT_ERROR_MESSAGE = "Export stopped. Check the PAT, network, or whether the Excel file is open."

with export_tab:
    st.write("Generates the Feature heatmap to Excel from a saved Azure DevOps query or a WIQL query.")
    saved_tab, wiql_tab = st.tabs(["Saved Query URL", "WIQL Query"])

    def run_export(query_text: str) -> None:
        heatmap.main(query_text)
        output = Path(heatmap.OUTPUT_XLSX)
        if output.exists():
            st.session_state["export_file"] = (output.name, output.read_bytes())
            output.unlink()
            st.success("Export completed. Use the download button below.")
        else:
            st.warning("No items found. Nothing was exported.")

    with saved_tab:
        query_url = st.text_input(
            "Saved query URL",
            placeholder="https://dev.azure.com/<org>/<project>/_queries/query/<query-id>/",
        )
        if st.button("Generate Heatmap", type="primary", key="generate_saved"):
            match = re.search(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", query_url or "")
            if not match:
                st.error("Enter a saved query URL that contains a query ID.")
            else:
                with st.spinner("Querying Azure DevOps and building the Excel file..."):
                    try:
                        run_export(heatmap.fetch_wiql_by_id(match.group(0)))
                    except SystemExit:
                        st.error(EXPORT_ERROR_MESSAGE)
                    except Exception as exc:
                        st.error(f"Export failed: {exc}")

    with wiql_tab:
        default_wiql = DEFAULT_QUERY_PATH.read_text(encoding="utf-8") if DEFAULT_QUERY_PATH.exists() else ""
        wiql_text = st.text_area("WIQL query", value=default_wiql, height=400)
        if st.button("Generate Heatmap", type="primary", key="generate_wiql"):
            if not wiql_text.strip():
                st.error("Enter a WIQL query.")
            else:
                with st.spinner("Querying Azure DevOps and building the Excel file..."):
                    try:
                        run_export(wiql_text)
                    except SystemExit:
                        st.error(EXPORT_ERROR_MESSAGE)
                    except Exception as exc:
                        st.error(f"Export failed: {exc}")

    if "export_file" in st.session_state:
        file_name, data = st.session_state["export_file"]
        st.download_button(
            "Download Excel",
            data=data,
            file_name=file_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

with link_tab:
    epic_id_text = st.text_input("Epic/Feature ID", placeholder="e.g. 1496542")
    link_source = st.radio("Test cases from", ["Area Path", "Test Plan suite"], horizontal=True)
    if link_source == "Area Path":
        area_path = st.text_input("Area Path", placeholder="Otis ONE Platform\\Otis ONE\\SST Systems Team")
    else:
        plan_col, suite_col = st.columns(2)
        plan_id_text = plan_col.text_input("Test Plan ID", placeholder="e.g. 1234567")
        suite_id_text = suite_col.text_input("Suite (feature folder) ID", placeholder="e.g. 1234568")

    if st.button("Find Test Cases", type="primary"):
        st.session_state.pop("link_preview", None)
        if not epic_id_text.strip().isdigit():
            st.error("Enter a numeric Epic/Feature ID.")
        elif link_source == "Area Path" and not area_path.strip():
            st.error("Enter an Area Path.")
        elif link_source != "Area Path" and not (plan_id_text.strip().isdigit() and suite_id_text.strip().isdigit()):
            st.error("Enter a numeric Test Plan ID and Suite ID.")
        else:
            with st.spinner("Reading the Epic/Feature and test cases from Azure DevOps..."):
                try:
                    if link_source == "Area Path":
                        data = link.preview_link(int(epic_id_text), area_path.strip())
                        source_label = f"Test cases under the Area Path: {len(data['test_cases'])}"
                    else:
                        test_case_ids = link.get_test_case_ids_by_suite(int(plan_id_text), int(suite_id_text))
                        data = link.preview_test_cases(int(epic_id_text), test_case_ids)
                        source_label = f"Test cases in suite {suite_id_text} of plan {plan_id_text}: {len(data['test_cases'])}"
                    st.session_state["link_preview"] = {"data": data, "source_label": source_label}
                except Exception as exc:
                    st.error(f"Could not read the Epic/Feature or test cases: {exc}")

    if "link_preview" in st.session_state:
        preview = st.session_state["link_preview"]
        data = preview["data"]
        pending = [tc for tc in data["test_cases"] if not tc["already_linked"]]
        st.subheader(f"{data['epic_type']} {data['epic_id']}: {data['epic_title']}")
        st.write(preview["source_label"])
        st.dataframe(
            [
                {"Test Case ID": str(tc["id"]), "Test Case Title": tc["title"]}
                for tc in data["test_cases"]
            ],
            hide_index=True,
            width="stretch",
            column_config={"Test Case Title": st.column_config.TextColumn("Test Case Title", width="large")},
        )

        if st.button(
            "Link test cases",
            type="primary",
            disabled=not pending,
            help=None if pending else f"All {len(data['test_cases'])} test cases are already linked to this Epic/Feature.",
        ):
            progress = st.progress(0.0)
            status = st.empty()

            def on_progress(done: int, total: int, linked: int, skipped: int, failed: int) -> None:
                progress.progress(done / total if total else 1.0)
                status.write(f"{done}/{total} | linked: {linked} | skipped: {skipped} | failed: {failed}")

            with st.spinner("Linking test cases..."):
                try:
                    result = link.run_link(
                        data["epic_url"],
                        [tc["id"] for tc in pending],
                        on_progress=on_progress,
                    )
                    st.success(
                        f"Linked successfully: {result['linked']} | "
                        f"Already linked: {len(data['test_cases']) - len(pending) + result['skipped']} | "
                        f"Failed: {result['failed']}"
                    )
                    for error in result["errors"]:
                        st.error(error)
                    st.session_state.pop("link_preview", None)
                except Exception as exc:
                    st.error(f"Linking failed: {exc}")

with gaps_tab:
    st.write("Lists Epics or Features that have no linked test cases.")
    gaps_saved_tab, gaps_wiql_tab = st.tabs(["Saved Query URL", "WIQL Query"])

    def run_gap_check(ids_loader) -> None:
        st.session_state.pop("gaps_result", None)
        with st.spinner("Checking test case links..."):
            try:
                st.session_state["gaps_result"] = link.find_coverage_gaps(ids_loader())
            except Exception as exc:
                st.error(f"Could not check coverage: {exc}")

    with gaps_saved_tab:
        gaps_query_url = st.text_input(
            "Saved query URL",
            placeholder="https://dev.azure.com/<org>/<project>/_queries/query/<query-id>/",
            key="gaps_query_url",
        )
        if st.button("Find Test links", type="primary", key="find_gaps_saved"):
            match = re.search(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", gaps_query_url or "")
            if not match:
                st.session_state.pop("gaps_result", None)
                st.error("Enter a saved query URL that contains a query ID.")
            else:
                run_gap_check(lambda: cached_saved_query_ids(match.group(0)))

    with gaps_wiql_tab:
        gaps_wiql_text = st.text_area("WIQL query", value=DEFAULT_QUERY_PATH.read_text(encoding="utf-8") if DEFAULT_QUERY_PATH.exists() else "", height=400, key="gaps_wiql_text")
        if st.button("Find Test links", type="primary", key="find_gaps_wiql"):
            if not gaps_wiql_text.strip():
                st.session_state.pop("gaps_result", None)
                st.error("Enter a WIQL query.")
            else:
                run_gap_check(lambda: cached_query_ids(gaps_wiql_text))

    if "gaps_result" in st.session_state:
        gaps = st.session_state["gaps_result"]
        if gaps["checked"] == 0:
            st.warning("No Epics or Features were found in the given input.")
        elif not gaps["unlinked"]:
            st.success(f"All {gaps['checked']} Epics/Features have linked test cases.")
        else:
            st.success(f"{gaps['checked']} Epics/Features checked. {len(gaps['unlinked'])} below are not linked with test cases.")
            st.dataframe(
                [
                    {"ID": g["url"], "Work Item": g["type"], "Title": g["title"]}
                    for g in gaps["unlinked"]
                ],
                hide_index=True,
                width="stretch",
                column_config={
                    "ID": st.column_config.LinkColumn("ID", display_text=r"edit/(\d+)"),
                    "Title": st.column_config.TextColumn("Title", width="large"),
                },
            )

with suite_tab:
    st.write("Creates a static suite that contains the test cases linked to an Epic or Feature.")
    suite_query_url = st.text_input(
        "Saved query URL (Epics/Features)",
        placeholder="https://dev.azure.com/<org>/<project>/_queries/query/<query-id>/",
        key="suite_query_url",
    )
    if st.button("Find Epics/Features", type="primary", key="find_suite_items"):
        st.session_state.pop("suite_items", None)
        match = re.search(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", suite_query_url or "")
        if not match:
            st.error("Enter a saved query URL that contains a query ID.")
        else:
            with st.spinner("Reading Epics and Features from the query..."):
                try:
                    items = link.get_epics_and_features(cached_saved_query_ids(match.group(0)))
                    st.session_state["suite_items"] = items
                    if items:
                        st.session_state["suite_name"] = items[0]["title"]
                except Exception as exc:
                    st.error(f"Could not read the query: {exc}")

    if "suite_items" in st.session_state:
        items = st.session_state["suite_items"]
        if not items:
            st.warning("No Epics or Features were found in the query.")
        else:
            def sync_suite_name() -> None:
                selected_id = st.session_state["suite_selected_item"].split(" - ", 1)[0]
                st.session_state["suite_name"] = next(
                    item["title"] for item in st.session_state["suite_items"] if str(item["id"]) == selected_id
                )

            options = {f"{item['id']} - {item['type']} - {item['title']}": item for item in items}
            selected_label = st.selectbox("Epic/Feature", list(options.keys()), key="suite_selected_item", on_change=sync_suite_name)
            selected = options[selected_label]

            suite_plan_col, suite_parent_col = st.columns(2)
            suite_plan_id = suite_plan_col.text_input("Test Plan ID", placeholder="e.g. 1234567", key="suite_plan_id")
            suite_parent_id = suite_parent_col.text_input("Parent suite ID", placeholder="e.g. 1234568", key="suite_parent_id")
            suite_name = st.text_input("New suite name", key="suite_name")

            if st.button("Find linked test cases", key="find_suite_tests"):
                st.session_state.pop("suite_preview", None)
                if not (suite_plan_id.strip().isdigit() and suite_parent_id.strip().isdigit()):
                    st.error("Enter a numeric Test Plan ID and Parent suite ID.")
                elif not suite_name.strip():
                    st.error("Enter a suite name.")
                else:
                    with st.spinner("Reading the linked test cases from Azure DevOps..."):
                        try:
                            st.session_state["suite_preview"] = {
                                "item": selected,
                                "plan_id": int(suite_plan_id),
                                "parent_suite_id": int(suite_parent_id),
                                "name": suite_name.strip(),
                                "test_cases": link.get_linked_test_cases(selected["id"]),
                            }
                        except Exception as exc:
                            st.error(f"Could not read the linked test cases: {exc}")

    if "suite_preview" in st.session_state:
        preview = st.session_state["suite_preview"]
        st.subheader(f"{preview['item']['type']} {preview['item']['id']}: {preview['item']['title']}")
        st.write(f"Linked test cases: {len(preview['test_cases'])}")
        if preview["test_cases"]:
            st.dataframe(
                [{"Test Case ID": str(tc["id"]), "Test Case Title": tc["title"]} for tc in preview["test_cases"]],
                hide_index=True,
                width="stretch",
                column_config={"Test Case Title": st.column_config.TextColumn("Test Case Title", width="large")},
            )
        if st.button(
            "Create static suite",
            type="primary",
            disabled=not preview["test_cases"],
            help=None if preview["test_cases"] else "No test cases are linked to this Epic/Feature.",
        ):
            with st.spinner("Creating the query-based suite..."):
                try:
                    suite_id = link.create_static_suite(
                        preview["plan_id"],
                        preview["parent_suite_id"],
                        preview["name"],
                        [tc["id"] for tc in preview["test_cases"]],
                    )
                    st.session_state.pop("suite_preview", None)
                    st.success(f"Created static suite {suite_id} '{preview['name']}' with {len(preview['test_cases'])} test cases in plan {preview['plan_id']}.")
                except Exception as exc:
                    st.error(f"Suite creation failed: {exc}")

st.iframe(
    """
    <script>
    const hiddenLabels
    const hideMenuItems = () => {
        const doc = window.parent.document;
        doc.querySelectorAll("[role='menuitem'], [role='menu'] li").forEach((item) => {
            if (hiddenLabels.includes(item.textContent.trim())) {
                item.style.display = "none";
            }
        });
    };
    new window.parent.MutationObserver(hideMenuItems).observe(window.parent.document.body, { childList: true, subtree: true });
    hideMenuItems();
    </script>
    """,
    height="content",
)

