"""
Platform-specific HTML parsers for Neeman's Listing Health Monitor.

Each parser receives a BeautifulSoup object (parsed from fully rendered HTML)
and returns a dict:
    {
        "price":   int or None,
        "buy_box": bool,
        "sizes":   list[str],
        "colors":  list[str],
        "error":   None or str,
    }

HOW TO ADD A NEW PLATFORM PARSER
─────────────────────────────────
1. Define a function named  parse_<sanitised_domain>(soup)
   e.g. for "mynewsite.com"  →  parse_mynewsite_com(soup)
2. Fill in the price / buy_box / sizes / colors extraction logic.
3. Register it in PARSER_REGISTRY at the bottom of this file:
       "mynewsite.com": parse_mynewsite_com,
4. Add a row to the "Catalog" Google Sheet — no other code changes needed.
"""

import re
from bs4 import BeautifulSoup


# ──────────────────────────────────────────────
# Helper utilities
# ──────────────────────────────────────────────

def _clean_price(text: str) -> int | None:
    """Extract the first run of digits (with optional commas) from a string."""
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text.split(".")[0])
    return int(digits) if digits else None


def _text(tag) -> str:
    return tag.get_text(strip=True) if tag else ""


def _empty_result(error: str | None = None) -> dict:
    return {"price": None, "buy_box": False, "sizes": [], "colors": [], "error": error}


# ──────────────────────────────────────────────
# Amazon India  (amazon.in)
# ──────────────────────────────────────────────

def parse_amazon_in(soup: BeautifulSoup) -> dict:
    result = _empty_result()
    try:
        price_tag = soup.select_one("span.a-price-whole")
        result["price"] = _clean_price(_text(price_tag))

        result["buy_box"] = bool(
            soup.find(id="add-to-cart-button") or soup.find(id="buy-now-button")
        )

        sizes = []
        for li in soup.select("#variation_size_name ul li, #native_dropdown_selected_size_name option"):
            val = li.get("data-value") or _text(li)
            if val and val.strip().lower() not in ("", "select", "-1"):
                sizes.append(val.strip())
        result["sizes"] = sizes

        colors = []
        for li in soup.select("#variation_color_name ul li"):
            title = li.get("title", "")
            val = re.sub(r"^Click to select\s*", "", title, flags=re.I).strip()
            if val:
                colors.append(val)
        result["colors"] = colors

        result["error"] = None
    except Exception as exc:
        result["error"] = f"amazon parser error: {exc}"
    return result


# ──────────────────────────────────────────────
# Flipkart  (flipkart.com)
# ──────────────────────────────────────────────

def parse_flipkart_com(soup: BeautifulSoup) -> dict:
    result = _empty_result()
    try:
        price_tag = soup.select_one("div._30jeq3, div.Nx9bqj")
        result["price"] = _clean_price(_text(price_tag))

        def _has_cta(tag):
            txt = _text(tag).lower()
            return "add to cart" in txt or "buy now" in txt

        result["buy_box"] = any(_has_cta(b) for b in soup.find_all("button"))

        sizes = []
        for li in soup.select("div._3mkSCk li, ul._7eSDEz li"):
            val = _text(li)
            if val:
                sizes.append(val)
        result["sizes"] = sizes

        colors = []
        for li in soup.select("div._2KpZ6l li, ul.t-rspns li"):
            val = li.get("title") or _text(li)
            if val:
                colors.append(val.strip())
        result["colors"] = colors

        result["error"] = None
    except Exception as exc:
        result["error"] = f"flipkart parser error: {exc}"
    return result


# ──────────────────────────────────────────────
# Myntra  (myntra.com)
# ──────────────────────────────────────────────

def parse_myntra_com(soup: BeautifulSoup) -> dict:
    result = _empty_result()
    try:
        price_tag = soup.select_one("span.pdp-price strong, span.pdp-discount-container span.pdp-price")
        if not price_tag:
            price_tag = soup.select_one("span.pdp-price")
        result["price"] = _clean_price(_text(price_tag))

        result["buy_box"] = bool(soup.select_one("div.pdp-add-to-bag button, button.pdp-add-to-bag"))

        sizes = []
        for btn in soup.select("ul.size-buttons-list-container li button, div.size-buttons-unified-size"):
            val = _text(btn)
            if val:
                sizes.append(val)
        result["sizes"] = sizes

        colors = []
        for swatch in soup.select("ul.color-swatches-main li"):
            val = swatch.get("title") or swatch.get("aria-label") or _text(swatch)
            if val:
                colors.append(val.strip())
        result["colors"] = colors

        result["error"] = None
    except Exception as exc:
        result["error"] = f"myntra parser error: {exc}"
    return result


# ──────────────────────────────────────────────
# Nykaa  (nykaa.com / nykaa fashion)
# ──────────────────────────────────────────────

def parse_nykaa_com(soup: BeautifulSoup) -> dict:
    result = _empty_result()
    try:
        # Multiple possible price selectors across Nykaa properties
        price_tag = soup.select_one(
            "span[class*='price'], span[class*='Price'], div[class*='price']"
        )
        result["price"] = _clean_price(_text(price_tag))

        result["buy_box"] = any(
            "add to bag" in _text(b).lower() or "add to cart" in _text(b).lower()
            for b in soup.find_all("button")
        )

        sizes = []
        for el in soup.select("div[class*='size'] button, ul[class*='size'] li, div[class*='Size'] button"):
            val = _text(el)
            if val and val.lower() not in ("size", ""):
                sizes.append(val)
        result["sizes"] = list(dict.fromkeys(sizes))  # dedupe preserving order

        colors = []
        for el in soup.select("div[class*='color'] button, ul[class*='color'] li, div[class*='Color'] button"):
            val = el.get("title") or el.get("aria-label") or _text(el)
            if val and val.lower() not in ("color", ""):
                colors.append(val.strip())
        result["colors"] = list(dict.fromkeys(colors))

        result["error"] = None
    except Exception as exc:
        result["error"] = f"nykaa parser error: {exc}"
    return result


# ──────────────────────────────────────────────
# Tata CLiQ  (tatacliq.com)
# ──────────────────────────────────────────────

def parse_tatacliq_com(soup: BeautifulSoup) -> dict:
    result = _empty_result()
    try:
        price_tag = soup.select_one(
            "div[class*='ProductDetailsMainCard__price'], span[class*='ProductDetailsMainCard__price']"
        )
        result["price"] = _clean_price(_text(price_tag))

        result["buy_box"] = any(
            "add to bag" in _text(b).lower() or "buy now" in _text(b).lower()
            for b in soup.find_all("button")
        )

        sizes = []
        for el in soup.select("ul[class*='SizeSelector'] li, div[class*='SizeSelector'] button"):
            val = _text(el)
            if val:
                sizes.append(val)
        result["sizes"] = sizes

        colors = []
        for el in soup.select("ul[class*='ColorSelector'] li, div[class*='ColorSelector'] button"):
            val = el.get("title") or el.get("aria-label") or _text(el)
            if val:
                colors.append(val.strip())
        result["colors"] = colors

        result["error"] = None
    except Exception as exc:
        result["error"] = f"tatacliq parser error: {exc}"
    return result


# ──────────────────────────────────────────────
# Neemans.com  (neemans.com)
# ──────────────────────────────────────────────

def parse_neemans_com(soup: BeautifulSoup) -> dict:
    result = _empty_result()
    try:
        price_tag = soup.select_one("span.price, div.price span")
        result["price"] = _clean_price(_text(price_tag))

        result["buy_box"] = any(
            "add to cart" in _text(b).lower()
            for b in soup.find_all("button")
        )

        sizes = []
        for el in soup.select(
            "div.swatch-size button, fieldset[data-option-name*='Size'] label, "
            "div[class*='size'] input + label"
        ):
            val = _text(el)
            if val:
                sizes.append(val)
        result["sizes"] = sizes

        colors = []
        for el in soup.select(
            "div.swatch-color button, fieldset[data-option-name*='Color'] label, "
            "div[class*='color'] input + label"
        ):
            val = el.get("title") or el.get("aria-label") or _text(el)
            if val:
                colors.append(val.strip())
        result["colors"] = colors

        result["error"] = None
    except Exception as exc:
        result["error"] = f"neemans parser error: {exc}"
    return result


# ──────────────────────────────────────────────
# Generic fallback — any unknown domain
# ──────────────────────────────────────────────

def parse_generic(soup: BeautifulSoup) -> dict:
    result = _empty_result()
    try:
        # Price: find first occurrence of ₹ followed by digits
        price_match = re.search(r"₹\s*([\d,]+)", soup.get_text())
        if price_match:
            result["price"] = _clean_price(price_match.group(1))

        result["buy_box"] = any(
            re.search(r"add to (cart|bag)|buy now", _text(b), re.I)
            for b in soup.find_all("button")
        )

        result["sizes"] = ["Could not parse"]
        result["colors"] = ["Could not parse"]
        result["error"] = None
    except Exception as exc:
        result["error"] = f"generic parser error: {exc}"
    return result


# ──────────────────────────────────────────────
# Parser registry  —  domain → function
# ──────────────────────────────────────────────

PARSER_REGISTRY: dict[str, callable] = {
    "amazon.in": parse_amazon_in,
    "www.amazon.in": parse_amazon_in,
    "flipkart.com": parse_flipkart_com,
    "www.flipkart.com": parse_flipkart_com,
    "myntra.com": parse_myntra_com,
    "www.myntra.com": parse_myntra_com,
    "nykaa.com": parse_nykaa_com,
    "www.nykaa.com": parse_nykaa_com,
    "nykaafashion.com": parse_nykaa_com,
    "www.nykaafashion.com": parse_nykaa_com,
    "tatacliq.com": parse_tatacliq_com,
    "www.tatacliq.com": parse_tatacliq_com,
    "neemans.com": parse_neemans_com,
    "www.neemans.com": parse_neemans_com,
}


def get_parser(domain: str):
    """Return the appropriate parser function for a given domain."""
    return PARSER_REGISTRY.get(domain.lower(), parse_generic)
