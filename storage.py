"""
Local file storage for Neeman's Listing Health Monitor.
Replaces Google Sheets — catalog and reports are stored as CSV files.

catalog.csv  — user-managed product/platform list
reports.csv  — auto-appended after every run
"""

import csv
import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).parent

CATALOG_FILE = BASE_DIR / "catalog.csv"
REPORTS_FILE = BASE_DIR / "reports.csv"

CATALOG_HEADERS = ["Product Internal Name", "Platform Name", "Platform URL", "Active"]

REPORTS_HEADERS = [
    "Run Timestamp", "Product Name", "Platform", "Price",
    "Buy Box", "Sizes Available", "Colors Available", "Flags", "Status",
]


@dataclass
class CatalogRow:
    product_name: str
    platform_name: str
    url: str
    active: bool


# ──────────────────────────────────────────────
# Catalog
# ──────────────────────────────────────────────

def _ensure_catalog():
    """Create an empty catalog file with headers if it doesn't exist."""
    if not CATALOG_FILE.exists():
        with open(CATALOG_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CATALOG_HEADERS)
            writer.writeheader()


def read_catalog(skip_inactive: bool = True) -> list[CatalogRow]:
    _ensure_catalog()
    rows = []
    with open(CATALOG_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for rec in reader:
            active_val = str(rec.get("Active", "TRUE")).strip().upper()
            active = active_val in ("TRUE", "1", "YES")
            if skip_inactive and not active:
                continue
            rows.append(CatalogRow(
                product_name=str(rec.get("Product Internal Name", "")).strip(),
                platform_name=str(rec.get("Platform Name", "")).strip(),
                url=str(rec.get("Platform URL", "")).strip(),
                active=active,
            ))
    return rows


def write_catalog(rows: list[dict]) -> None:
    """
    Overwrite catalog.csv with a list of dicts.
    Each dict should have keys matching CATALOG_HEADERS.
    """
    with open(CATALOG_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CATALOG_HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def catalog_as_dicts(include_inactive: bool = True) -> list[dict]:
    """Return catalog rows as plain dicts (for st.data_editor)."""
    _ensure_catalog()
    rows = []
    with open(CATALOG_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for rec in reader:
            if not include_inactive:
                active_val = str(rec.get("Active", "TRUE")).strip().upper()
                if active_val not in ("TRUE", "1", "YES"):
                    continue
            rows.append({
                "Product Internal Name": rec.get("Product Internal Name", ""),
                "Platform Name": rec.get("Platform Name", ""),
                "Platform URL": rec.get("Platform URL", ""),
                "Active": str(rec.get("Active", "TRUE")).strip().upper() in ("TRUE", "1", "YES"),
            })
    return rows


# ──────────────────────────────────────────────
# Reports
# ──────────────────────────────────────────────

def _ensure_reports():
    if not REPORTS_FILE.exists():
        with open(REPORTS_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=REPORTS_HEADERS)
            writer.writeheader()


def write_report_rows(report_rows: list[dict], timestamp: str) -> None:
    _ensure_reports()
    with open(REPORTS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REPORTS_HEADERS)
        for row in report_rows:
            writer.writerow({
                "Run Timestamp": timestamp,
                "Product Name": row.get("product_name", ""),
                "Platform": row.get("platform", ""),
                "Price": row.get("price", ""),
                "Buy Box": "Yes" if row.get("buy_box") else "No",
                "Sizes Available": ", ".join(row.get("sizes", [])),
                "Colors Available": ", ".join(row.get("colors", [])),
                "Flags": " | ".join(row.get("flags", [])),
                "Status": row.get("status", ""),
            })


def read_reports() -> list[dict]:
    _ensure_reports()
    rows = []
    with open(REPORTS_FILE, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for rec in reader:
            rows.append(dict(rec))
    return rows


def reports_as_csv_bytes() -> bytes:
    """Return the full reports CSV as bytes for st.download_button."""
    _ensure_reports()
    return REPORTS_FILE.read_bytes()


def catalog_as_csv_bytes() -> bytes:
    _ensure_catalog()
    return CATALOG_FILE.read_bytes()
