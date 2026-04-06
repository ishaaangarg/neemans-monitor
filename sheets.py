"""
Google Sheets integration for Neeman's Listing Health Monitor.

Reads the "Catalog" tab and writes results to the "Reports" tab
using a service-account JSON credential file.

Environment variables required:
    GOOGLE_SHEETS_CREDENTIALS_PATH  — path to service-account JSON
    GOOGLE_SHEET_ID                 — the spreadsheet ID from the URL
"""

import os
from dataclasses import dataclass
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

CATALOG_SHEET = "Catalog"
REPORTS_SHEET = "Reports"

REPORTS_HEADERS = [
    "Run Timestamp",
    "Product Name",
    "Platform",
    "Price",
    "Buy Box",
    "Sizes Available",
    "Colors Available",
    "Flags",
    "Status",
]


@dataclass
class CatalogRow:
    product_name: str
    platform_name: str
    url: str
    active: bool


def _get_client() -> gspread.Client:
    """
    Build a gspread client from credentials. Supports three sources (checked in order):
      1. GOOGLE_SHEETS_CREDENTIALS_JSON  — full JSON content as a string (cloud-friendly)
      2. GOOGLE_SHEETS_CREDENTIALS_PATH  — path to a local JSON file
      3. Raises EnvironmentError if neither is set
    """
    import json as _json

    json_str = os.environ.get("GOOGLE_SHEETS_CREDENTIALS_JSON")
    if json_str:
        try:
            info = _json.loads(json_str)
        except _json.JSONDecodeError as exc:
            raise ValueError(f"GOOGLE_SHEETS_CREDENTIALS_JSON is not valid JSON: {exc}")
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        return gspread.authorize(creds)

    creds_path = os.environ.get("GOOGLE_SHEETS_CREDENTIALS_PATH")
    if creds_path:
        if not os.path.isfile(creds_path):
            raise FileNotFoundError(
                f"Service-account credentials file not found: {creds_path}"
            )
        creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        return gspread.authorize(creds)

    raise EnvironmentError(
        "No Google credentials found. Set either:\n"
        "  • GOOGLE_SHEETS_CREDENTIALS_JSON (JSON string) — recommended for cloud\n"
        "  • GOOGLE_SHEETS_CREDENTIALS_PATH (file path)   — for local use"
    )


def _get_spreadsheet(client: gspread.Client) -> gspread.Spreadsheet:
    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    if not sheet_id:
        raise EnvironmentError("GOOGLE_SHEET_ID environment variable is not set.")
    return client.open_by_key(sheet_id)


def read_catalog(skip_inactive: bool = True) -> list[CatalogRow]:
    """
    Read all rows from the "Catalog" sheet.
    Returns a list of CatalogRow objects.
    Rows with Active = FALSE are excluded when skip_inactive=True.
    """
    client = _get_client()
    spreadsheet = _get_spreadsheet(client)

    try:
        worksheet = spreadsheet.worksheet(CATALOG_SHEET)
    except gspread.WorksheetNotFound:
        raise ValueError(
            f'Sheet "{CATALOG_SHEET}" not found. '
            "Please create it with columns: "
            "Product Internal Name | Platform Name | Platform URL | Active"
        )

    records = worksheet.get_all_records(expected_headers=[
        "Product Internal Name",
        "Platform Name",
        "Platform URL",
        "Active",
    ])

    rows = []
    for rec in records:
        active_val = str(rec.get("Active", "TRUE")).strip().upper()
        active = active_val in ("TRUE", "1", "YES")
        if skip_inactive and not active:
            continue
        rows.append(
            CatalogRow(
                product_name=str(rec.get("Product Internal Name", "")).strip(),
                platform_name=str(rec.get("Platform Name", "")).strip(),
                url=str(rec.get("Platform URL", "")).strip(),
                active=active,
            )
        )
    return rows


def ensure_reports_sheet(spreadsheet: gspread.Spreadsheet) -> gspread.Worksheet:
    """Create the Reports sheet with headers if it doesn't exist."""
    try:
        ws = spreadsheet.worksheet(REPORTS_SHEET)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=REPORTS_SHEET, rows=1000, cols=len(REPORTS_HEADERS))
        ws.append_row(REPORTS_HEADERS, value_input_option="RAW")
    return ws


def write_report_rows(report_rows: list[dict], timestamp: str) -> None:
    """
    Append report rows to the "Reports" sheet.

    Each dict in report_rows should have keys matching REPORTS_HEADERS
    (minus "Run Timestamp", which is injected here).
    """
    client = _get_client()
    spreadsheet = _get_spreadsheet(client)
    ws = ensure_reports_sheet(spreadsheet)

    rows_to_append = []
    for row in report_rows:
        rows_to_append.append([
            timestamp,
            row.get("product_name", ""),
            row.get("platform", ""),
            row.get("price", ""),
            "Yes" if row.get("buy_box") else "No",
            ", ".join(row.get("sizes", [])),
            ", ".join(row.get("colors", [])),
            " | ".join(row.get("flags", [])),
            row.get("status", ""),
        ])

    if rows_to_append:
        ws.append_rows(rows_to_append, value_input_option="RAW")
