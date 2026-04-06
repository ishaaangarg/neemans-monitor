"""
Platform-specific HTML parsers for Neeman's Listing Health Monitor.

Each parser receives a BeautifulSoup object and returns:
{
    "price":              int or None,
    "title":              str or None,
    "title_ok":           bool,          # True if title has > 5 words
    "images_count":       int,           # number of product images found
    "buy_box":            bool,          # Add to Cart / Buy Now present & enabled
    "in_stock":           bool or None,  # None = could not determine
    "sold_by":            str or None,
    "sizes":              list[str],     # available sizes only
    "sizes_unavailable":  list[str],     # sizes present but crossed-out / disabled
    "colors":             list[str],     # available colors
    "error":              None or str,
}

HOW TO ADD A NEW PLATFORM PARSER
─────────────────────────────────
1. Define parse_<domain>(soup) returning the dict above
2. Register it in PARSER_REGISTRY at the bottom
3. Add a row to the Catalog — done
"""

import re
from bs4 import BeautifulSoup


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _clean_price(text: str) -> int | None:
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text.split(".")[0])
    return int(digits) if digits else None

def _text(tag) -> str:
    return tag.get_text(strip=True) if tag else ""

def _title_ok(title: str) -> bool:
    return len(title.split()) > 5

def _empty_result(error: str | None = None) -> dict:
    return {
        "price": None,
        "title": None,
        "title_ok": None,
        "images_count": 0,
        "buy_box": False,
        "in_stock": None,
        "sold_by": None,
        "sizes": [],
        "sizes_unavailable": [],
        "colors": [],
        "error": error,
    }


# ──────────────────────────────────────────────
# Amazon India  (amazon.in)
# ──────────────────────────────────────────────

def parse_amazon_in(soup: BeautifulSoup) -> dict:
    result = _empty_result()
    try:
        # ── Title
        title_tag = soup.select_one("#productTitle")
        title = _text(title_tag)
        result["title"] = title
        result["title_ok"] = _title_ok(title)

        # ── Images — try multiple Amazon image gallery selectors
        img_srcs = set()
        for sel in [
            "#altImages li.item img",
            "#imageBlock img[src]",
            "#imageBlockThumbs img",
            "div#imageBlock_feature_div img",
            "img.a-dynamic-image",
            "#main-image-container img",
        ]:
            for img in soup.select(sel):
                src = img.get("src", "")
                if src and "sprite" not in src and "transparent-pixel" not in src:
                    img_srcs.add(src.split("._")[0])  # normalise variant suffixes
        result["images_count"] = len(img_srcs)

        # ── Price
        price_tag = soup.select_one("span.a-price-whole")
        result["price"] = _clean_price(_text(price_tag))

        # ── Buy box
        atc = soup.find(id="add-to-cart-button")
        buy = soup.find(id="buy-now-button")
        result["buy_box"] = bool(atc or buy)

        # ── In stock
        avail_tag = soup.select_one("#availability span, #availability-string span")
        avail_text = _text(avail_tag).lower()
        if avail_text:
            result["in_stock"] = "in stock" in avail_text or "available" in avail_text
        else:
            result["in_stock"] = result["buy_box"]  # fallback: if can add to cart = in stock

        # ── Sold by
        for sel in ["#merchant-info a", "#tabular-buybox-container .tabular-buybox-text a",
                    "#sellerProfileTriggerId"]:
            tag = soup.select_one(sel)
            if tag:
                result["sold_by"] = _text(tag)
                break

        # ── Sizes — split available vs unavailable
        sizes, sizes_unavailable = [], []
        # Amazon renders sizes as li elements or as a select dropdown
        for li in soup.select(
            "#variation_size_name ul li, "
            "#native_dropdown_selected_size_name option, "
            "div[id*='size'] ul li, "
            "ul.a-nostyle li[data-value]"
        ):
            val = li.get("data-value") or _text(li)
            if not val or val.strip().lower() in ("", "select", "-1"):
                continue
            val = val.strip()
            classes = " ".join(li.get("class") or [])
            # Unavailable = a-disabled class, or contains a crossed-out icon
            is_unavail = (
                "a-disabled" in classes
                or bool(li.find(class_=re.compile(r"a-disabled|cross-icon|unavailable", re.I)))
            )
            (sizes_unavailable if is_unavail else sizes).append(val)
        result["sizes"] = sizes
        result["sizes_unavailable"] = sizes_unavailable

        # ── Colors — available only
        colors = []
        for li in soup.select("#variation_color_name ul li"):
            title_attr = li.get("title", "")
            val = re.sub(r"^Click to select\s*", "", title_attr, flags=re.I).strip()
            classes = " ".join(li.get("class") or [])
            if val and "a-disabled" not in classes:
                colors.append(val)
        result["colors"] = colors

        result["error"] = None
    except Exception as exc:
        result["error"] = f"amazon parser error: {exc}"
    return result


# ──────────────────────────────────────────────
# Flipkart  (flipkart.com)
# ──────────────────────────────────────────────

def _find_buy_button(soup):
    """Find any active buy/add-to-cart button regardless of class names."""
    patterns = re.compile(r"add to (cart|bag)|buy now|buy at|place order", re.I)
    for btn in soup.find_all("button"):
        if patterns.search(_text(btn)) and not btn.get("disabled"):
            return btn
    return None


def _find_images(soup, extra_selectors=""):
    """
    Count unique product images. Checks both src and data-src (lazy-load).
    Returns count of unique image URLs.
    """
    srcs = set()
    base_selectors = (extra_selectors + ", img[src], img[data-src]").lstrip(", ")
    for img in soup.select(base_selectors):
        for attr in ("src", "data-src", "data-lazy-src", "data-original"):
            s = img.get(attr, "")
            if s and s.startswith("http") and "sprite" not in s and "logo" not in s.lower():
                srcs.add(s.split("?")[0].split("._")[0])
    return len(srcs)


def parse_flipkart_com(soup: BeautifulSoup) -> dict:
    result = _empty_result()
    try:
        # ── Title: h1 first, then page <title> (class names change — never rely on them)
        h1 = soup.find("h1")
        title = _text(h1) if h1 else ""
        if not title or len(title) < 5:
            pt = soup.find("title")
            if pt:
                title = _text(pt).split("|")[0].strip()
        result["title"]    = title
        result["title_ok"] = _title_ok(title)

        # ── Images: filter by Flipkart/Flixcart CDN domain — class-agnostic
        srcs = set()
        for img in soup.find_all("img"):
            for attr in ("src", "data-src", "data-lazy-src", "data-original"):
                s = img.get(attr, "")
                if s and ("rukminim" in s or "flixcart" in s) and "sprite" not in s:
                    srcs.add(s.split("?")[0].split("._")[0])
        # Fallback: any product-looking HTTP image if CDN filtering found too few
        if len(srcs) < 3:
            srcs.update(
                s.split("?")[0].split("._")[0]
                for img in soup.find_all("img")
                for attr in ("src", "data-src")
                if (s := img.get(attr, ""))
                and s.startswith("http")
                and "sprite" not in s
                and "logo" not in s.lower()
                and "icon" not in s.lower()
            )
        result["images_count"] = len(srcs)

        # ── Price: ₹ regex scan — immune to class-name changes
        price = None
        for m in re.finditer(r"₹\s*([\d,]+)", soup.get_text()):
            p = _clean_price(m.group(1))
            if p and p > 100:
                price = p
                break
        result["price"] = price

        # ── Buy box: text-based, uses shared helper
        buy_btn = _find_buy_button(soup)
        # Also accept div/span acting as button
        if not buy_btn:
            for el in soup.find_all(["div", "span", "a"]):
                if el.get("role") == "button" or el.get("tabindex") == "0":
                    txt = _text(el).lower()
                    if re.search(r"add to (cart|bag)|buy now|place order", txt):
                        buy_btn = el
                        break
        result["buy_box"] = buy_btn is not None

        # ── In stock: exact-text match on small elements (avoids review false positives)
        oos_found = False
        for el in soup.find_all(["div", "span", "p", "h2", "h3"]):
            if el.find(["div", "span", "p"]):  # skip containers
                continue
            txt = _text(el).strip().lower()
            if txt in ("out of stock", "currently unavailable", "sold out"):
                oos_found = True
                break
        result["in_stock"] = not oos_found and result["buy_box"]

        # ── Sold by: scan for "Sold by" / "Fulfilled by" text nodes
        for node in soup.find_all(string=re.compile(r"(Sold|Fulfilled)\s+by", re.I)):
            parent = node.find_parent()
            a_tag  = parent.find("a") if parent else None
            if a_tag:
                result["sold_by"] = _text(a_tag).strip()
                break
            elif parent:
                val = re.sub(r"(Sold|Fulfilled)\s+by\s*:?\s*", "", _text(parent), flags=re.I).strip()
                if val:
                    result["sold_by"] = val
                    break

        # ── Sizes: walk DOM from "Select Size" text upward to find the size list
        sizes, sizes_unavailable = [], []
        size_container = None
        for node in soup.find_all(string=re.compile(r"select\s+size", re.I)):
            parent = node.find_parent()
            for _ in range(10):
                if not parent:
                    break
                short_lis = [li for li in parent.find_all("li")
                             if 1 <= len(_text(li).strip()) <= 6]
                if len(short_lis) >= 2:
                    size_container = parent
                    break
                parent = parent.find_parent()
            if size_container:
                break

        if size_container:
            for li in size_container.find_all("li"):
                val = _text(li).split("\n")[0].strip()
                if not val or len(val) > 6:
                    continue
                classes = " ".join(li.get("class") or [])
                # Flipkart marks OOS sizes with _9E25nV or aria-disabled
                is_unavail = (
                    "_9E25nV" in classes
                    or "disabled" in classes.lower()
                    or "unavailable" in classes.lower()
                    or li.get("aria-disabled") == "true"
                    or bool(li.find("button", attrs={"disabled": True}))
                )
                (sizes_unavailable if is_unavail else sizes).append(val)

        result["sizes"]             = list(dict.fromkeys(sizes))
        result["sizes_unavailable"] = list(dict.fromkeys(sizes_unavailable))

        # ── Colors: walk DOM from "Colour" / "Color" text
        colors = []
        for node in soup.find_all(string=re.compile(r"^colou?r$", re.I)):
            parent = node.find_parent()
            for _ in range(6):
                if not parent:
                    break
                lis = parent.find_all("li")
                if len(lis) >= 1:
                    break
                parent = parent.find_parent()
            if parent:
                for li in parent.find_all("li"):
                    val = li.get("title") or li.get("aria-label") or _text(li)
                    if val and len(val.strip()) < 30:
                        colors.append(val.strip())
                break
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
        # ── Title: Myntra has Brand in h1, product name in the next element
        h1_tags = soup.find_all("h1")
        parts = [_text(h) for h in h1_tags if _text(h)]
        if not parts:
            # Try h2 as fallback
            parts = [_text(h) for h in soup.find_all("h2") if _text(h)][:2]
        if not parts:
            pt = soup.find("title")
            if pt:
                parts = [_text(pt).split("|")[0].strip()]
        title = " ".join(parts[:2]).strip()
        result["title"]    = title
        result["title_ok"] = _title_ok(title)

        # ── Images: filter by Myntra's CDN domain — class-agnostic
        srcs = set()
        for img in soup.find_all("img"):
            for attr in ("src", "data-src", "data-lazy-src", "data-original"):
                s = img.get(attr, "")
                if s and "myntassets" in s and "logo" not in s.lower():
                    srcs.add(s.split("?")[0])
        # Fallback: any sizable HTTP image
        if len(srcs) < 3:
            srcs.update(
                s.split("?")[0]
                for img in soup.find_all("img")
                for attr in ("src", "data-src")
                if (s := img.get(attr, ""))
                and s.startswith("http")
                and "sprite" not in s
                and "logo" not in s.lower()
                and "icon" not in s.lower()
            )
        result["images_count"] = len(srcs)

        # ── Price: ₹ regex scan — immune to class-name changes
        price = None
        for m in re.finditer(r"₹\s*([\d,]+)", soup.get_text()):
            p = _clean_price(m.group(1))
            if p and p > 100:
                price = p
                break
        result["price"] = price

        # ── Buy box: text-based helpers; Myntra uses "Add to Bag"
        buy_btn = _find_buy_button(soup)   # catches "add to bag" via regex
        # Also try div/span with role=button
        if not buy_btn:
            for el in soup.find_all(["div", "span", "a"]):
                if el.get("role") == "button":
                    txt = _text(el).lower()
                    if re.search(r"add to (cart|bag)|buy now", txt):
                        buy_btn = el
                        break
        result["buy_box"] = buy_btn is not None

        # ── In stock: exact-text match on leaf elements only
        oos_found = False
        for el in soup.find_all(["div", "span", "p", "h4", "button"]):
            if el.find(["div", "span", "p"]):
                continue  # skip containers
            txt = _text(el).strip().lower()
            if txt in ("out of stock", "sold out", "notify me", "currently unavailable"):
                oos_found = True
                break
        result["in_stock"] = not oos_found and result["buy_box"]

        # ── Sizes: walk DOM from "Select Size" or "Size" heading
        sizes, sizes_unavailable = [], []
        size_container = None
        for node in soup.find_all(string=re.compile(r"select\s+size|size\s*:", re.I)):
            parent = node.find_parent()
            for _ in range(10):
                if not parent:
                    break
                candidates = [
                    el for el in parent.find_all(["li", "button"])
                    if 1 <= len(_text(el).strip()) <= 6
                ]
                if len(candidates) >= 2:
                    size_container = parent
                    break
                parent = parent.find_parent()
            if size_container:
                break

        if size_container:
            seen_vals = set()
            for item in size_container.find_all(["li", "button"]):
                # Prefer innermost text (button inside li)
                val = _text(item).split("\n")[0].strip()
                if not val or len(val) > 6 or val in seen_vals:
                    continue
                seen_vals.add(val)
                classes     = " ".join(item.get("class") or [])
                parent_li   = item.find_parent("li")
                li_classes  = " ".join(parent_li.get("class") or []) if parent_li else ""
                is_unavail  = (
                    "size-buttons-size-out" in li_classes
                    or "size-buttons-size-out" in classes
                    or "unavailable" in classes.lower()
                    or "unavailable" in li_classes.lower()
                    or "disabled" in classes.lower()
                    or item.get("disabled") is not None
                    or item.get("aria-disabled") == "true"
                )
                (sizes_unavailable if is_unavail else sizes).append(val)

        result["sizes"]             = list(dict.fromkeys(sizes))
        result["sizes_unavailable"] = list(dict.fromkeys(sizes_unavailable))

        # ── Colors: walk DOM from "Colour" / "Color" label
        colors = []
        for node in soup.find_all(string=re.compile(r"^colou?r$", re.I)):
            parent = node.find_parent()
            for _ in range(6):
                if not parent:
                    break
                lis = parent.find_all("li")
                if len(lis) >= 1:
                    break
                parent = parent.find_parent()
            if parent:
                for li in parent.find_all("li"):
                    val = li.get("title") or li.get("aria-label") or _text(li)
                    if val and len(val.strip()) < 30:
                        colors.append(val.strip())
                break
        result["colors"] = colors

        result["error"] = None
    except Exception as exc:
        result["error"] = f"myntra parser error: {exc}"
    return result


# ──────────────────────────────────────────────
# Nykaa  (nykaa.com)
# ──────────────────────────────────────────────

def parse_nykaa_com(soup: BeautifulSoup) -> dict:
    result = _empty_result()
    try:
        title_tag = soup.select_one("h1[class*='product'], h1[class*='title']")
        title = _text(title_tag)
        result["title"] = title
        result["title_ok"] = _title_ok(title)

        imgs = soup.select("div[class*='image'] img, ul[class*='image'] img")
        result["images_count"] = len({i.get("src","") for i in imgs if i.get("src")})

        price_tag = soup.select_one("span[class*='price'], span[class*='Price']")
        result["price"] = _clean_price(_text(price_tag))

        result["buy_box"] = any(
            "add to bag" in _text(b).lower() or "add to cart" in _text(b).lower()
            for b in soup.find_all("button")
        )
        oos = soup.find(string=re.compile(r"out of stock|sold out", re.I))
        result["in_stock"] = oos is None and result["buy_box"]

        sizes, sizes_unavailable = [], []
        for el in soup.select("div[class*='size'] button, ul[class*='size'] li"):
            val = _text(el)
            if not val or val.lower() == "size":
                continue
            if el.get("disabled") or "disabled" in " ".join(el.get("class") or []).lower():
                sizes_unavailable.append(val)
            else:
                sizes.append(val)
        result["sizes"] = list(dict.fromkeys(sizes))
        result["sizes_unavailable"] = list(dict.fromkeys(sizes_unavailable))

        colors = []
        for el in soup.select("div[class*='color'] button, ul[class*='color'] li"):
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
        title_tag = soup.select_one("h1[class*='ProductDetailsMainCard'], h1[class*='product']")
        title = _text(title_tag)
        result["title"] = title
        result["title_ok"] = _title_ok(title)

        imgs = soup.select("div[class*='ProductImage'] img, ul[class*='ImageCarousel'] img")
        result["images_count"] = len({i.get("src","") for i in imgs if i.get("src")})

        price_tag = soup.select_one("div[class*='ProductDetailsMainCard__price'], span[class*='ProductDetailsMainCard__price']")
        result["price"] = _clean_price(_text(price_tag))

        result["buy_box"] = any(
            "add to bag" in _text(b).lower() or "buy now" in _text(b).lower()
            for b in soup.find_all("button")
        )
        oos = soup.find(string=re.compile(r"out of stock|sold out", re.I))
        result["in_stock"] = oos is None and result["buy_box"]

        sizes, sizes_unavailable = [], []
        for el in soup.select("ul[class*='SizeSelector'] li, div[class*='SizeSelector'] button"):
            val = _text(el)
            if not val:
                continue
            if el.get("disabled") or "disabled" in " ".join(el.get("class") or []).lower():
                sizes_unavailable.append(val)
            else:
                sizes.append(val)
        result["sizes"] = sizes
        result["sizes_unavailable"] = sizes_unavailable

        colors = []
        for el in soup.select("ul[class*='ColorSelector'] li"):
            val = el.get("title") or el.get("aria-label") or _text(el)
            if val:
                colors.append(val.strip())
        result["colors"] = colors

        result["error"] = None
    except Exception as exc:
        result["error"] = f"tatacliq parser error: {exc}"
    return result


# ──────────────────────────────────────────────
# Shopify — covers neemans.com + any *.myshopify.com
# ──────────────────────────────────────────────

def parse_shopify(soup: BeautifulSoup) -> dict:
    result = _empty_result()
    try:
        # Title
        title_tag = soup.select_one("h1.product__title, h1.product-title, h1[class*='product']")
        title = _text(title_tag)
        result["title"] = title
        result["title_ok"] = _title_ok(title)

        # Images — Shopify product gallery
        imgs = soup.select(
            "div.product__media img, div.product-single__photo img, "
            "ul.product__media-list img, div[class*='product-gallery'] img"
        )
        result["images_count"] = len({i.get("src","").split("?")[0] for i in imgs if i.get("src")})

        # Price
        for sel in ["span.price__current", "span.price", "span[class*='price']",
                    "div[class*='price'] span", "p.price"]:
            tag = soup.select_one(sel)
            if tag:
                p = _clean_price(_text(tag))
                if p:
                    result["price"] = p
                    break

        # Buy box — not disabled
        result["buy_box"] = False
        for btn in soup.find_all("button"):
            txt = _text(btn).lower()
            if "add to cart" in txt or "add to bag" in txt:
                disabled = btn.get("disabled") is not None or btn.get("aria-disabled") == "true"
                name = btn.get("name", "")
                if not disabled and name != "add":
                    result["buy_box"] = True
                    break
                elif not disabled:
                    result["buy_box"] = True
                    break

        # In stock
        oos = soup.find(string=re.compile(r"out of stock|sold out|unavailable", re.I))
        result["in_stock"] = oos is None

        # Sizes
        sizes, sizes_unavailable = [], []
        size_selectors = [
            "fieldset[data-option-name*='Size'] label",
            "fieldset[data-option-name*='size'] label",
            "div[class*='size'] input + label",
            "div[class*='Size'] button",
            "ul[class*='size'] li",
            "select[id*='size'] option",
            "select[id*='Size'] option",
        ]
        for sel in size_selectors:
            for el in soup.select(sel):
                val = _text(el)
                if not val or val.lower() in ("size", "select size", ""):
                    continue
                classes = " ".join(el.get("class") or [])
                # Shopify marks unavailable with crossed-out or disabled style
                is_unavailable = (
                    el.get("disabled") is not None
                    or "disabled" in classes.lower()
                    or "unavailable" in classes.lower()
                    or "sold-out" in classes.lower()
                    or el.find(class_=re.compile(r"cross|strike|soldout|unavailable", re.I))
                )
                if is_unavailable:
                    sizes_unavailable.append(val)
                else:
                    sizes.append(val)
        result["sizes"] = list(dict.fromkeys(sizes))
        result["sizes_unavailable"] = list(dict.fromkeys(sizes_unavailable))

        # Colors
        colors = []
        for sel in [
            "fieldset[data-option-name*='Color'] label",
            "fieldset[data-option-name*='color'] label",
            "fieldset[data-option-name*='Colour'] label",
        ]:
            for el in soup.select(sel):
                val = el.get("title") or el.get("aria-label") or _text(el)
                if val and val.lower() not in ("color", "colour", ""):
                    colors.append(val.strip())
        result["colors"] = list(dict.fromkeys(colors))

        result["error"] = None
    except Exception as exc:
        result["error"] = f"shopify parser error: {exc}"
    return result


# ──────────────────────────────────────────────
# Generic fallback
# ──────────────────────────────────────────────

def parse_generic(soup: BeautifulSoup) -> dict:
    result = _empty_result()
    try:
        title_tag = soup.find("h1")
        title = _text(title_tag)
        result["title"] = title
        result["title_ok"] = _title_ok(title)

        imgs = soup.find_all("img")
        result["images_count"] = len(imgs)

        price_match = re.search(r"₹\s*([\d,]+)", soup.get_text())
        if price_match:
            result["price"] = _clean_price(price_match.group(1))

        result["buy_box"] = any(
            re.search(r"add to (cart|bag)|buy now", _text(b), re.I)
            for b in soup.find_all("button")
        )
        oos = soup.find(string=re.compile(r"out of stock|sold out", re.I))
        result["in_stock"] = oos is None and result["buy_box"]

        result["sizes"] = ["Could not parse"]
        result["error"] = None
    except Exception as exc:
        result["error"] = f"generic parser error: {exc}"
    return result


# ──────────────────────────────────────────────
# Parser registry
# ──────────────────────────────────────────────

PARSER_REGISTRY: dict[str, callable] = {
    "amazon.in":            parse_amazon_in,
    "www.amazon.in":        parse_amazon_in,
    "flipkart.com":         parse_flipkart_com,
    "www.flipkart.com":     parse_flipkart_com,
    "myntra.com":           parse_myntra_com,
    "www.myntra.com":       parse_myntra_com,
    "nykaa.com":            parse_nykaa_com,
    "www.nykaa.com":        parse_nykaa_com,
    "nykaafashion.com":     parse_nykaa_com,
    "www.nykaafashion.com": parse_nykaa_com,
    "tatacliq.com":         parse_tatacliq_com,
    "www.tatacliq.com":     parse_tatacliq_com,
    "neemans.com":          parse_shopify,
    "www.neemans.com":      parse_shopify,
    "neemans.myshopify.com": parse_shopify,
}


def get_parser(domain: str):
    return PARSER_REGISTRY.get(domain.lower(), parse_generic)
