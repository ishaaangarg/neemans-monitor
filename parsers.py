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

import json
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

# Valid size pattern: numeric (6, 6.5, 10), numeric+suffix (6 UK, 10 US, 42 EU),
# clothing codes (XS S M L XL XXL 2XL 3XL 4XL), or short alpha codes (ONE SIZE)
_SIZE_RE = re.compile(
    r"^(\d{1,3}(\.\d)?\s*(UK|US|EU|IN|CM)?|XS|S|M|L|XL|XXL|XXXL|[2-4]XL|ONE\s*SIZE|FREE\s*SIZE)$",
    re.I,
)

def _is_valid_size(val: str) -> bool:
    """Return True only if val looks like an actual size (not a category/brand name)."""
    # Also normalise common Amazon data-value formats like "10_UK" → "10 UK"
    v = re.sub(r"[_\-]", " ", val.strip())
    return bool(_SIZE_RE.match(v))

_MAX_PRICE = 50_000   # sanity cap — no shoe costs more than ₹50k

def _selling_price(text: str) -> int | None:
    """
    Extract the selling (discounted) price from page text.
    Strategy 1: '₹PRICE MRP'  (Myntra style)
    Strategy 2: price that appears just before '% OFF'
    Strategy 3: skip first ₹ occurrence (often an ad), return next in range
    """
    def _valid(p):
        return p is not None and 100 < p < _MAX_PRICE

    # Strategy 1 — Myntra "₹1499 MRP ₹3499"
    m = re.search(r"₹\s*([\d,]+)\s*MRP", text, re.I)
    if m:
        p = _clean_price(m.group(1))
        if _valid(p):
            return p
    # Strategy 2 — price CLOSEST to "% off" (= selling price; MRP appears further left)
    # Flipkart layout: "₹2,999  ₹1,499  50% off" → take the LAST price before % off
    for m in re.finditer(r"\d+\s*%\s*(?:off|OFF|Off)", text):
        lookback = text[max(0, m.start() - 400): m.start()]
        candidates = [_clean_price(pm.group(1))
                      for pm in re.finditer(r"₹\s*([\d,]+)", lookback)]
        candidates = [p for p in candidates if _valid(p)]
        if candidates:
            return candidates[-1]   # last = closest to "% off" = selling price
    # Strategy 3 — skip first hit (often an ad), take next sensible price
    hits = [(m.start(), _clean_price(m.group(1)))
            for m in re.finditer(r"₹\s*([\d,]+)", text)]
    hits = [(pos, p) for pos, p in hits if _valid(p)]
    if len(hits) >= 2:
        return hits[1][1]
    elif hits:
        return hits[0][1]
    return None

# Words that should NOT appear in a valid colour name
_INVALID_COLOR_WORDS = re.compile(
    r"\b(off|selected|description|caption|chapters?|play|pause|muted|volume|menu|"
    r"button|click|image|video|audio|tracks?|subtitles?|fullscreen|settings|"
    r"captions?|thumbnails?|seekbar|buffered|autoplay|controls?|loop|preload)\b",
    re.I,
)

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
        "colors_unavailable": [],
        "error": error,
    }


# ──────────────────────────────────────────────
# JSON extraction helpers
# ──────────────────────────────────────────────

def _extract_jsonld(soup) -> list[dict]:
    """Return all JSON-LD <script> blocks parsed as dicts (flattened list)."""
    out = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = (script.string or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                out.extend(data)
            elif isinstance(data, dict):
                out.append(data)
        except Exception:
            pass
    return out


def _extract_window_var(soup, var_name: str) -> dict:
    """
    Extract window.VAR_NAME = {...} JSON from inline <script> tags.
    Uses JSONDecoder.raw_decode so trailing JS after the object is ignored.
    """
    pattern = re.compile(
        r"(?:window\.)?" + re.escape(var_name) + r"\s*=\s*", re.DOTALL
    )
    for script in soup.find_all("script"):
        text = script.string or ""
        m = pattern.search(text)
        if not m:
            continue
        rest = text[m.end():].lstrip()
        if not rest.startswith("{"):
            continue
        try:
            data, _ = json.JSONDecoder().raw_decode(rest)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def _extract_variationvalues(soup) -> dict:
    """
    Extract Amazon's variationValues object from inline scripts.
    Returns {"size_name": [...], "color_name": [...]} or {}.
    """
    # The object is a flat dict with array values — no nested braces, safe regex
    pattern = re.compile(r'"variationValues"\s*:\s*(\{[^}]+\})')
    for script in soup.find_all("script"):
        text = script.string or ""
        m = pattern.search(text)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
    return {}


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

        # ── Sizes + Colors — primary source: variationValues JSON in inline script
        # Amazon embeds {"size_name":["6 UK","7 UK",...], "color_name":[...]} in the page JS.
        # This is more reliable than HTML element parsing for variation widgets.
        vv = _extract_variationvalues(soup)
        sizes, sizes_unavailable = [], []
        colors_avail, colors_unavail = [], []

        if vv.get("size_name"):
            for raw in vv["size_name"]:
                val = re.sub(r"[_\-]", " ", str(raw)).strip()
                if _is_valid_size(val):
                    sizes.append(val)   # variationValues lists all selectable sizes (available)

        if vv.get("color_name"):
            colors_avail = [str(c).strip() for c in vv["color_name"] if str(c).strip()]

        # HTML fallback for sizes: variation div (twister-style)
        if not sizes:
            _SKIP_SIZE_VALS = {"", "select", "-1", "size", "please select", "select size"}
            variation_div = soup.find(id=re.compile(r"variation_size|variation_shoe_size", re.I))
            if variation_div:
                for li in variation_div.find_all("li"):
                    raw = li.get("data-value") or ""
                    val = re.sub(r"[_\-]", " ", raw).strip()
                    if not val:
                        span = li.find("span", class_=re.compile(r"a-button-text|a-size", re.I))
                        val = _text(span or li).split("\n")[0].strip()
                    val = re.sub(r"\s+", " ", val).strip()
                    if not val or val.lower() in _SKIP_SIZE_VALS or not _is_valid_size(val):
                        continue
                    classes = " ".join(li.get("class") or [])
                    is_unavail = (
                        "a-disabled" in classes
                        or li.get("aria-disabled") == "true"
                        or li.get("disabled") is not None
                        or bool(li.find(class_=re.compile(r"a-disabled|cross-icon", re.I)))
                        or "currently unavailable" in _text(li).lower()
                    )
                    (sizes_unavailable if is_unavail else sizes).append(val)

        # HTML fallback for colors: image-swatch list
        if not colors_avail:
            for li in soup.select("#variation_color_name ul li"):
                title_attr = li.get("title", "")
                val = re.sub(r"^Click to select\s*", "", title_attr, flags=re.I).strip()
                if not val:
                    img = li.find("img")
                    val = (img.get("alt", "") if img else "").strip()
                if not val:
                    continue
                classes = " ".join(li.get("class") or [])
                li_text = _text(li).lower()
                is_unavail = (
                    "a-disabled" in classes
                    or li.get("aria-disabled") == "true"
                    or "currently unavailable" in li_text
                )
                (colors_unavail if is_unavail else colors_avail).append(val)

        result["sizes"] = list(dict.fromkeys(sizes))
        result["sizes_unavailable"] = list(dict.fromkeys(sizes_unavailable))
        result["colors"] = colors_avail
        result["colors_unavailable"] = colors_unavail

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
        # ── Title: h1 first, then page <title>
        h1 = soup.find("h1")
        title = _text(h1) if h1 else ""
        if not title or len(title) < 5:
            pt = soup.find("title")
            if pt:
                title = _text(pt).split("|")[0].strip()
        result["title"]    = title
        result["title_ok"] = _title_ok(title)

        # ── Price + Availability + Images: use Schema.org JSON-LD (most reliable)
        # Flipkart embeds structured data: {"@type":"Product","offers":{"price":1499,...}}
        jsonld_price = None
        jsonld_instock = None
        jsonld_images = []
        for item in _extract_jsonld(soup):
            if item.get("@type") == "Product":
                offers = item.get("offers", {})
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                p = offers.get("price")
                try:
                    p = int(float(p))
                except (TypeError, ValueError):
                    p = None
                if p and 100 < p < _MAX_PRICE:
                    jsonld_price = p
                avail = str(offers.get("availability", ""))
                if avail:
                    jsonld_instock = "InStock" in avail
                imgs = item.get("image", [])
                if isinstance(imgs, str):
                    imgs = [imgs]
                jsonld_images = [s for s in imgs if isinstance(s, str) and "rukminim" in s]
                break  # only need first Product schema

        result["price"] = jsonld_price or _selling_price(soup.get_text())

        # ── Images: prefer JSON-LD list (guaranteed product images), fallback HTML CDN scan
        if jsonld_images:
            result["images_count"] = len(jsonld_images)
        else:
            srcs = set()
            for img in soup.find_all("img"):
                for attr in ("src", "data-src", "data-lazy-src", "data-original"):
                    s = img.get(attr, "")
                    if s and ("rukminim" in s or "flixcart" in s) and "sprite" not in s:
                        srcs.add(s.split("?")[0].split("._")[0])
            result["images_count"] = min(len(srcs), 12)

        # ── Buy box: check for exact buy-button text in any element (FK uses unstyled divs)
        _BUY_EXACT = re.compile(
            r"^(add to (cart|bag)|buy now|place order)$", re.I
        )
        _BUY_PARTIAL = re.compile(
            r"add to (cart|bag)|buy now|buy at|place order", re.I
        )
        buy_btn = _find_buy_button(soup)   # checks <button> tags
        if not buy_btn:
            for el in soup.find_all(["div", "span", "a", "button"]):
                txt = _text(el).strip()
                # Exact match: element whose entire text IS the buy action
                if _BUY_EXACT.match(txt):
                    buy_btn = el
                    break
                # Partial match only if element has button semantics
                role = el.get("role", "")
                tab  = el.get("tabindex", "")
                if (role == "button" or tab == "0") and _BUY_PARTIAL.search(txt.lower()):
                    buy_btn = el
                    break
        result["buy_box"] = buy_btn is not None

        # ── In stock: JSON-LD first, then OOS signal scan
        if jsonld_instock is not None:
            result["in_stock"] = jsonld_instock
        else:
            oos_found = False
            for el in soup.find_all(["div", "span", "p", "h2", "h3", "button"]):
                if el.find(["div", "span", "p"]):
                    continue
                txt = _text(el).strip().lower()
                if txt in ("out of stock", "currently unavailable", "sold out",
                           "notify me", "coming soon"):
                    oos_found = True
                    break
            result["in_stock"] = not oos_found

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

        # ── Sizes: Flipkart sizes are React-rendered and NOT in the static HTML.
        # We attempt DOM walk (works if Zyte fully hydrates) but accept 0 if not found.
        sizes, sizes_unavailable = [], []
        size_container = None

        for pattern in (r"select\s+size", r"^size$"):
            for node in soup.find_all(string=re.compile(pattern, re.I)):
                parent = node.find_parent()
                for _ in range(12):
                    if not parent:
                        break
                    short_lis = [li for li in parent.find_all("li")
                                 if 1 <= len(_text(li).split("\n")[0].strip()) <= 8]
                    if len(short_lis) >= 2:
                        size_container = parent
                        break
                    parent = parent.find_parent()
                if size_container:
                    break
            if size_container:
                break

        if size_container:
            for li in size_container.find_all("li"):
                val = _text(li).split("\n")[0].strip()
                if not val or not _is_valid_size(val):
                    continue
                classes = " ".join(li.get("class") or [])
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

        # ── Colors: walk DOM from "Colour"/"Color" label
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
        # ══════════════════════════════════════════════════════════
        # PRIMARY SOURCE: window.__myx.pdpData (Myntra's React state)
        # Contains: name, price, sizes[], colours[], sellers[]
        # ══════════════════════════════════════════════════════════
        myx = _extract_window_var(soup, "__myx")
        pdp = myx.get("pdpData", {})

        if pdp:
            # ── Title from pdpData
            name = (pdp.get("name") or "").strip()
            if name:
                result["title"]    = name
                result["title_ok"] = _title_ok(name)

            # ── Price: pdpData.price = {"mrp": 3499, "discounted": 1499}
            price_obj = pdp.get("price") or {}
            if isinstance(price_obj, dict):
                p = price_obj.get("discounted") or price_obj.get("mrp")
                if p:
                    try:
                        result["price"] = int(float(p))
                    except (TypeError, ValueError):
                        pass
            # Also try selectedSeller.discountedPrice
            if not result["price"]:
                sel_seller = pdp.get("selectedSeller") or {}
                sp = sel_seller.get("discountedPrice")
                if sp:
                    try:
                        result["price"] = int(float(sp))
                    except (TypeError, ValueError):
                        pass

            # ── Sizes: pdpData.sizes[] = [{label:"6", available:true, ...}, ...]
            sizes, sizes_unavailable = [], []
            for s in pdp.get("sizes", []):
                label = str(s.get("label", "")).strip()
                if label and _is_valid_size(label):
                    if s.get("available"):
                        sizes.append(label)
                    else:
                        sizes_unavailable.append(label)
            result["sizes"]            = list(dict.fromkeys(sizes))
            result["sizes_unavailable"]= list(dict.fromkeys(sizes_unavailable))

            # ── In stock + Buy box: if selectedSeller exists and any size available
            has_seller  = bool(pdp.get("selectedSeller"))
            has_stock   = bool(sizes)
            result["in_stock"] = has_stock
            result["buy_box"]  = has_seller and has_stock

            # ── Seller: selectedSeller.sellerName or sellers[0].sellerName
            sel = pdp.get("selectedSeller") or {}
            seller_name = (sel.get("sellerName") or sel.get("displayName") or "").strip()
            if not seller_name:
                sellers = pdp.get("sellers") or []
                if sellers:
                    seller_name = (sellers[0].get("sellerName") or
                                   sellers[0].get("displayName") or "").strip()
            result["sold_by"] = seller_name or None

            # ── Colors: pdpData.colours[] = [{label:"Olive", styleId:..., image:...}, ...]
            colour_list = pdp.get("colours") or []
            result["colors"] = [
                c.get("label", "").strip()
                for c in colour_list
                if c.get("label", "").strip()
            ]

        # ══════════════════════════════════════════════════════════
        # FALLBACKS (when pdpData not available / incomplete)
        # ══════════════════════════════════════════════════════════

        # ── Title fallback
        if not result["title"]:
            h1_tags = soup.find_all("h1")
            parts = [_text(h) for h in h1_tags if _text(h)]
            if not parts:
                pt = soup.find("title")
                if pt:
                    parts = [_text(pt).split("|")[0].strip()]
            title = " ".join(parts[:2]).strip()
            result["title"]    = title
            result["title_ok"] = _title_ok(title)

        # ── Price fallback
        if not result["price"]:
            result["price"] = _selling_price(soup.get_text())

        # ── Images: always from HTML (CDN scan)
        srcs = set()
        for img in soup.find_all("img"):
            for attr in ("src", "data-src", "data-lazy-src", "data-original"):
                s = img.get(attr, "")
                if s and "myntassets" in s and "logo" not in s.lower():
                    srcs.add(s.split("?")[0])
        result["images_count"] = len(srcs)

        # ── HTML fallbacks for buy_box / in_stock / sold_by / colors
        # (only used when pdpData wasn't available above)

        if result["buy_box"] is False and result["in_stock"] is None:
            # buy_box: Myntra renders "pdp-add-to-bag" div or "ADD TO BAG" text
            buy_btn = soup.select_one("div.pdp-add-to-bag, button.pdp-add-to-bag")
            if not buy_btn:
                buy_btn = _find_buy_button(soup)
            if not buy_btn:
                for el in soup.find_all(["div", "span", "a", "button"]):
                    txt = _text(el).strip()
                    if re.fullmatch(r"add to (cart|bag)|buy now", txt, re.I):
                        buy_btn = el
                        break
            result["buy_box"] = buy_btn is not None

            # in_stock: OOS signal scan
            oos_found = False
            for el in soup.find_all(["div", "span", "p", "h4", "button"]):
                if el.find(["div", "span", "p"]):
                    continue
                txt = _text(el).strip().lower()
                if txt in ("out of stock", "sold out", "notify me",
                           "currently unavailable", "coming soon"):
                    oos_found = True
                    break
            result["in_stock"] = not oos_found

        if not result["sold_by"]:
            # HTML seller scan
            for node in soup.find_all(string=re.compile(r"(Sold|Fulfilled|Ships)\s+by", re.I)):
                parent = node.find_parent()
                a_tag  = parent.find("a") if parent else None
                if a_tag:
                    result["sold_by"] = _text(a_tag).strip()
                    break
                elif parent:
                    val = re.sub(r"(Sold|Fulfilled|Ships)\s+by\s*:?\s*",
                                 "", _text(parent), flags=re.I).strip()
                    if val and len(val) < 50 and not val.startswith("/"):
                        result["sold_by"] = val
                        break

        if not result["colors"]:
            # HTML color scan — "MORE COLORS" heading, then "Colour" label
            for heading in soup.find_all(string=re.compile(r"more\s+colou?rs?", re.I)):
                parent = heading.find_parent()
                for _ in range(5):
                    if not parent:
                        break
                    if parent.find_all("img") or parent.find_all("li"):
                        break
                    parent = parent.find_parent()
                if parent:
                    for img in parent.find_all("img"):
                        alt = img.get("alt", "").strip()
                        if alt and len(alt) < 30 and not _INVALID_COLOR_WORDS.search(alt):
                            result["colors"].append(alt)
                    break

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
