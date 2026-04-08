"""
Neeman's Listing Health Monitor — Streamlit Web Dashboard
Run with:  streamlit run dashboard.py
"""

import json
import os
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv, set_key

load_dotenv()

ENV_FILE = Path(__file__).parent / ".env"

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Neeman's Listing Health Monitor",
    page_icon="👟",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Imports ────────────────────────────────────────────────────────────────────
from core import (
    collect_product_flags,
    compute_flags,
    product_status,
    scrape_listing,
)
from storage import (
    CatalogRow,
    catalog_as_csv_bytes,
    catalog_as_dicts,
    read_catalog,
    read_reports,
    reports_as_csv_bytes,
    write_catalog,
    write_report_rows,
)

# ──────────────────────────────────────────────────────────────────────────────
# CSS
# ──────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

.dashboard-header {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%);
    border-radius: 16px; padding: 28px 36px; margin-bottom: 24px;
    display: flex; align-items: center; justify-content: space-between;
}
.dashboard-header h1 { color:#fff; font-size:26px; font-weight:700; margin:0; }
.dashboard-header p  { color:#94a3b8; margin:4px 0 0 0; font-size:13px; }
.header-badge {
    background:rgba(255,255,255,0.1); border:1px solid rgba(255,255,255,0.15);
    border-radius:8px; padding:8px 16px; color:#e2e8f0; font-size:13px; font-weight:500;
}

.metric-card {
    background:#fff; border-radius:12px; padding:20px 24px;
    box-shadow:0 1px 3px rgba(0,0,0,0.08),0 0 0 1px rgba(0,0,0,0.04); text-align:center;
}
.metric-card .metric-value { font-size:36px; font-weight:700; line-height:1; margin-bottom:6px; }
.metric-card .metric-label { font-size:12px; font-weight:500; color:#64748b; text-transform:uppercase; letter-spacing:.05em; }

.badge { display:inline-block; padding:3px 10px; border-radius:999px; font-size:12px; font-weight:600; }
.badge-green  { background:#dcfce7; color:#166534; }
.badge-yellow { background:#fef9c3; color:#854d0e; }
.badge-red    { background:#fee2e2; color:#991b1b; }
.badge-error  { background:#f1f5f9; color:#475569; }

.product-card {
    background:#fff; border-radius:14px;
    box-shadow:0 1px 3px rgba(0,0,0,0.07),0 0 0 1px rgba(0,0,0,0.04);
    margin-bottom:20px; overflow:hidden;
}
.product-card-header {
    padding:16px 24px; display:flex; align-items:center; justify-content:space-between;
    border-bottom:1px solid #f1f5f9;
}
.product-card-header h3 { margin:0; font-size:16px; font-weight:600; color:#0f172a; }
.product-card-body { padding:0 24px 20px 24px; }

.flag-pill {
    background:#fff7ed; border:1px solid #fed7aa; border-radius:8px;
    padding:6px 12px; font-size:13px; color:#9a3412; margin:4px 0; display:block;
}
.flag-pill-error { background:#fef2f2; border-color:#fecaca; color:#991b1b; }

.platform-table { width:100%; border-collapse:collapse; margin-top:14px; }
.platform-table th {
    font-size:11px; font-weight:600; color:#64748b; text-transform:uppercase;
    letter-spacing:.06em; padding:8px 12px; background:#f8fafc;
    border-bottom:1px solid #e2e8f0; text-align:left;
}
.platform-table td { padding:10px 12px; font-size:14px; color:#1e293b; border-bottom:1px solid #f1f5f9; }
.platform-table tr:last-child td { border-bottom:none; }
.platform-table tr:hover td { background:#f8fafc; }

section[data-testid="stSidebar"] { background:#0f172a !important; }
section[data-testid="stSidebar"] * { color:#e2e8f0 !important; }
section[data-testid="stSidebar"] .stButton button {
    background:#3b82f6 !important; color:white !important; border:none !important;
    border-radius:8px !important; font-weight:600 !important; width:100% !important;
}
section[data-testid="stSidebar"] .stButton button:hover { background:#2563eb !important; }

.stTabs [data-baseweb="tab-list"] {
    gap:4px; background:#f1f5f9; border-radius:10px; padding:4px;
}
.stTabs [data-baseweb="tab"] { border-radius:7px; padding:8px 20px; font-weight:500; }
.stTabs [aria-selected="true"] { background:#fff !important; box-shadow:0 1px 3px rgba(0,0,0,.1) !important; }

hr { border:none; border-top:1px solid #f1f5f9; margin:16px 0; }
</style>
""", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────────
# Session state
# ──────────────────────────────────────────────────────────────────────────────
def _init_state():
    defaults = {
        "results": [],
        "flags_by_product": {},
        "timestamp": None,
        "is_running": False,
        "key_bee": os.environ.get("SCRAPINGBEE_API_KEY", ""),
        "keys_saved": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


def _apply_keys():
    if st.session_state["key_bee"]:
        os.environ["SCRAPINGBEE_API_KEY"] = st.session_state["key_bee"]

def _save_keys():
    ENV_FILE.touch(exist_ok=True)
    if st.session_state["key_bee"]:
        set_key(str(ENV_FILE), "SCRAPINGBEE_API_KEY", st.session_state["key_bee"])

_apply_keys()


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
STATUS_EMOJI  = {"GREEN":"🟢","YELLOW":"🟡","RED":"🔴","ERROR":"⚫"}
STATUS_CLASS  = {"GREEN":"badge-green","YELLOW":"badge-yellow","RED":"badge-red","ERROR":"badge-error"}

def _badge(status):
    return f'<span class="badge {STATUS_CLASS.get(status,"badge-error")}">{STATUS_EMOJI.get(status,"")} {status}</span>'

def _price_str(price):
    return f"₹{int(price):,}" if price else "—"

def _check(val):
    return "✅" if val else "❌"

def _bee_ok():
    return bool(os.environ.get("SCRAPINGBEE_API_KEY"))


# ──────────────────────────────────────────────────────────────────────────────
# Run logic
# ──────────────────────────────────────────────────────────────────────────────
def do_run(catalog_rows: list[CatalogRow]):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    by_product = defaultdict(list)
    for row in catalog_rows:
        by_product[row.product_name].append(row)

    total = sum(len(v) for v in by_product.values())
    all_results, flags_by_product = [], {}
    idx = 0

    progress_bar = st.progress(0, text="Starting…")
    status_box   = st.empty()

    for product_name, rows in by_product.items():
        product_results = []
        for i, row in enumerate(rows):
            progress_bar.progress(
                idx / total,
                text=f"Scraping **{row.product_name}** on **{row.platform_name}** ({idx+1}/{total})"
            )
            status_box.info(f"⏳ `{row.url[:70]}…`")
            result = scrape_listing(row)
            product_results.append(result)
            idx += 1
            if i < len(rows) - 1:
                import random
                time.sleep(random.uniform(1, 3))

        product_results = compute_flags(product_results)
        all_results.extend(product_results)
        flags_by_product[product_name] = collect_product_flags(product_results)

    progress_bar.progress(1.0, text="✅ Done!")
    status_box.empty()

    st.session_state["results"]          = all_results
    st.session_state["flags_by_product"] = flags_by_product
    st.session_state["timestamp"]        = timestamp

    try:
        write_report_rows(all_results, timestamp)
        st.toast("✅ Results saved to reports.csv", icon="💾")
    except Exception as exc:
        st.toast(f"⚠️ Could not save report: {exc}", icon="⚠️")


# ──────────────────────────────────────────────────────────────────────────────
# Sidebar
# ──────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 👟 Neeman's Monitor")
    st.markdown("---")

    # ── ScrapingBee key ──────────────────────────────────────────────────────
    with st.expander("🔑 ScrapingBee API Key", expanded=not _bee_ok()):
        bee_input = st.text_input(
            "API Key",
            value=st.session_state["key_bee"],
            type="password",
            placeholder="Paste your ScrapingBee key…",
            label_visibility="collapsed",
        )
        if st.button("💾 Save Key", use_container_width=True, type="primary"):
            st.session_state["key_bee"] = bee_input.strip()
            _apply_keys()
            _save_keys()
            st.session_state["keys_saved"] = True
            st.rerun()

        if st.session_state.get("keys_saved"):
            st.success("Key saved ✅")
            st.session_state["keys_saved"] = False

        st.caption("Get your key → [app.scrapingbee.com](https://app.scrapingbee.com)")

    # ── Status ───────────────────────────────────────────────────────────────
    st.markdown("**Status**")
    st.markdown(f"{'🟢' if _bee_ok() else '🔴'} ScrapingBee API Key")

    st.markdown("---")

    # ── Catalog summary ──────────────────────────────────────────────────────
    try:
        catalog = read_catalog(skip_inactive=True)
        catalog_error = None
    except Exception as e:
        catalog = []
        catalog_error = str(e)

    if catalog_error:
        st.error(f"Catalog error: {catalog_error}")
    elif catalog:
        st.success(f"{len(catalog)} active listing(s)")
    else:
        st.warning("Catalog is empty — add listings in the 📋 Catalog tab")

    st.markdown("---")
    st.markdown("**Run Options**")

    run_mode = st.radio("Mode", ["All listings", "By Product", "By Platform"],
                        label_visibility="collapsed")

    filter_value = None
    if run_mode == "By Product" and catalog:
        filter_value = st.selectbox("Product", sorted(set(r.product_name for r in catalog)))
    elif run_mode == "By Platform" and catalog:
        filter_value = st.selectbox("Platform", sorted(set(r.platform_name for r in catalog)))

    st.markdown("")
    run_clicked = st.button(
        "🚀 Run Health Check", use_container_width=True, type="primary",
        disabled=not (_bee_ok() and bool(catalog)),
    )
    dry_run_clicked = st.button(
        "🔍 Dry Run (preview)", use_container_width=True,
        disabled=not bool(catalog),
    )

    st.markdown("---")
    if st.session_state["timestamp"]:
        st.caption(f"Last run: {st.session_state['timestamp']}")


# ──────────────────────────────────────────────────────────────────────────────
# Handle run
# ──────────────────────────────────────────────────────────────────────────────
if run_clicked and catalog:
    if run_mode == "By Product" and filter_value:
        rows_to_scrape = [r for r in catalog if r.product_name == filter_value]
    elif run_mode == "By Platform" and filter_value:
        rows_to_scrape = [r for r in catalog if r.platform_name == filter_value]
    else:
        rows_to_scrape = catalog
    do_run(rows_to_scrape)
    st.rerun()


# ──────────────────────────────────────────────────────────────────────────────
# Header
# ──────────────────────────────────────────────────────────────────────────────
ts_display = st.session_state["timestamp"] or "No run yet"
st.markdown(f"""
<div class="dashboard-header">
  <div>
    <h1>👟 Listing Health Monitor</h1>
    <p>Neeman's Marketplace Intelligence · Powered by ScrapingBee</p>
  </div>
  <div class="header-badge">Last run: {ts_display}</div>
</div>
""", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────────
# Metric row
# ──────────────────────────────────────────────────────────────────────────────
results          = st.session_state["results"]
flags_by_product = st.session_state["flags_by_product"]
products_seen    = list(dict.fromkeys(r["product_name"] for r in results))

n_products  = len(products_seen)
n_platforms = len(results)
n_flags     = sum(len(f) for f in flags_by_product.values())
n_green     = sum(1 for r in results if r["status"] == "GREEN")
n_yellow    = sum(1 for r in results if r["status"] == "YELLOW")
n_red       = sum(1 for r in results if r["status"] in ("RED","ERROR"))

c1,c2,c3,c4,c5,c6 = st.columns(6)
for col, val, label, color in [
    (c1, n_products,  "Products",   "#3b82f6"),
    (c2, n_platforms, "Listings",   "#8b5cf6"),
    (c3, n_flags,     "Flags",      "#f59e0b"),
    (c4, n_green,     "🟢 Healthy", "#16a34a"),
    (c5, n_yellow,    "🟡 Warning", "#d97706"),
    (c6, n_red,       "🔴 Critical","#dc2626"),
]:
    col.markdown(f"""
    <div class="metric-card">
      <div class="metric-value" style="color:{color}">{val}</div>
      <div class="metric-label">{label}</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────────
# Tabs
# ──────────────────────────────────────────────────────────────────────────────
tab_report, tab_catalog, tab_history, tab_setup, tab_debug = st.tabs([
    "📊 Health Report", "📋 Catalog", "🕒 Run History", "⚙️ Setup", "🔍 Debug HTML",
])


# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 — Health Report
# ════════════════════════════════════════════════════════════════════════════════
with tab_report:

    if dry_run_clicked and catalog:
        st.info(f"**Dry Run** — {len(catalog)} listing(s) would be scraped")
        st.dataframe(pd.DataFrame([
            {"#": i+1, "Product": r.product_name, "Platform": r.platform_name, "URL": r.url}
            for i, r in enumerate(catalog)
        ]), use_container_width=True, hide_index=True)

    elif not results:
        st.markdown("""
        <div style="text-align:center;padding:60px 0;color:#94a3b8;">
          <div style="font-size:64px">🔍</div>
          <div style="font-size:18px;font-weight:600;color:#475569;margin-top:16px">No results yet</div>
          <div style="font-size:14px;margin-top:8px">
            Add listings in <strong>📋 Catalog</strong> tab, then hit
            <strong>🚀 Run Health Check</strong> in the sidebar
          </div>
        </div>""", unsafe_allow_html=True)

    else:
        # ── Filter bar ──────────────────────────────────────────────────────
        cf1, cf2, cf3 = st.columns([3,2,1])
        with cf1:
            fp = st.multiselect("Filter by product", sorted(products_seen), placeholder="All products")
        with cf2:
            fs = st.multiselect("Filter by status", ["GREEN","YELLOW","RED","ERROR"], placeholder="All")
        with cf3:
            st.markdown("<br>", unsafe_allow_html=True)
            flags_only = st.checkbox("Flagged only")

        st.markdown("---")

        # ── Download button ─────────────────────────────────────────────────
        st.download_button(
            "⬇️ Download full report (CSV)",
            data=reports_as_csv_bytes(),
            file_name=f"neemans_report_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
        )
        st.markdown("")

        # ── Product cards ────────────────────────────────────────────────────
        displayed = 0
        for product_name in products_seen:
            if fp and product_name not in fp:
                continue
            prod_results = [r for r in results if r["product_name"] == product_name]
            prod_flags   = flags_by_product.get(product_name, [])
            status       = product_status(prod_results)

            if fs and status not in fs:
                continue
            if flags_only and not prod_flags:
                continue

            displayed += 1

            rows_html = ""
            for r in prod_results:
                sz_avail   = r.get("sizes", [])
                sz_unavail = r.get("sizes_unavailable", [])
                sz_tip = (", ".join(sz_avail) if sz_avail and sz_avail != ["Could not parse"] else "–")
                unavail_tip = (", ".join(sz_unavail) if sz_unavail else "")

                sz_cell = "?" if sz_avail == ["Could not parse"] else str(len(sz_avail))
                if sz_unavail:
                    sz_cell += f' <span style="color:#dc2626;font-size:11px">({len(sz_unavail)} OOS)</span>'

                n_imgs   = r.get("images_count", 0)
                img_cell = f'<span style="color:{"#16a34a" if n_imgs>=5 else "#dc2626"}">{n_imgs}</span>'

                title     = r.get("title") or "–"
                title_ok  = r.get("title_ok")
                title_display = (title[:40] + "…") if len(title) > 40 else title
                title_icon = ("✅" if title_ok else ("❌" if title_ok is False else "–"))

                stock = r.get("in_stock")
                stock_cell = ("✅ In stock" if stock else ("❌ OOS" if stock is False else "–"))

                sold_by = r.get("sold_by") or "–"

                rows_html += f"""
                <tr>
                  <td><strong>{r['platform']}</strong><br>
                      <span style="font-size:11px;color:#64748b">{sold_by[:30]}</span></td>
                  <td><strong>{_price_str(r.get('price'))}</strong></td>
                  <td>{stock_cell}</td>
                  <td style="text-align:center">{_check(r.get('buy_box',False))}</td>
                  <td style="text-align:center">{img_cell}</td>
                  <td title="{sz_tip}">{sz_cell}</td>
                  <td title="{title_display}">{title_icon}</td>
                  <td>{_badge(r['status'])}</td>
                </tr>"""

            # Available sizes summary row per platform
            sizes_detail = ""
            colors_detail = ""
            for r in prod_results:
                sz_avail   = [s for s in r.get("sizes", []) if s != "Could not parse"]
                sz_unavail = r.get("sizes_unavailable", [])
                if sz_avail or sz_unavail:
                    avail_pills = "".join(
                        f'<span style="background:#dcfce7;color:#166534;border-radius:4px;'
                        f'padding:2px 7px;font-size:12px;margin:2px;display:inline-block">{s}</span>'
                        for s in sz_avail
                    )
                    unavail_pills = "".join(
                        f'<span style="background:#fee2e2;color:#991b1b;border-radius:4px;'
                        f'padding:2px 7px;font-size:12px;margin:2px;display:inline-block;'
                        f'text-decoration:line-through">{s}</span>'
                        for s in sz_unavail
                    )
                    sizes_detail += (
                        f'<div style="margin:6px 0">'
                        f'<span style="font-size:12px;font-weight:600;color:#475569;min-width:90px;'
                        f'display:inline-block">{r["platform"]}:</span>'
                        f'{avail_pills}{unavail_pills}</div>'
                    )

                col_avail   = r.get("colors", [])
                col_unavail = r.get("colors_unavailable", [])
                if col_avail or col_unavail:
                    avail_cpills = "".join(
                        f'<span style="background:#dcfce7;color:#166534;border-radius:4px;'
                        f'padding:2px 7px;font-size:12px;margin:2px;display:inline-block">{c}</span>'
                        for c in col_avail
                    )
                    unavail_cpills = "".join(
                        f'<span style="background:#fee2e2;color:#991b1b;border-radius:4px;'
                        f'padding:2px 7px;font-size:12px;margin:2px;display:inline-block;'
                        f'text-decoration:line-through">{c}</span>'
                        for c in col_unavail
                    )
                    colors_detail += (
                        f'<div style="margin:6px 0">'
                        f'<span style="font-size:12px;font-weight:600;color:#475569;min-width:90px;'
                        f'display:inline-block">{r["platform"]}:</span>'
                        f'{avail_cpills}{unavail_cpills}</div>'
                    )

            flags_html = "".join(
                f'<div class="flag-pill{"" if "ERROR" not in f else "-error"}">⚠ {f}</div>'
                for f in prod_flags
            ) or '<div style="color:#16a34a;font-size:13px;padding:6px 0">✓ No flags — all clear</div>'

            sizes_section = ""
            if sizes_detail:
                sizes_section = (
                    '<div style="font-size:12px;font-weight:600;color:#64748b;margin:12px 0 6px;'
                    'text-transform:uppercase;letter-spacing:.05em">Size Availability</div>'
                    + sizes_detail
                )

            colors_section = ""
            if colors_detail:
                colors_section = (
                    '<div style="font-size:12px;font-weight:600;color:#64748b;margin:12px 0 6px;'
                    'text-transform:uppercase;letter-spacing:.05em">Colour Availability</div>'
                    + colors_detail
                )

            html_block = (
                '<div class="product-card">'
                '<div class="product-card-header">'
                f'<h3>{product_name}</h3>{_badge(status)}'
                '</div>'
                '<div class="product-card-body">'
                '<table class="platform-table">'
                '<thead><tr>'
                '<th>Platform / Sold By</th><th>Price</th><th>Stock</th>'
                '<th>Buy Button</th><th>Images</th><th>Sizes</th><th>Title</th><th>Status</th>'
                '</tr></thead>'
                f'<tbody>{rows_html}</tbody>'
                '</table>'
                + sizes_section
                + colors_section +
                '<div style="border-top:1px solid #f1f5f9;margin:12px 0 8px"></div>'
                '<div style="font-size:12px;font-weight:600;color:#64748b;margin-bottom:6px;text-transform:uppercase;letter-spacing:.05em">Flags</div>'
                + flags_html +
                '</div>'
                '</div>'
            )
            st.markdown(html_block, unsafe_allow_html=True)

        if displayed == 0:
            st.info("No products match the current filters.")


# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 — Catalog editor
# ════════════════════════════════════════════════════════════════════════════════
with tab_catalog:
    st.markdown("### 📋 Product Catalog")
    st.caption("Add, edit or delete rows directly in the table below, then click **Save Catalog**.")

    raw_rows = catalog_as_dicts(include_inactive=True)

    # Seed with example rows if empty
    if not raw_rows:
        raw_rows = [
            {"Product Internal Name": "Knit Runner", "Platform Name": "Amazon",
             "Platform URL": "https://amazon.in/dp/XXX", "Active": True},
            {"Product Internal Name": "Knit Runner", "Platform Name": "Flipkart",
             "Platform URL": "https://flipkart.com/...", "Active": True},
        ]

    edited_df = st.data_editor(
        pd.DataFrame(raw_rows),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "Product Internal Name": st.column_config.TextColumn("Product Name", width="medium"),
            "Platform Name":         st.column_config.TextColumn("Platform",     width="small"),
            "Platform URL":          st.column_config.LinkColumn("URL",          width="large",
                                         display_text="🔗 link"),
            "Active":                st.column_config.CheckboxColumn("Active",   width="small"),
        },
    )

    col_save, col_dl = st.columns([1, 1])
    with col_save:
        if st.button("💾 Save Catalog", type="primary", use_container_width=True):
            rows_to_save = []
            for _, row in edited_df.iterrows():
                rows_to_save.append({
                    "Product Internal Name": str(row.get("Product Internal Name", "")).strip(),
                    "Platform Name":         str(row.get("Platform Name", "")).strip(),
                    "Platform URL":          str(row.get("Platform URL", "")).strip(),
                    "Active":                "TRUE" if row.get("Active", True) else "FALSE",
                })
            write_catalog(rows_to_save)
            st.success(f"✅ Saved {len(rows_to_save)} row(s) to catalog.csv")
            st.rerun()

    with col_dl:
        st.download_button(
            "⬇️ Download catalog.csv",
            data=catalog_as_csv_bytes(),
            file_name="neemans_catalog.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.markdown("---")
    st.markdown("#### Coverage summary")
    if raw_rows:
        by_prod = defaultdict(list)
        for r in raw_rows:
            if r.get("Active"):
                by_prod[r["Product Internal Name"]].append(r["Platform Name"])
        for prod, plats in sorted(by_prod.items()):
            with st.expander(f"**{prod}** — {len(plats)} platform(s)"):
                for p in plats:
                    st.markdown(f"• {p}")
    else:
        st.info("No rows yet — add some above.")


# ════════════════════════════════════════════════════════════════════════════════
# TAB 3 — Run History
# ════════════════════════════════════════════════════════════════════════════════
with tab_history:
    st.markdown("### 🕒 Run History")

    history = read_reports()

    if not history:
        st.info("No runs recorded yet. Run a health check to see history here.")
    else:
        df_hist = pd.DataFrame(history)

        # ── Filters ──────────────────────────────────────────────────────────
        hc1, hc2, hc3 = st.columns(3)
        with hc1:
            if "Run Timestamp" in df_hist.columns:
                run_times = ["All"] + sorted(df_hist["Run Timestamp"].unique(), reverse=True)
                sel_run = st.selectbox("Run timestamp", run_times)
                if sel_run != "All":
                    df_hist = df_hist[df_hist["Run Timestamp"] == sel_run]
        with hc2:
            if "Product Name" in df_hist.columns:
                prods = st.multiselect("Product", df_hist["Product Name"].unique().tolist())
                if prods:
                    df_hist = df_hist[df_hist["Product Name"].isin(prods)]
        with hc3:
            if "Status" in df_hist.columns:
                stats = st.multiselect("Status", df_hist["Status"].unique().tolist())
                if stats:
                    df_hist = df_hist[df_hist["Status"].isin(stats)]

        # ── Color rows ────────────────────────────────────────────────────────
        def _row_color(row):
            s = row.get("Status","")
            if s == "GREEN":            return ["background-color:#f0fdf4"]*len(row)
            if s == "YELLOW":           return ["background-color:#fefce8"]*len(row)
            if s in ("RED","ERROR"):    return ["background-color:#fef2f2"]*len(row)
            return [""]*len(row)

        st.dataframe(
            df_hist.style.apply(_row_color, axis=1),
            use_container_width=True, hide_index=True,
        )

        st.markdown(f"**{len(df_hist)}** rows shown")

        st.download_button(
            "⬇️ Download history (CSV)",
            data=reports_as_csv_bytes(),
            file_name=f"neemans_history_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )


# ════════════════════════════════════════════════════════════════════════════════
# TAB 4 — Setup
# ════════════════════════════════════════════════════════════════════════════════
with tab_setup:
    st.markdown("### ⚙️ Setup")

    # Status cards
    c1, c2 = st.columns(2)
    bee_ok = _bee_ok()
    for col, ok, label, hint in [
        (c1, bee_ok,        "ScrapingBee API Key", "Enter in sidebar → 🔑"),
        (c2, bool(catalog), "Catalog",             "Add rows in 📋 Catalog tab"),
    ]:
        bg, bd = ("#f0fdf4","#86efac") if ok else ("#fef2f2","#fca5a5")
        col.markdown(f"""
        <div style="background:{bg};border:1px solid {bd};border-radius:10px;
                    padding:14px 16px;text-align:center">
          <div style="font-size:24px">{'✅' if ok else '❌'}</div>
          <div style="font-weight:600;font-size:14px;margin-top:6px">{label}</div>
          <div style="color:#64748b;font-size:12px;margin-top:2px">
            {'Configured' if ok else hint}</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("---")

    col_s1, col_s2 = st.columns(2)
    with col_s1:
        st.markdown("""
### Step 1 — ScrapingBee API Key
1. Sign up at [app.scrapingbee.com](https://app.scrapingbee.com) *(free trial available)*
2. Copy your API key from the dashboard
3. Paste it in the sidebar → **🔑 ScrapingBee API Key** → Save

---

### Step 2 — Add your listings
1. Go to the **📋 Catalog** tab
2. Edit the table — add a row for each product × platform combination
3. Tick **Active** for rows you want to scrape
4. Click **💾 Save Catalog**
""")
    with col_s2:
        st.markdown("""
### Step 3 — Run a health check
1. In the sidebar choose **All listings** (or filter by product/platform)
2. Click **🚀 Run Health Check**
3. Watch the live progress bar
4. Results appear in **📊 Health Report** tab instantly

---

### Step 4 — Export results
- **📊 Health Report** tab → **⬇️ Download full report (CSV)**
- **🕒 Run History** tab → see all past runs, filter, download
""")

    st.markdown("---")
    st.markdown("### Catalog format")
    st.dataframe(pd.DataFrame([
        {"Product Internal Name":"Knit Runner","Platform Name":"Amazon",
         "Platform URL":"https://amazon.in/dp/XXX","Active":"TRUE"},
        {"Product Internal Name":"Knit Runner","Platform Name":"Flipkart",
         "Platform URL":"https://flipkart.com/...","Active":"TRUE"},
        {"Product Internal Name":"Knit Runner","Platform Name":"Myntra",
         "Platform URL":"https://myntra.com/...","Active":"TRUE"},
        {"Product Internal Name":"Hemp Runner","Platform Name":"Nykaa",
         "Platform URL":"https://nykaa.com/...","Active":"FALSE"},
    ]), use_container_width=True, hide_index=True)

# ════════════════════════════════════════════════════════════════════════════════
# TAB 5 — Debug HTML
# ════════════════════════════════════════════════════════════════════════════════
with tab_debug:
    st.markdown("### 🔍 Debug — Raw HTML from ScrapingBee")
    st.caption(
        "Every scrape automatically saves the raw HTML ScrapingBee returned. "
        "Download a file and send it to your developer to diagnose parser issues."
    )

    debug_dir = Path("debug_html")
    html_files = sorted(debug_dir.glob("*.html")) if debug_dir.exists() else []

    if not html_files:
        st.info("No debug HTML files yet. Run a health check first — files will appear here automatically.")
    else:
        for f in html_files:
            size_kb = f.stat().st_size // 1024
            col_a, col_b, col_c = st.columns([3, 1, 1])
            col_a.markdown(f"**{f.stem.replace('_', '.')}**")
            col_b.caption(f"{size_kb} KB")
            with col_c:
                st.download_button(
                    label="⬇️ Download",
                    data=f.read_bytes(),
                    file_name=f.name,
                    mime="text/html",
                    key=f"dl_{f.name}",
                )

        st.markdown("---")
        st.markdown("**Quick diagnosis for each file:**")
        for f in html_files:
            try:
                content = f.read_text(encoding="utf-8", errors="replace").lower()
                checks = {
                    "Page has product title (h1)": "<h1" in content,
                    "Price symbol found (₹)":      "₹" in content,
                    "Select Size text found":       "select size" in content,
                    "Buy button text found":        "add to cart" in content or "add to bag" in content or "buy now" in content,
                    "Product images (CDN found)":   "rukminim" in content or "myntassets" in content or "media.amazon" in content or "m.media-amazon" in content,
                    "CAPTCHA / bot block":          "captcha" in content or "access denied" in content or "robot" in content,
                    "Maintenance / error page":     "site maintenance" in content or "something went wrong" in content or "529" in content,
                }
                with st.expander(f"📄 {f.stem.replace('_', '.')} — click to expand diagnosis"):
                    for label, ok in checks.items():
                        icon = "✅" if ok else "❌"
                        # Invert logic for bad signals
                        if label in ("CAPTCHA / bot block", "Maintenance / error page"):
                            icon = "🚨" if ok else "✅"
                        st.markdown(f"{icon} {label}")
            except Exception as e:
                st.warning(f"Could not read {f.name}: {e}")
