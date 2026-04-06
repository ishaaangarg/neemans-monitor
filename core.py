"""
Shared scraping + flag logic for Neeman's Listing Health Monitor.
Used by both monitor.py (CLI) and dashboard.py (web UI).
"""

import os
import random
import time
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from parsers import get_parser
from sheets import CatalogRow

SCRAPINGBEE_URL = "https://app.scrapingbee.com/api/v1/"
REQUEST_TIMEOUT = 30


# ──────────────────────────────────────────────
# ScrapingBee fetch
# ──────────────────────────────────────────────

def fetch_html(url: str) -> tuple[str | None, str | None]:
    api_key = os.environ.get("SCRAPINGBEE_API_KEY")
    if not api_key:
        return None, "SCRAPINGBEE_API_KEY not set."
    params = {
        "api_key": api_key,
        "url": url,
        "render_js": "true",
        "premium_proxy": "true",
        "country_code": "in",
    }
    try:
        resp = requests.get(SCRAPINGBEE_URL, params=params, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            return resp.text, None
        return None, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except requests.Timeout:
        return None, f"Timeout after {REQUEST_TIMEOUT}s"
    except requests.RequestException as exc:
        return None, str(exc)


def domain_from_url(url: str) -> str:
    return urlparse(url).netloc.lower()


# ──────────────────────────────────────────────
# Single listing scrape
# ──────────────────────────────────────────────

def scrape_listing(row: CatalogRow) -> dict:
    """Scrape one listing. Never raises — errors captured in result."""
    domain = domain_from_url(row.url)
    parser_fn = get_parser(domain)

    html, fetch_err = fetch_html(row.url)
    if fetch_err:
        return {
            "product_name": row.product_name,
            "platform": row.platform_name,
            "url": row.url,
            "price": None,
            "buy_box": False,
            "sizes": [],
            "colors": [],
            "flags": [f"FETCH ERROR: {fetch_err}"],
            "status": "ERROR",
            "error": fetch_err,
        }

    soup = BeautifulSoup(html, "html.parser")
    parsed = parser_fn(soup)

    return {
        "product_name": row.product_name,
        "platform": row.platform_name,
        "url": row.url,
        "price": parsed.get("price"),
        "buy_box": parsed.get("buy_box", False),
        "sizes": parsed.get("sizes", []),
        "colors": parsed.get("colors", []),
        "flags": [],
        "status": "GREEN",
        "error": parsed.get("error"),
    }


# ──────────────────────────────────────────────
# Flag computation
# ──────────────────────────────────────────────

def compute_flags(results: list[dict]) -> list[dict]:
    """Attach flags and statuses to a list of same-product results."""
    valid = [r for r in results if not r.get("error")]
    errored = [r for r in results if r.get("error")]

    for r in errored:
        r["flags"].append(f"PARSE ERROR on {r['platform']}: {r['error']}")

    for r in valid:
        if not r["buy_box"]:
            r["flags"].append(f"NOT PURCHASABLE on {r['platform']}")

    prices = {r["platform"]: r["price"] for r in valid if r["price"] is not None}
    if len(prices) >= 2:
        min_plat = min(prices, key=prices.get)
        max_plat = max(prices, key=prices.get)
        gap = prices[max_plat] - prices[min_plat]
        if gap > 50:
            ref = [p for p, v in prices.items() if v == prices[max_plat]]
            cheap = [p for p, v in prices.items() if v == prices[min_plat]]
            flag_msg = f"PRICE GAP ₹{gap:,}: {', '.join(cheap)} cheaper than {', '.join(ref)}"
            for r in results:
                if r["platform"] in prices:
                    r["flags"].append(flag_msg)
                    break

    parseable_sizes = {
        r["platform"]: set(r["sizes"])
        for r in valid
        if r["sizes"] and r["sizes"] != ["Could not parse"]
    }
    if len(parseable_sizes) >= 2:
        all_sizes = set().union(*parseable_sizes.values())
        for r in valid:
            if r["platform"] in parseable_sizes:
                missing = all_sizes - parseable_sizes[r["platform"]]
                if missing:
                    r["flags"].append(f"MISSING SIZES on {r['platform']}: {', '.join(sorted(missing))}")

    parseable_colors = {
        r["platform"]: set(r["colors"])
        for r in valid
        if r["colors"] and r["colors"] != ["Could not parse"]
    }
    if len(parseable_colors) >= 2:
        all_colors = set().union(*parseable_colors.values())
        for r in valid:
            if r["platform"] in parseable_colors:
                missing = all_colors - parseable_colors[r["platform"]]
                if missing:
                    r["flags"].append(f"MISSING COLORS on {r['platform']}: {', '.join(sorted(missing))}")

    for r in results:
        n = len(r["flags"])
        if r.get("error"):
            r["status"] = "ERROR"
        elif n == 0:
            r["status"] = "GREEN"
        elif n <= 2:
            r["status"] = "YELLOW"
        else:
            r["status"] = "RED"
        if any("NOT PURCHASABLE" in f or "PARSE ERROR" in f or "FETCH ERROR" in f for f in r["flags"]):
            r["status"] = "RED"

    return results


def product_status(results: list[dict]) -> str:
    order = {"ERROR": 3, "RED": 2, "YELLOW": 1, "GREEN": 0}
    return max((r["status"] for r in results), key=lambda s: order.get(s, 0))


def collect_product_flags(results: list[dict]) -> list[str]:
    seen, flags = set(), []
    for r in results:
        for f in r["flags"]:
            if f not in seen:
                seen.add(f)
                flags.append(f)
    return flags


# ──────────────────────────────────────────────
# Full run (used by CLI; dashboard calls scrape_listing directly for live progress)
# ──────────────────────────────────────────────

def run_scrape(
    catalog_rows: list[CatalogRow],
    progress_callback=None,   # callable(product, platform, index, total)
    delay: bool = True,
) -> tuple[list[dict], dict[str, list[str]], str]:
    """
    Scrape all rows, compute flags, return:
        (all_results, flags_by_product, timestamp)
    progress_callback is called before each request so callers can update UI.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    by_product: dict[str, list[CatalogRow]] = defaultdict(list)
    for row in catalog_rows:
        by_product[row.product_name].append(row)

    all_results: list[dict] = []
    flags_by_product: dict[str, list[str]] = {}
    total = sum(len(v) for v in by_product.values())
    idx = 0

    for product_name, rows in by_product.items():
        product_results = []
        for i, row in enumerate(rows):
            if progress_callback:
                progress_callback(product_name, row.platform_name, idx, total)
            result = scrape_listing(row)
            product_results.append(result)
            idx += 1
            if delay and i < len(rows) - 1:
                time.sleep(random.uniform(1, 3))

        product_results = compute_flags(product_results)
        all_results.extend(product_results)
        flags_by_product[product_name] = collect_product_flags(product_results)

    return all_results, flags_by_product, timestamp
