# -*- coding: utf-8 -*-

"""
Azure DevOps WIQL Export Script (Improved)

- Runs a fixed WIQL filter
- Fetches work items in batches (project-scoped URL, per-batch error handling)
- Parses System.Description (HTML) using robust Regex-based text extraction
- Exports a styled Excel heatmap with specific column ordering
- Fixes: ID extraction, Static Color Filling, Freeze Panes
- Improvements: main() guard, urllib.parse.quote, better error messages,
                fetch_details at module level, proj_enc computed once
"""

import os
import sys
import re
from typing import List, Dict, Tuple
from datetime import datetime
from urllib.parse import quote

import requests
import pandas as pd
from requests.auth import HTTPBasicAuth
from bs4 import BeautifulSoup

from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# =====================================================
# CONFIGURATION
# =====================================================

ORG = "utcbis"
PROJECT_NAME = "Otis ONE Platform"
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_XLSX = f"otis_one_platform_features_heatmap_{timestamp}.xlsx"
TARGET_FIX_VERSION = "Dhruva"

PAT = os.getenv("AZDO_PAT")
if not PAT:
    print("ERROR: AZDO_PAT environment variable not set")
    print('Windows (PowerShell):   [Environment]::SetEnvironmentVariable("AZDO_PAT","<your_pat>", "User")')
    print('macOS/Linux (bash/zsh):  export AZDO_PAT="<your_pat>"')
    sys.exit(1)

AUTH = HTTPBasicAuth("", PAT)
HEADERS = {"Content-Type": "application/json"}

# =====================================================
# COLUMN MAPPINGS & ORDERING
# =====================================================

# 1. API Fields (Direct from ADO Work Item Fields)
# Map: ADO Field Name -> Excel Column Header
API_FIELD_MAP = {
    "System.Id": "ID",
    "System.Title": "Title",
    "System.AssignedTo": "Assigned To",
    "Custom.MeetsDoR": "MeetsDoR",
    "Custom.TestingScope": "Testing Scope",
    "Custom.Region": "Region",
    "Custom.SMEName": "SME",
    "Custom.ProductManager": "Product Manager",
    "Custom.ProductOwner": "Product Owner",
}

# 2. Parsed Description Fields (From HTML)
# Map: Normalized Description Key -> Excel Column Header
PARSED_FIELD_MAP = {
    "Acceptance Criteria": "Acceptance Criteria",
    "Feature Originator": "Feature Originator",
    "Feature Overview": "Feature Overview",
    "Design Requirements": "Design Requirements",
    "Applicable Geographic Regions": "Applicable Geographic Regions",
    "Controller Types": "Controller Types",
    "Controller Baseline firmware version": "Controller Baseline firmware version",
    "Non - functional requirements": "Non-functional requirements",  # ADO typo variant
    "Non-functional requirements": "Non-functional requirements",    # canonical form
    "Compatibility details with earlier releases": "Compatibility details with earlier releases",
    "OTA Inputs": "OTA Inputs",
    "Implementation Constraints": "Implementation Constraints",
    "Hardware dependency": "Hardware dependency",
    "Testing Constraints": "Testing Constraints",
    "Architecture Link": "Architecture Link",
    "Design Link": "Design Link",
    "DFMEA": "DFMEA",
    "Interface Documentation (ICD) Link": "Interface Documentation (ICD) Link",
    "Third party components dependency": "Third party components dependency",
    "Other External Dependencies": "Other External Dependencies",
}

# 3. Final Column Order (Strict Enforcement)
FINAL_COLUMN_ORDER = [
    "ID",
    "Title",
    "Assigned To",
    "MeetsDoR",
    "Testing Scope",
    "Acceptance Criteria",
    "Region",
    "SME",
    "Product Manager",
    "Product Owner",
]

# Append remaining parsed fields that aren't already in the specific list
for header in PARSED_FIELD_MAP.values():
    if header not in FINAL_COLUMN_ORDER:
        FINAL_COLUMN_ORDER.append(header)

# Ensure uniqueness and keep order
FINAL_COLUMN_ORDER = list(dict.fromkeys(FINAL_COLUMN_ORDER))

PLACEHOLDER_VALUES = {"", "-", "n/a", "na", "none", "nil", "tbd", "null", "?"}
ILLEGAL_XLSX_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
EXCEL_MAX_CELL_CHARS = 32000

# 4. Fields to Apply Yes/No Coloring
YES_NO_COLOR_FIELDS = [
    "MeetsDoR",
    "Testing Scope",
    "Acceptance Criteria",
    "Feature Overview",
    "Design Requirements",
]

# =====================================================
# HTML PARSING LOGIC
# =====================================================

def is_placeholder(value: str) -> bool:
    """True when the text is empty or a placeholder such as N/A or TBD."""
    return str(value).strip().lower() in PLACEHOLDER_VALUES


def clean_cell(value) -> str:
    """Make a value safe for Excel: drop illegal control characters and cap length."""
    text = ILLEGAL_XLSX_CHARS.sub("", str(value) if value is not None else "")
    return text[:EXCEL_MAX_CELL_CHARS]


def parse_html_description(html: str) -> Dict[str, str]:
    """Robust Regex-based parsing of the Description HTML into the PARSED_FIELD_MAP headers."""
    if not html:
        return {}

    soup = BeautifulSoup(html, "html.parser")

    # Pre-process lists for readability (prefix list items with "- " when extracted as text)
    for li in soup.find_all("li"):
        if li.string:
            s = li.string.strip()
            if not s.startswith("-"):
                li.string.replace_with(f"- {s}")
        else:
            # If the <li> has nested tags, prepend a dash visually
            li.insert(0, "- ")

    # Flatten to text preserving line breaks
    text = soup.get_text("\n", strip=True)

    # Build Regex Pattern from keys (longest keys first to avoid partial match issues)
    keys = list(PARSED_FIELD_MAP.keys())
    sorted_keys = sorted(keys, key=len, reverse=True)
    escaped_keys = [re.escape(k) for k in sorted_keys]
    keys_alt = '|'.join(escaped_keys)
    pattern = re.compile(
        rf"^[ \t]*({keys_alt})[^\n:]*:?[ \t]*$|({keys_alt})\s*:",
        flags=re.IGNORECASE | re.MULTILINE,
    )

    matches = list(pattern.finditer(text))
    result: Dict[str, str] = {}

    # Lowercase map for lookup
    key_map_lower = {k.lower(): v for k, v in PARSED_FIELD_MAP.items()}

    for i, match in enumerate(matches):
        matched_str = (match.group(1) or match.group(2)).lower()
        excel_header = key_map_lower.get(matched_str)
        if not excel_header:
            continue

        start_idx = match.end()
        end_idx = matches[i + 1].start() if (i + 1) < len(matches) else len(text)
        content = text[start_idx:end_idx].strip()

        # Clean leading punctuation if any
        content = re.sub(r"^\s*[:\-]\s*", "", content)

        result[excel_header] = content

    return result

# =====================================================
# API HELPERS
# =====================================================

def fetch_details(ids: List[str]) -> Tuple[List[dict], List[str]]:
    """Fetch full work item details in batches of 200. Returns (items, ids_that_failed)."""
    results: List[dict] = []
    failed: List[str] = []
    for i in range(0, len(ids), 200):
        batch = ids[i : i + 200]
        url = (
            f"https://dev.azure.com/{ORG}/{PROJECT_NAME}/_apis/wit/workitems"
            f"?ids={','.join(batch)}&$expand=all&api-version=7.0"
        )
        try:
            r = requests.get(url, headers=HEADERS, auth=AUTH, timeout=60)
            r.raise_for_status()
            results.extend(r.json().get("value", []))
        except (requests.RequestException, ValueError) as exc:
            print(f"WARNING: Batch {i}-{i + len(batch)} failed: {exc}")
            failed.extend(batch)
    return results, failed

# =====================================================
# MAIN
# =====================================================

def fetch_wiql_by_id(query_id: str) -> str:
    """Return the WIQL text of a saved Azure DevOps query by its GUID."""
    url = (
        f"https://dev.azure.com/{ORG}/{PROJECT_NAME}/_apis/wit/queries/{query_id}"
        f"?$expand=wiql&api-version=7.0"
    )
    r = requests.get(url, headers=HEADERS, auth=AUTH, timeout=30)
    r.raise_for_status()
    return r.json()["wiql"]


def main(query_text: str) -> None:
    # Preflight check
    if os.path.exists(OUTPUT_XLSX):
        try:
            with open(OUTPUT_XLSX, "a+"):
                pass
        except OSError:
            print(f"ERROR: '{OUTPUT_XLSX}' is open. Close it and retry.")
            sys.exit(1)

    # 1. WIQL QUERY
    wiql_url = f"https://dev.azure.com/{ORG}/{PROJECT_NAME}/_apis/wit/wiql?api-version=7.0"
    wiql_query = {"query": query_text}

    print("Running WIQL query ...")
    try:
        resp = requests.post(wiql_url, json=wiql_query, headers=HEADERS, auth=AUTH, timeout=30)
        resp.raise_for_status()
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        print(f"ERROR: WIQL request failed (HTTP {status}). Check your PAT and project name.")
        sys.exit(1)
    except requests.ConnectionError:
        print("ERROR: Could not connect to Azure DevOps. Check your network connection.")
        sys.exit(1)

    item_ids = [str(w["id"]) for w in resp.json().get("workItems", [])]

    if not item_ids:
        print("No items found. Nothing to export.")
        return

    print(f"Fetching {len(item_ids)} items...")
    items, failed_ids = fetch_details(item_ids)
    if failed_ids:
        print(f"WARNING: {len(failed_ids)} of {len(item_ids)} items could not be fetched and are missing from the export: {', '.join(failed_ids)}")

    # 2. BUILD DATAFRAME
    rows = []
    for item in items:
        f = item.get("fields", {})
        desc_html = f.get("System.Description", "") or ""
        parsed_data = parse_html_description(desc_html)

        row_data: Dict[str, str] = {}

        # A. Populate API Fields
        for api_key, header in API_FIELD_MAP.items():
            if api_key == "System.Id":
                val = item.get("id", "")
            else:
                val = f.get(api_key, "")

            # Handle identity objects like System.AssignedTo
            if isinstance(val, dict) and "displayName" in val:
                val = val.get("displayName", "")
            row_data[header] = clean_cell(val)

        # B. Populate Parsed Fields
        for header in PARSED_FIELD_MAP.values():
            raw_val = parsed_data.get(header, "")
            # For descriptive Yes/No columns, infer Yes if any real content exists
            if header in YES_NO_COLOR_FIELDS and header not in ["MeetsDoR", "Testing Scope"]:
                row_data[header] = "No" if is_placeholder(raw_val) else "Yes"
            else:
                row_data[header] = clean_cell(raw_val)

        # Ensure all columns exist
        for col in FINAL_COLUMN_ORDER:
            if col not in row_data:
                row_data[col] = ""

        rows.append(row_data)

    df = pd.DataFrame(rows)
    df = df[FINAL_COLUMN_ORDER]

    # 3. EXPORT & FORMATTING
    print("Generating Excel...")
    with pd.ExcelWriter(OUTPUT_XLSX, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Heatmap")
        ws = writer.sheets["Heatmap"]

        # Freeze Panes (Row 1 and Column A)
        ws.freeze_panes = "B2"

        # Styles
        header_fill = PatternFill("solid", fgColor="FFD966")
        yes_fill = PatternFill("solid", fgColor="C6EFCE")  # Green
        no_fill = PatternFill("solid", fgColor="F4B084")   # Orange
        red_fill = PatternFill("solid", fgColor="FFC7CE")  # Red

        border = Border(
            left=Side(style="thin"),
            right=Side(style="thin"),
            top=Side(style="thin"),
            bottom=Side(style="thin"),
        )

        # Header Styling
        for col_num, _col_title in enumerate(df.columns, 1):
            cell = ws.cell(row=1, column=col_num)
            cell.fill = header_fill
            cell.font = Font(bold=True)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.border = border
            ws.column_dimensions[get_column_letter(col_num)].width = 25

        # Pre-compute color column indices (1-based) - done once, not per row
        color_col_indices = [
            df.columns.get_loc(col) + 1
            for col in YES_NO_COLOR_FIELDS
            if col in df.columns
        ]

        # Pre-encode project name for hyperlinks - done once, not per row
        proj_enc = quote(PROJECT_NAME, safe="")

        # Content Styling
        for row_num in range(2, ws.max_row + 1):
            ws.row_dimensions[row_num].height = 60

            # Hyperlink on ID cell (Column 1)
            id_cell = ws.cell(row=row_num, column=1)
            if id_cell.value:
                id_cell.hyperlink = (
                    f"https://dev.azure.com/{ORG}/{proj_enc}"
                    f"/_workitems/edit/{id_cell.value}"
                )
                id_cell.style = "Hyperlink"

            for col_num in range(1, ws.max_column + 1):
                cell = ws.cell(row=row_num, column=col_num)
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                cell.border = border

                if col_num in color_col_indices:
                    val_str = str(cell.value).strip().lower()
                    if val_str in ("yes", "true"):
                        cell.fill = yes_fill
                    elif val_str in ("no", "false"):
                        cell.fill = no_fill
                    elif val_str == "wip":
                        cell.fill = red_fill

    print(f"Export completed: {OUTPUT_XLSX}")


if __name__ == "__main__":
    main()
