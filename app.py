# -*- coding: utf-8 -*-

"""
ADO Tool Kit (Streamlit)

- Export Heatmap: runs the WIQL export and offers the Excel file for download
- Link Tests: links Test Cases under an Area Path to an Epic

PAT is read from config.json (git-ignored) next to this file, or from AZDO_PAT if set.
"""

import json
import os
import re
import sys
from typing import Dict, List
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

BASE_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.json"
DEFAULT_QUERY_PATH = BASE_DIR / "default_query.wiql"

if not os.getenv("AZDO_PAT") and CONFIG_PATH.exists():
    os.environ["AZDO_PAT"] = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("pat", "")

st.set_page_config(page_title="ADO Tool Kit", layout="wide")
st.markdown(
    "<style>div[data-testid='InputInstructions'], [data-testid='stAppDeployButton'] {display: none;} div[data-testid='stMainBlockContainer'] {padding-top: 2rem; padding-left: 3rem; padding-right: 3rem;}</style>",
    unsafe_allow_html=True,
)
st.title("ADO Tool Kit")

if not os.getenv("AZDO_PAT"):
    st.error(f"No PAT found. Add \"pat\" to {CONFIG_PATH.name} or set AZDO_PAT.")
    st.stop()

import link_tests_to_epic as link  # noqa: E402
import AzureDevOpsHeatmap_improved_fixed as heatmap  # noqa: E402
import pipelines_ado as pipes  # noqa: E402


@st.cache_data(ttl=300, show_spinner=False)
def cached_query_ids(query_text: str) -> list:
    return link.run_wiql(query_text)


@st.cache_data(ttl=300, show_spinner=False)
def cached_saved_query_ids(query_id: str) -> list:
    return link.run_wiql(heatmap.fetch_wiql_by_id(query_id))


@st.cache_data(ttl=300, show_spinner=False)
def cached_coverage_summary(query_id: str) -> dict:
    return link.get_coverage_summary(cached_saved_query_ids(query_id))


@st.cache_data(ttl=300, show_spinner=False)
def cached_feature_sprints(query_id: str) -> list:
    return link.get_feature_sprints(cached_saved_query_ids(query_id))


@st.cache_data(ttl=300, show_spinner=False)
def cached_epic_sprints(query_id: str) -> list:
    return link.get_epic_sprints(cached_saved_query_ids(query_id))


def sprint_order(iteration_path: str) -> tuple:
    parts = iteration_path.split("\\")
    pi_name = parts[-2] if len(parts) >= 2 else ""
    sprint = parts[-1] if parts else ""
    pi_match = re.search(r"PI(\d+)([A-Z])", pi_name)
    sprint_match = re.search(r"(\d+)$", sprint)
    pi_key = (int(pi_match.group(1)), pi_match.group(2)) if pi_match else (0, "")
    return (*pi_key, int(sprint_match.group(1)) if sprint_match else 0)

def sync_query_url(widget_key: str) -> None:
    st.session_state["saved_query_url"] = st.session_state[widget_key]


def saved_query_url_input(widget_key: str) -> str:
    return st.text_input(
        "Saved query URL (Epics/Features)",
        value=st.session_state.get("saved_query_url", ""),
        placeholder="https://dev.azure.com/<org>/<project>/_queries/query/<query-id>/",
        key=widget_key,
        on_change=sync_query_url,
        args=(widget_key,),
    )


export_tab, link_tab, suite_tab, dashboard_tab, sprint_tab, pipeline_tab = st.tabs(["Generate Heatmap", "Link Test Cases to Epic/Feature", "Create New Test Suite by Epics/Feature", "Dashboards", "Epics/Features expected by sprint", "Pipelines"])

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
        query_url = saved_query_url_input("export_query_url")
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

with suite_tab:
    st.write("Creates a static suite that contains the test cases linked to an Epic or Feature.")
    suite_query_url = saved_query_url_input("suite_query_url")
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

with dashboard_tab:
    st.write("Counts and lists of Epics/Features that have linked test cases and those that do not.")
    dash_query_url = saved_query_url_input("dash_query_url")
    if st.button("Load dashboard", type="primary", key="load_dashboard"):
        match = re.search(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", dash_query_url or "")
        if not match:
            st.session_state.pop("dash_summary", None)
            st.error("Enter a saved query URL that contains a query ID.")
        else:
            with st.spinner("Reading Epics and Features and their test links..."):
                try:
                    st.session_state["dash_summary"] = cached_coverage_summary(match.group(0))
                except Exception as exc:
                    st.error(f"Could not load the dashboard: {exc}")

    if "dash_summary" in st.session_state:
        summary = st.session_state["dash_summary"]
        linked, unlinked = summary["linked"], summary["unlinked"]
        total = len(linked) + len(unlinked)

        metric_total, metric_linked, metric_unlinked, metric_coverage = st.columns(4)
        metric_total.metric("Epics/Features", total)
        metric_linked.metric("With linked tests", len(linked))
        metric_unlinked.metric("With no linked tests", len(unlinked))
        metric_coverage.metric("Coverage", f"{(len(linked) / total * 100):.0f}%" if total else "0%")

        if total:
            chart_data = pd.DataFrame(
                {"Status": ["With linked tests", "With no linked tests"], "Count": [len(linked), len(unlinked)]}
            )
            donut = (
                alt.Chart(chart_data)
                .mark_arc(innerRadius=60, outerRadius=110)
                .encode(
                    theta=alt.Theta("Count:Q"),
                    color=alt.Color(
                        "Status:N",
                        scale=alt.Scale(domain=["With linked tests", "With no linked tests"], range=["#339947", "#B20B1E"]),
                        legend=alt.Legend(orient="bottom", title=None),
                    ),
                    tooltip=["Status:N", "Count:Q"],
                )
                .properties(height=320)
            )
            st.subheader("Coverage of Epics/Features")
            st.altair_chart(donut, width="stretch")

        link_col, unlink_col = st.columns(2)
        column_config = {
            "ID": st.column_config.LinkColumn("ID", display_text=r"edit/(\d+)"),
            "Title": st.column_config.TextColumn("Title", width="large"),
        }
        with link_col:
            st.subheader(f"With linked test cases ({len(linked)})")
            if linked:
                st.dataframe(
                    [{"ID": i["url"], "Work Item": i["type"], "Title": i["title"], "Test cases": i["tests"]} for i in linked],
                    hide_index=True,
                    width="stretch",
                    height=400,
                    column_config={**column_config, "Test cases": st.column_config.NumberColumn("Test cases")},
                )
            else:
                st.info("No work items with linked test cases.")
        with unlink_col:
            st.subheader(f"With no linked test cases ({len(unlinked)})")
            if unlinked:
                st.dataframe(
                    [{"ID": i["url"], "Work Item": i["type"], "Title": i["title"]} for i in unlinked],
                    hide_index=True,
                    width="stretch",
                    height=400,
                    column_config=column_config,
                )
            else:
                st.info("Every work item has linked test cases.")

with sprint_tab:
    st.subheader("Epics / Features expected by sprint")
    st.caption("An Epic's expected sprint is the last sprint among its child Features. Epics with no child Features are skipped. If the saved query has Features, they are listed by their own sprint. Titles containing SST are excluded.")
    sprint_query_url = saved_query_url_input("sprint_query_url")
    if st.button("Load sprint plan", key="load_sprint_plan"):
        match = re.search(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", sprint_query_url or "")
        if not match:
            st.session_state.pop("sprint_plan", None)
            st.session_state.pop("feature_plan", None)
            st.error("Enter a saved query URL in the field above to load the sprint plan.")
        else:
            with st.spinner("Reading the saved query items..."):
                try:
                    st.session_state["sprint_plan"] = cached_epic_sprints(match.group(0))
                    st.session_state["feature_plan"] = cached_feature_sprints(match.group(0))
                except Exception as exc:
                    st.error(f"Could not load the sprint plan: {exc}")

    if "sprint_plan" in st.session_state or "feature_plan" in st.session_state:
        epic_total = len(st.session_state.get("sprint_plan", []))
        feature_total = len(st.session_state.get("feature_plan", []))
        if epic_total:
            st.write(f"Total Epics in saved query: {epic_total}")
        else:
            st.write(f"Total Features in saved query: {feature_total}")

    if "sprint_plan" in st.session_state:
        plan = st.session_state["sprint_plan"]
        expected_by_sprint: Dict[str, List[Dict[str, object]]] = {}
        for epic in plan:
            sprint_features = [f for f in epic["features"] if re.match(r"^\d+[A-Z]\d+$", f["iteration"].split("\\")[-1])]
            if not sprint_features:
                continue
            last_feature = max(sprint_features, key=lambda f: sprint_order(f["iteration"]))
            expected_by_sprint.setdefault(last_feature["iteration"], []).append(
                {"ID": epic["id"], "Epic": epic["title"], "State": epic["state"], "Last Feature sprint": last_feature["iteration"].split("\\")[-1], "Features": len(epic["features"])}
            )
        sprint_names = sorted(expected_by_sprint, key=sprint_order)
        st.markdown("### Epics expected by sprint")
        if not sprint_names:
            st.info("No Epics with child Features were found in the saved query.")
        else:
            default_index = sprint_names.index(next((s for s in sprint_names if s.endswith("\\26C7")), sprint_names[-1]))
            selected_sprint = st.selectbox("Sprint", sprint_names, index=default_index, format_func=lambda s: s.split("\\", 1)[-1], key="sprint_select")
            rows = expected_by_sprint[selected_sprint]
            st.metric(f"Epics expected in {selected_sprint.split(chr(92))[-1]}", len(rows))
            st.dataframe(
                rows,
                hide_index=True,
                width="stretch",
                height=400,
                column_config={
                    "ID": st.column_config.NumberColumn("ID", format="%d"),
                    "Epic": st.column_config.TextColumn("Epic", width="large"),
                },
            )

    if st.session_state.get("feature_plan"):
        feature_by_sprint: Dict[str, List[Dict[str, object]]] = {}
        for feature in st.session_state["feature_plan"]:
            if not re.match(r"^\d+[A-Z]\d+$", feature["iteration"].split("\\")[-1]):
                continue
            feature_by_sprint.setdefault(feature["iteration"], []).append(
                {"ID": feature["id"], "Feature": feature["title"], "State": feature["state"]}
            )
        feature_sprints = sorted(feature_by_sprint, key=sprint_order)
        st.markdown("### Features expected by sprint")
        if feature_sprints:
            feature_default = feature_sprints.index(next((s for s in feature_sprints if s.endswith("\\26C7")), feature_sprints[-1]))
            selected_feature_sprint = st.selectbox("Feature sprint", feature_sprints, index=feature_default, format_func=lambda s: s.split("\\", 1)[-1], key="feature_sprint_select")
            feature_rows = feature_by_sprint[selected_feature_sprint]
            st.metric(f"Features expected in {selected_feature_sprint.split(chr(92))[-1]}", len(feature_rows))
            st.dataframe(
                feature_rows,
                hide_index=True,
                width="stretch",
                height=400,
                column_config={
                    "ID": st.column_config.NumberColumn("ID", format="%d"),
                    "Feature": st.column_config.TextColumn("Feature", width="large"),
                },
            )
        else:
            st.info("No Features with a sprint in their iteration path were found in the saved query.")

@st.cache_data(ttl=300, show_spinner=False)
def cached_pipeline_definitions() -> list:
    return pipes.list_pipeline_definitions()


@st.cache_data(ttl=300, show_spinner=False)
def cached_builds(definition_id, branch: str, days: int) -> list:
    return pipes.list_builds(definition_id, branch, days)


@st.cache_data(ttl=300, show_spinner=False)
def cached_deployments() -> list:
    return pipes.list_deployments()


with pipeline_tab:
    definitions = cached_pipeline_definitions()
    pipeline_options: Dict[str, object] = {"All pipelines": None, **{d["name"]: d["id"] for d in definitions}}
    col_pipeline, col_branch, col_days = st.columns([3, 2, 1])
    with col_pipeline:
        pipeline_name = st.selectbox("Pipeline", list(pipeline_options), key="pipe_definition")
    with col_branch:
        pipe_branch = st.text_input("Branch (optional)", value="", placeholder="main", key="pipe_branch")
    with col_days:
        pipe_days = st.number_input("Days back", min_value=1, max_value=365, value=30, key="pipe_days")

    runs_tab, results_tab, deploy_tab, queue_tab = st.tabs(["Runs", "Test results", "Deployments", "Queue"])

    with runs_tab:
        st.markdown("### Pipeline runs")
        try:
            builds = cached_builds(pipeline_options[pipeline_name], pipe_branch.strip(), int(pipe_days))
        except Exception as exc:
            builds = []
            st.error(f"Could not load pipeline runs: {exc}")
        if builds:
            builds_df = pd.DataFrame(builds)
            result_filter = st.multiselect("Result", sorted(builds_df["Result"].unique()), default=sorted(builds_df["Result"].unique()), key="pipe_results")
            filtered_df = builds_df[builds_df["Result"].isin(result_filter)]
            total_runs = len(filtered_df)
            pass_count = int((filtered_df["Result"] == "succeeded").sum())
            finished_count = int(filtered_df["Result"].isin(["succeeded", "failed", "partiallySucceeded", "canceled"]).sum())
            metric_cols = st.columns(4)
            metric_cols[0].metric("Runs", f"{total_runs} of {len(builds_df)}")
            metric_cols[1].metric("Succeeded", pass_count)
            metric_cols[2].metric("Failed", int((filtered_df["Result"] == "failed").sum()))
            metric_cols[3].metric("Pass rate", f"{(pass_count / finished_count * 100):.1f}%" if finished_count else "n/a")
            st.dataframe(filtered_df, hide_index=True, width="stretch", height=400)
            st.download_button("Download runs (CSV)", filtered_df.to_csv(index=False).encode("utf-8"), "pipeline_runs.csv", "text/csv", key="pipe_runs_csv")

            finished = builds_df[builds_df["Result"].isin(["succeeded", "failed", "partiallySucceeded", "canceled"])].copy()
            if not finished.empty:
                finished["Passed"] = (finished["Result"] == "succeeded").astype(int)
                trend = finished.groupby("Date").agg(runs=("Passed", "size"), passed=("Passed", "sum")).reset_index()
                trend["Pass rate (%)"] = (trend["passed"] / trend["runs"] * 100).round(1)
                st.markdown("### Pass rate trend")
                trend_chart = alt.Chart(trend).mark_line(point=True).encode(
                    x=alt.X("Date:T", title="Date"),
                    y=alt.Y("Pass rate (%):Q", scale=alt.Scale(domain=[0, 100])),
                    tooltip=["Date", "runs", "Pass rate (%)"],
                ).properties(height=300)
                st.altair_chart(trend_chart, width="stretch")
        else:
            builds = []
            st.info("No pipeline runs found for the selected filters.")

    with results_tab:
        st.markdown("### Test results for a run")
        if builds:
            build_choices = {f"{b['Pipeline']} #{b['Build number']} ({b['Result']})": b["Build ID"] for b in builds}
            selected_build = st.selectbox("Run", list(build_choices), key="pipe_build_select")
            if st.button("Load test results", key="load_test_results"):
                try:
                    summary = pipes.get_build_test_summary(int(build_choices[selected_build]))
                    st.session_state["test_summary"] = summary
                except Exception as exc:
                    st.session_state.pop("test_summary", None)
                    st.error(f"Could not load test results: {exc}")
            if "test_summary" in st.session_state:
                summary = st.session_state["test_summary"]
                result_cols = st.columns(4)
                result_cols[0].metric("Total", summary["Total"])
                result_cols[1].metric("Passed", summary["Passed"])
                result_cols[2].metric("Failed", summary["Failed"])
                result_cols[3].metric("Other", summary["Other"])
                if summary["Failing tests"]:
                    st.dataframe(pd.DataFrame({"Failing test": summary["Failing tests"]}), hide_index=True, width="stretch", height=400)
                else:
                    st.info("No failing tests in this run.")
        else:
            st.info("No runs available. Adjust the filters on the Runs tab.")

    with deploy_tab:
        st.markdown("### Deployments")
        if st.button("Load deployments", key="load_deployments"):
            try:
                st.session_state["deployments"] = cached_deployments()
            except Exception as exc:
                st.session_state.pop("deployments", None)
                st.error(f"Could not load deployments: {exc}")
        if "deployments" in st.session_state:
            deployments = st.session_state["deployments"]
            if deployments:
                deployments_df = pd.DataFrame(deployments)
                st.metric("Deployments", len(deployments_df))
                st.dataframe(deployments_df, hide_index=True, width="stretch", height=400)
                st.download_button("Download deployments (CSV)", deployments_df.to_csv(index=False).encode("utf-8"), "deployments.csv", "text/csv", key="deploy_csv")
            else:
                st.info("No deployments found.")

    with queue_tab:
        st.markdown("### Queue a pipeline run")
        queue_options = {name: value for name, value in pipeline_options.items() if value is not None}
        if queue_options:
            queue_name = st.selectbox("Pipeline to queue", list(queue_options), key="queue_definition")
            queue_branch = st.text_input("Branch to run", value="main", key="queue_branch")
            if st.button("Queue run", key="queue_run"):
                if not queue_branch.strip():
                    st.error("Enter a branch name.")
                else:
                    st.session_state["pending_queue"] = (queue_name, queue_branch.strip())
            pending = st.session_state.get("pending_queue")
            if pending:
                pending_name, pending_branch = pending
                st.warning(f"Confirm: queue '{pending_name}' on branch '{pending_branch}'?")
                confirm_col, cancel_col = st.columns(2)
                with confirm_col:
                    if st.button("Confirm queue", key="confirm_queue", type="primary"):
                        st.session_state.pop("pending_queue", None)
                        try:
                            queued = pipes.queue_build(int(queue_options[pending_name]), pending_branch)
                            st.success(f"Queued build #{queued.get('buildNumber', queued.get('id'))} on {pending_branch}.")
                            cached_builds.clear()
                        except Exception as exc:
                            st.error(f"Could not queue the run: {exc}")
                with cancel_col:
                    if st.button("Cancel", key="cancel_queue"):
                        st.session_state.pop("pending_queue", None)
                        st.rerun()

st.iframe(
    """
    <script>
    const hiddenLabels = ["Print", "Record screen"];
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

