"""
Shared scraping + flag logic for Neeman's Listing Health Monitor.
Used by both monitor.py (CLI) and dashboard.py (web UI).
"""

import os
import re
import random
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from parsers import get_parser
from storage import CatalogRow

SCRAPINGBEE_URL = "https://app.scrapingbee.com/api/v1/"
REQUEST_TIMEOUT = 90  # increased — FK/Myntra need more time with stealth proxy

MIN_IMAGES      = 5
MIN_TITLE_WORDS = 5

# Folder where raw HTML dumps are saved for debugging
DEBUG_DIR = Path("debug_html")


# ──────────────────────────────────────────────
# ScrapingBee fetch
# ──────────────────────────────────────────────

# Sites that need stealth proxy (extra anti-bot measures)
_STEALTH_DOMAINS = {"flipkart.com", "www.flipkart.com", "myntra.com", "www.myntra.com"}

def fetch_html(url: str, save_debug: bool = True) -> tuple[str | None, str | None]:
    api_key = os.environ.get("SCRAPINGBEE_API_KEY")
    if not api_key:
        return None, "SCRAPINGBEE_API_KEY not set."
    url = url.strip()
    domain = urlparse(url).netloc.lower()
    stealth = domain in _STEALTH_DOMAINS

    params = {
        "api_key":        api_key,
        "url":            url,
        "render_js":      "true",
        "stealth_proxy":  "true" if stealth else "false",
        "premium_proxy":  "true",
        "country_code":   "in",
        "block_resources":"false",
        "wait":           "4000" if stealth else "2000",
        "window_width":   "1920",
        "window_height":  "1080",
    }
    try:
        resp = requests.get(SCRAPINGBEE_URL, params=params, timeout=REQUEST_TIMEOUT)
        html = resp.text

        # ── Save raw HTML for debugging (always, silently)
        if save_debug and html:
            try:
                DEBUG_DIR.mkdir(exist_ok=True)
                safe = re.sub(r"[^\w\-]", "_", domain)
                debug_file = DEBUG_DIR / f"{safe}.html"
                debug_file.write_text(html, encoding="utf-8", errors="replace")
            except Exception:
                pass  # never let debug saving crash the scrape

        if resp.status_code == 200:
            return html, None
        return None, f"HTTP {resp.status_code}: {html[:300]}"
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
            "platform":     row.platform_name,
            "url":          row.url,
            "price":        None,
            "title":        None,
            "title_ok":     None,
            "images_count": 0,
            "buy_box":      False,
            "in_stock":     False,
            "sold_by":      None,
            "sizes":              [],
            "sizes_unavailable":  [],
            "colors":             [],
            "colors_unavailable": [],
            "flags":        [f"FETCH ERROR: {fetch_err}"],
            "status":       "ERROR",
            "error":        fetch_err,
        }

    soup = BeautifulSoup(html, "html.parser")
    p = parser_fn(soup)

    return {
        "product_name": row.product_name,
        "platform":     row.platform_name,
        "url":          row.url,
        "price":        p.get("price"),
        "title":        p.get("title"),
        "title_ok":     p.get("title_ok"),
        "images_count": p.get("images_count", 0),
        "buy_box":      p.get("buy_box", False),
        "in_stock":     p.get("in_stock"),
        "sold_by":      p.get("sold_by"),
        "sizes":              p.get("sizes", []),
        "sizes_unavailable":  p.get("sizes_unavailable", []),
        "colors":             p.get("colors", []),
        "colors_unavailable": p.get("colors_unavailable", []),
        "flags":        [],
        "status":       "GREEN",
        "error":        p.get("error"),
    }


# ──────────────────────────────────────────────
# Flag computation
# ──────────────────────────────────────────────

def compute_flags(results: list[dict]) -> list[dict]:
    """Attach flags and statuses to all platform results for one product."""
    valid   = [r for r in results if not r.get("error")]
    errored = [r for r in results if r.get("error")]

    # ── Parse / fetch errors
    for r in errored:
        r["flags"].append(f"PARSE ERROR on {r['platform']}: {r['error']}")

    for r in valid:
        # ── Out of stock / not purchasable
        if r.get("in_stock") is False:
            r["flags"].append(f"OUT OF STOCK on {r['platform']}")
        elif not r["buy_box"]:
            r["flags"].append(f"NOT PURCHASABLE on {r['platform']} (no Add to Cart / Buy Now)")

        # ── Low image count
        n_imgs = r.get("images_count", 0)
        if n_imgs < MIN_IMAGES:
            r["flags"].append(f"LOW IMAGE COUNT on {r['platform']}: only {n_imgs} image(s) (need {MIN_IMAGES}+)")

        # ── Title too short
        if r.get("title_ok") is False:
            words = len((r.get("title") or "").split())
            r["flags"].append(f"TITLE TOO SHORT on {r['platform']}: {words} word(s) (need {MIN_TITLE_WORDS}+)")

        # ── Sizes out of stock on this platform
        unavail = r.get("sizes_unavailable", [])
        if unavail:
            r["flags"].append(f"SIZES OUT OF STOCK on {r['platform']}: {', '.join(unavail)}")

    # ── Price parity (cross-platform)
    prices = {r["platform"]: r["price"] for r in valid if r["price"] is not None}
    if len(prices) >= 2:
        min_plat = min(prices, key=prices.get)
        max_plat = max(prices, key=prices.get)
        gap = prices[max_plat] - prices[min_plat]
        if gap > 50:
            ref   = [p for p, v in prices.items() if v == prices[max_plat]]
            cheap = [p for p, v in prices.items() if v == prices[min_plat]]
            flag_msg = f"PRICE GAP ₹{gap:,}: {', '.join(cheap)} cheaper than {', '.join(ref)}"
            for r in results:
                if r["platform"] in prices:
                    r["flags"].append(flag_msg)
                    break

    # ── Missing sizes across platforms
    parseable = {
        r["platform"]: set(r["sizes"])
        for r in valid
        if r["sizes"] and r["sizes"] != ["Could not parse"]
    }
    if len(parseable) >= 2:
        all_sizes = set().union(*parseable.values())
        for r in valid:
            if r["platform"] in parseable:
                missing = all_sizes - parseable[r["platform"]]
                if missing:
                    r["flags"].append(f"MISSING SIZES on {r['platform']}: {', '.join(sorted(missing))}")

    # ── Status assignment
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

        critical = ("OUT OF STOCK", "NOT PURCHASABLE", "PARSE ERROR", "FETCH ERROR")
        if any(any(c in f for c in critical) for f in r["flags"]):
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
# Full run
# ──────────────────────────────────────────────

def run_scrape(
    catalog_rows: list[CatalogRow],
    progress_callback=None,
    delay: bool = True,
) -> tuple[list[dict], dict[str, list[str]], str]:
    timestamp  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    by_product = defaultdict(list)
    for row in catalog_rows:
        by_product[row.product_name].append(row)

    all_results, flags_by_product = [], {}
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
