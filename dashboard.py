"""
Neeman's Listing Health Monitor — Streamlit Web Dashboard
Run with:  streamlit run dashboard.py
"""

import json
import os
import tempfile
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv, set_key

load_dotenv()

ENV_FILE = Path(__file__).parent / ".env"


def _load_streamlit_secrets():
    """
    On Streamlit Community Cloud, secrets live in st.secrets (not os.environ).
    This function copies them into os.environ so the rest of the codebase
    (sheets.py, core.py) can read them the normal way.
    """
    try:
        import streamlit as _st
        mapping = {
            "SCRAPINGBEE_API_KEY": "SCRAPINGBEE_API_KEY",
            "GOOGLE_SHEET_ID": "GOOGLE_SHEET_ID",
            "GOOGLE_SHEETS_CREDENTIALS_JSON": "GOOGLE_SHEETS_CREDENTIALS_JSON",
            "GOOGLE_SHEETS_CREDENTIALS_PATH": "GOOGLE_SHEETS_CREDENTIALS_PATH",
        }
        for secret_key, env_key in mapping.items():
            if secret_key in _st.secrets and not os.environ.get(env_key):
                os.environ[env_key] = str(_st.secrets[secret_key])
    except Exception:
        pass   # not on Streamlit Cloud or secrets not configured — skip silently


_load_streamlit_secrets()

# ── Page config (must be first Streamlit call) ─────────────────────────────────
st.set_page_config(
    page_title="Neeman's Listing Health Monitor",
    page_icon="👟",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Imports that need .env loaded first ───────────────────────────────────────
from core import (
    collect_product_flags,
    compute_flags,
    product_status,
    run_scrape,
    scrape_listing,
)
from sheets import CatalogRow, read_catalog, write_report_rows


# ──────────────────────────────────────────────────────────────────────────────
# Custom CSS
# ──────────────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
/* ── Global ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

/* ── Top header bar ── */
.dashboard-header {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%);
    border-radius: 16px;
    padding: 28px 36px;
    margin-bottom: 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.dashboard-header h1 {
    color: #ffffff;
    font-size: 26px;
    font-weight: 700;
    margin: 0;
    letter-spacing: -0.3px;
}
.dashboard-header p {
    color: #94a3b8;
    margin: 4px 0 0 0;
    font-size: 13px;
}
.header-badge {
    background: rgba(255,255,255,0.1);
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 8px;
    padding: 8px 16px;
    color: #e2e8f0;
    font-size: 13px;
    font-weight: 500;
}

/* ── Metric cards ── */
.metric-card {
    background: #ffffff;
    border-radius: 12px;
    padding: 20px 24px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08), 0 0 0 1px rgba(0,0,0,0.04);
    text-align: center;
}
.metric-card .metric-value {
    font-size: 36px;
    font-weight: 700;
    line-height: 1;
    margin-bottom: 6px;
}
.metric-card .metric-label {
    font-size: 12px;
    font-weight: 500;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

/* ── Status badge ── */
.badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.03em;
}
.badge-green  { background: #dcfce7; color: #166534; }
.badge-yellow { background: #fef9c3; color: #854d0e; }
.badge-red    { background: #fee2e2; color: #991b1b; }
.badge-error  { background: #f1f5f9; color: #475569; }

/* ── Product card ── */
.product-card {
    background: #ffffff;
    border-radius: 14px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.07), 0 0 0 1px rgba(0,0,0,0.04);
    margin-bottom: 20px;
    overflow: hidden;
}
.product-card-header {
    padding: 16px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid #f1f5f9;
}
.product-card-header h3 {
    margin: 0;
    font-size: 16px;
    font-weight: 600;
    color: #0f172a;
}
.product-card-body { padding: 0 24px 20px 24px; }

/* ── Flag pill ── */
.flag-pill {
    background: #fff7ed;
    border: 1px solid #fed7aa;
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 13px;
    color: #9a3412;
    margin: 4px 0;
    display: block;
}
.flag-pill-error {
    background: #fef2f2;
    border-color: #fecaca;
    color: #991b1b;
}

/* ── Platform table ── */
.platform-table { width: 100%; border-collapse: collapse; margin-top: 14px; }
.platform-table th {
    font-size: 11px;
    font-weight: 600;
    color: #64748b;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    padding: 8px 12px;
    background: #f8fafc;
    border-bottom: 1px solid #e2e8f0;
    text-align: left;
}
.platform-table td {
    padding: 10px 12px;
    font-size: 14px;
    color: #1e293b;
    border-bottom: 1px solid #f1f5f9;
}
.platform-table tr:last-child td { border-bottom: none; }
.platform-table tr:hover td { background: #f8fafc; }

/* ── Sidebar ── */
section[data-testid="stSidebar"] { background: #0f172a !important; }
section[data-testid="stSidebar"] * { color: #e2e8f0 !important; }
section[data-testid="stSidebar"] .stButton button {
    background: #3b82f6 !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    width: 100% !important;
}
section[data-testid="stSidebar"] .stButton button:hover {
    background: #2563eb !important;
}

/* ── Env status dots ── */
.env-ok   { color: #4ade80; font-size: 10px; }
.env-fail { color: #f87171; font-size: 10px; }

/* ── Tab styling ── */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    background: #f1f5f9;
    border-radius: 10px;
    padding: 4px;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 7px;
    padding: 8px 20px;
    font-weight: 500;
}
.stTabs [aria-selected="true"] {
    background: #ffffff !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1) !important;
}

/* ── Progress container ── */
.scrape-progress {
    background: #f0f9ff;
    border: 1px solid #bae6fd;
    border-radius: 10px;
    padding: 16px 20px;
    font-size: 14px;
    color: #0369a1;
}

/* ── Divider ── */
hr { border: none; border-top: 1px solid #f1f5f9; margin: 16px 0; }
</style>
""", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────────
# Session state defaults
# ──────────────────────────────────────────────────────────────────────────────

def _init_state():
    defaults = {
        # scrape results
        "results": [],
        "flags_by_product": {},
        "timestamp": None,
        # catalog
        "catalog": [],
        "catalog_loaded": False,
        "catalog_error": None,
        # run state
        "is_running": False,
        "run_log": [],
        # ── stored credentials (entered in dashboard) ──
        "key_bee": os.environ.get("SCRAPINGBEE_API_KEY", ""),
        "key_sheet_id": os.environ.get("GOOGLE_SHEET_ID", ""),
        "key_creds_path": os.environ.get("GOOGLE_SHEETS_CREDENTIALS_PATH", ""),
        "key_creds_json": None,   # parsed dict from uploaded JSON
        "keys_saved": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ──────────────────────────────────────────────────────────────────────────────
# Credential helpers
# ──────────────────────────────────────────────────────────────────────────────

def _apply_stored_keys():
    """Push session-state credentials into os.environ so all modules pick them up."""
    if st.session_state["key_bee"]:
        os.environ["SCRAPINGBEE_API_KEY"] = st.session_state["key_bee"]

    if st.session_state["key_sheet_id"]:
        os.environ["GOOGLE_SHEET_ID"] = st.session_state["key_sheet_id"]

    # Prefer JSON-string path (cloud-safe) over file path
    if st.session_state["key_creds_json"] is not None:
        os.environ["GOOGLE_SHEETS_CREDENTIALS_JSON"] = json.dumps(st.session_state["key_creds_json"])
        # Also keep a temp file for libraries that strictly need a path
        if not st.session_state.get("key_creds_path"):
            tmp = tempfile.NamedTemporaryFile(
                delete=False, suffix=".json", prefix="neemans_creds_"
            )
            tmp.write(json.dumps(st.session_state["key_creds_json"]).encode())
            tmp.close()
            st.session_state["key_creds_path"] = tmp.name
        os.environ["GOOGLE_SHEETS_CREDENTIALS_PATH"] = st.session_state["key_creds_path"]

    elif st.session_state["key_creds_path"]:
        os.environ["GOOGLE_SHEETS_CREDENTIALS_PATH"] = st.session_state["key_creds_path"]


def _save_keys_to_env_file():
    """Write current keys to .env file so they survive a local server restart."""
    ENV_FILE.touch(exist_ok=True)
    if st.session_state["key_bee"]:
        set_key(str(ENV_FILE), "SCRAPINGBEE_API_KEY", st.session_state["key_bee"])
    if st.session_state["key_sheet_id"]:
        set_key(str(ENV_FILE), "GOOGLE_SHEET_ID", st.session_state["key_sheet_id"])
    # Store JSON string so cloud deploys don't need a file
    if st.session_state["key_creds_json"]:
        set_key(str(ENV_FILE), "GOOGLE_SHEETS_CREDENTIALS_JSON",
                json.dumps(st.session_state["key_creds_json"]))
    elif st.session_state["key_creds_path"]:
        set_key(str(ENV_FILE), "GOOGLE_SHEETS_CREDENTIALS_PATH",
                st.session_state["key_creds_path"])


# Apply stored keys every render so env vars are always fresh
_apply_stored_keys()


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

STATUS_EMOJI = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴", "ERROR": "⚫"}
STATUS_CLASS = {"GREEN": "badge-green", "YELLOW": "badge-yellow", "RED": "badge-red", "ERROR": "badge-error"}

def _badge(status: str) -> str:
    emoji = STATUS_EMOJI.get(status, "")
    cls = STATUS_CLASS.get(status, "badge-error")
    return f'<span class="badge {cls}">{emoji} {status}</span>'

def _price_str(price) -> str:
    if price is None:
        return "—"
    return f"₹{int(price):,}"

def _check(val: bool) -> str:
    return "✅" if val else "❌"

def _env_status() -> dict:
    return {
        "SCRAPINGBEE_API_KEY": bool(os.environ.get("SCRAPINGBEE_API_KEY")),
        "GOOGLE_SHEET_ID": bool(os.environ.get("GOOGLE_SHEET_ID")),
        "GOOGLE_SHEETS_CREDENTIALS_PATH": bool(
            os.environ.get("GOOGLE_SHEETS_CREDENTIALS_PATH")
            and os.path.isfile(os.environ.get("GOOGLE_SHEETS_CREDENTIALS_PATH", ""))
        ),
    }

def _all_env_ok() -> bool:
    return all(_env_status().values())


# ──────────────────────────────────────────────────────────────────────────────
# Catalog loader
# ──────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=120, show_spinner=False)
def _load_catalog():
    return read_catalog(skip_inactive=True)


def load_catalog_cached():
    try:
        rows = _load_catalog()
        st.session_state["catalog"] = rows
        st.session_state["catalog_loaded"] = True
        st.session_state["catalog_error"] = None
    except Exception as exc:
        st.session_state["catalog_error"] = str(exc)
        st.session_state["catalog_loaded"] = False


# ──────────────────────────────────────────────────────────────────────────────
# Run logic (synchronous, with live progress via st.status)
# ──────────────────────────────────────────────────────────────────────────────

def do_run(catalog_rows: list[CatalogRow]):
    st.session_state["is_running"] = True
    st.session_state["run_log"] = []

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    by_product = defaultdict(list)
    for row in catalog_rows:
        by_product[row.product_name].append(row)

    total = sum(len(v) for v in by_product.values())
    all_results = []
    flags_by_product = {}
    idx = 0

    progress_bar = st.progress(0, text="Starting scrape…")
    status_box = st.empty()

    for product_name, rows in by_product.items():
        product_results = []
        for i, row in enumerate(rows):
            pct = int((idx / total) * 100)
            progress_bar.progress(
                pct / 100,
                text=f"Scraping **{row.product_name}** on **{row.platform_name}** ({idx + 1}/{total})"
            )
            status_box.info(f"⏳ Fetching `{row.url[:60]}…`")
            st.session_state["run_log"].append(
                f"[{idx + 1}/{total}] {row.product_name} — {row.platform_name}"
            )

            result = scrape_listing(row)
            product_results.append(result)
            idx += 1

            if i < len(rows) - 1:
                import random
                time.sleep(random.uniform(1, 3))

        product_results = compute_flags(product_results)
        all_results.extend(product_results)
        flags_by_product[product_name] = collect_product_flags(product_results)

    progress_bar.progress(1.0, text="✅ Scrape complete!")
    status_box.empty()

    st.session_state["results"] = all_results
    st.session_state["flags_by_product"] = flags_by_product
    st.session_state["timestamp"] = timestamp
    st.session_state["is_running"] = False

    # Write to Sheets
    try:
        write_report_rows(all_results, timestamp)
        st.toast("✅ Results saved to Google Sheets", icon="📊")
    except Exception as exc:
        st.toast(f"⚠️ Sheet write failed: {exc}", icon="⚠️")


# ──────────────────────────────────────────────────────────────────────────────
# Sidebar
# ──────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### 👟 Neeman's Monitor")
    st.markdown("---")

    # ── API Key Configuration ──────────────────────────────────────────────
    with st.expander("🔑 Configure API Keys", expanded=not _all_env_ok()):

        bee_input = st.text_input(
            "ScrapingBee API Key",
            value=st.session_state["key_bee"],
            type="password",
            placeholder="Paste your ScrapingBee key…",
            help="Get it from app.scrapingbee.com → Dashboard",
        )

        sheet_input = st.text_input(
            "Google Sheet ID",
            value=st.session_state["key_sheet_id"],
            placeholder="The long ID from your Sheet URL",
            help="From: docs.google.com/spreadsheets/d/THIS_PART/edit",
        )

        creds_tab_upload, creds_tab_paste = st.tabs(["📁 Upload file", "📋 Paste JSON"])

        creds_file = None
        creds_pasted = None

        with creds_tab_upload:
            creds_file = st.file_uploader(
                "Service Account JSON file",
                type=["json"],
                label_visibility="collapsed",
                help="Download from Google Cloud Console → IAM → Service Accounts → Keys",
            )

        with creds_tab_paste:
            creds_pasted = st.text_area(
                "Paste JSON content",
                label_visibility="collapsed",
                height=120,
                placeholder='{\n  "type": "service_account",\n  "project_id": "...",\n  ...\n}',
                help="Paste the entire contents of your service-account JSON file",
            )

        # Show current creds status
        if st.session_state["key_creds_json"]:
            proj = st.session_state["key_creds_json"].get("project_id", "unknown project")
            email = st.session_state["key_creds_json"].get("client_email", "")
            st.caption(f"✅ Credentials loaded · {proj}")
            if email:
                st.caption(f"📧 Share your Sheet with: `{email}`")
        elif st.session_state["key_creds_path"] and os.path.isfile(st.session_state["key_creds_path"]):
            fname = Path(st.session_state["key_creds_path"]).name
            st.caption(f"✅ Credentials file: `{fname}`")
        else:
            st.caption("❌ No credentials yet")

        col_save, col_clear = st.columns(2)
        save_keys = col_save.button("💾 Save Keys", use_container_width=True, type="primary")
        clear_keys = col_clear.button("🗑 Clear", use_container_width=True)

        if save_keys:
            # Parse credentials — prefer pasted text, then uploaded file
            if creds_pasted and creds_pasted.strip():
                try:
                    parsed = json.loads(creds_pasted.strip())
                    st.session_state["key_creds_json"] = parsed
                    st.session_state["key_creds_path"] = ""
                except Exception as e:
                    st.error(f"Invalid JSON text: {e}")
            elif creds_file is not None:
                try:
                    parsed = json.load(creds_file)
                    st.session_state["key_creds_json"] = parsed
                    st.session_state["key_creds_path"] = ""
                except Exception as e:
                    st.error(f"Invalid JSON file: {e}")

            st.session_state["key_bee"] = bee_input.strip()
            st.session_state["key_sheet_id"] = sheet_input.strip()
            _apply_stored_keys()
            _save_keys_to_env_file()
            _load_catalog.clear()         # force catalog reload with new creds
            st.session_state["keys_saved"] = True
            st.rerun()

        if clear_keys:
            for k in ["key_bee", "key_sheet_id", "key_creds_path", "key_creds_json"]:
                st.session_state[k] = "" if k != "key_creds_json" else None
            for env_var in ["SCRAPINGBEE_API_KEY", "GOOGLE_SHEET_ID", "GOOGLE_SHEETS_CREDENTIALS_PATH"]:
                os.environ.pop(env_var, None)
            st.rerun()

        if st.session_state.get("keys_saved"):
            st.success("Keys saved ✅")
            st.session_state["keys_saved"] = False

    # ── Env status indicators ──────────────────────────────────────────────
    st.markdown("**Status**")
    env = _env_status()
    for var, ok in env.items():
        dot = "🟢" if ok else "🔴"
        short = var.replace("GOOGLE_SHEETS_", "GS_").replace("SCRAPINGBEE_", "BEE_")
        st.markdown(f"{dot} `{short}`")

    st.markdown("---")

    # Load catalog
    if st.button("🔄 Reload Catalog", use_container_width=True):
        _load_catalog.clear()
        load_catalog_cached()

    if not st.session_state["catalog_loaded"]:
        load_catalog_cached()

    catalog = st.session_state["catalog"]
    catalog_error = st.session_state["catalog_error"]

    if catalog_error:
        st.error(f"Catalog error:\n{catalog_error}")
    elif catalog:
        st.success(f"{len(catalog)} active listing(s) loaded")
    else:
        st.warning("No active listings found")

    st.markdown("---")
    st.markdown("**Run Options**")

    run_mode = st.radio(
        "Mode",
        ["All listings", "By Product", "By Platform"],
        label_visibility="collapsed",
    )

    filter_value = None
    if run_mode == "By Product" and catalog:
        products = sorted(set(r.product_name for r in catalog))
        filter_value = st.selectbox("Select Product", products)
    elif run_mode == "By Platform" and catalog:
        platforms = sorted(set(r.platform_name for r in catalog))
        filter_value = st.selectbox("Select Platform", platforms)

    st.markdown("")
    run_clicked = st.button(
        "🚀 Run Health Check",
        use_container_width=True,
        disabled=not (_all_env_ok() and bool(catalog)),
        type="primary",
    )

    dry_run_clicked = st.button(
        "🔍 Dry Run (preview only)",
        use_container_width=True,
        disabled=not bool(catalog),
    )

    st.markdown("---")
    if st.session_state["timestamp"]:
        st.caption(f"Last run: {st.session_state['timestamp']}")


# ──────────────────────────────────────────────────────────────────────────────
# Handle run button
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
# Main area header
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
# Summary metric row
# ──────────────────────────────────────────────────────────────────────────────

results = st.session_state["results"]
flags_by_product = st.session_state["flags_by_product"]

products_seen = list(dict.fromkeys(r["product_name"] for r in results))
n_products = len(products_seen)
n_platforms = len(results)
n_flags = sum(len(f) for f in flags_by_product.values())
n_green = sum(1 for r in results if r["status"] == "GREEN")
n_yellow = sum(1 for r in results if r["status"] == "YELLOW")
n_red = sum(1 for r in results if r["status"] in ("RED", "ERROR"))

col1, col2, col3, col4, col5, col6 = st.columns(6)

with col1:
    st.markdown(f"""
    <div class="metric-card">
      <div class="metric-value" style="color:#3b82f6">{n_products}</div>
      <div class="metric-label">Products</div>
    </div>""", unsafe_allow_html=True)

with col2:
    st.markdown(f"""
    <div class="metric-card">
      <div class="metric-value" style="color:#8b5cf6">{n_platforms}</div>
      <div class="metric-label">Listings</div>
    </div>""", unsafe_allow_html=True)

with col3:
    st.markdown(f"""
    <div class="metric-card">
      <div class="metric-value" style="color:#f59e0b">{n_flags}</div>
      <div class="metric-label">Flags</div>
    </div>""", unsafe_allow_html=True)

with col4:
    st.markdown(f"""
    <div class="metric-card">
      <div class="metric-value" style="color:#16a34a">{n_green}</div>
      <div class="metric-label">🟢 Healthy</div>
    </div>""", unsafe_allow_html=True)

with col5:
    st.markdown(f"""
    <div class="metric-card">
      <div class="metric-value" style="color:#d97706">{n_yellow}</div>
      <div class="metric-label">🟡 Warning</div>
    </div>""", unsafe_allow_html=True)

with col6:
    st.markdown(f"""
    <div class="metric-card">
      <div class="metric-value" style="color:#dc2626">{n_red}</div>
      <div class="metric-label">🔴 Critical</div>
    </div>""", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)


# ──────────────────────────────────────────────────────────────────────────────
# Tabs
# ──────────────────────────────────────────────────────────────────────────────

tab_results, tab_catalog, tab_history, tab_setup = st.tabs([
    "📊 Health Report",
    "📋 Catalog",
    "🕒 Run History",
    "⚙️ Setup & Keys",
])


# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 — Health Report
# ════════════════════════════════════════════════════════════════════════════════

with tab_results:

    # Dry-run preview
    if dry_run_clicked and catalog:
        st.info(f"**Dry Run** — {len(catalog)} listing(s) would be scraped (no API calls made)")
        import pandas as pd
        df_preview = pd.DataFrame([
            {"#": i + 1, "Product": r.product_name, "Platform": r.platform_name, "URL": r.url}
            for i, r in enumerate(catalog)
        ])
        st.dataframe(df_preview, use_container_width=True, hide_index=True)

    elif not results:
        st.markdown("""
        <div style="text-align:center; padding: 60px 0; color: #94a3b8;">
          <div style="font-size:64px">🔍</div>
          <div style="font-size:18px; font-weight:600; color:#475569; margin-top:16px">No results yet</div>
          <div style="font-size:14px; margin-top:8px">Hit <strong>Run Health Check</strong> in the sidebar to start scanning</div>
        </div>
        """, unsafe_allow_html=True)

    else:
        # Filter bar
        col_f1, col_f2, col_f3 = st.columns([3, 2, 1])
        with col_f1:
            filter_product = st.multiselect(
                "Filter by product", options=sorted(products_seen), placeholder="All products"
            )
        with col_f2:
            filter_status = st.multiselect(
                "Filter by status", options=["GREEN", "YELLOW", "RED", "ERROR"], placeholder="All statuses"
            )
        with col_f3:
            st.markdown("<br>", unsafe_allow_html=True)
            show_flags_only = st.checkbox("Flagged only", value=False)

        st.markdown("---")

        # Render product cards
        displayed = 0
        for product_name in products_seen:
            if filter_product and product_name not in filter_product:
                continue

            prod_results = [r for r in results if r["product_name"] == product_name]
            prod_flags = flags_by_product.get(product_name, [])
            status = product_status(prod_results)

            if filter_status and status not in filter_status:
                continue
            if show_flags_only and not prod_flags:
                continue

            displayed += 1

            # Build platform rows HTML
            rows_html = ""
            for r in prod_results:
                sizes_display = ", ".join(r["sizes"]) if r["sizes"] and r["sizes"] != ["Could not parse"] else "–"
                colors_display = ", ".join(r["colors"]) if r["colors"] and r["colors"] != ["Could not parse"] else "–"
                sz_count = "?" if r["sizes"] == ["Could not parse"] else str(len(r["sizes"]))
                cl_count = "?" if r["colors"] == ["Could not parse"] else str(len(r["colors"]))
                row_status_badge = _badge(r["status"])
                rows_html += f"""
                <tr>
                  <td><strong>{r['platform']}</strong></td>
                  <td><strong>{_price_str(r.get('price'))}</strong></td>
                  <td style="text-align:center">{_check(r.get('buy_box', False))}</td>
                  <td title="{sizes_display}">{sz_count} sizes</td>
                  <td title="{colors_display}">{cl_count} colors</td>
                  <td>{row_status_badge}</td>
                </tr>"""

            # Flags HTML
            flags_html = ""
            for flag in prod_flags:
                pill_class = "flag-pill-error" if "ERROR" in flag else "flag-pill"
                flags_html += f'<div class="{pill_class}">⚠ {flag}</div>'
            if not flags_html:
                flags_html = '<div style="color:#16a34a;font-size:13px;padding:6px 0">✓ No flags — all clear</div>'

            badge_html = _badge(status)

            st.markdown(f"""
            <div class="product-card">
              <div class="product-card-header">
                <h3>{product_name}</h3>
                {badge_html}
              </div>
              <div class="product-card-body">
                <table class="platform-table">
                  <thead>
                    <tr>
                      <th>Platform</th><th>Price</th><th>Buy Box</th>
                      <th>Sizes</th><th>Colors</th><th>Status</th>
                    </tr>
                  </thead>
                  <tbody>{rows_html}</tbody>
                </table>
                <hr>
                <div style="margin-top:4px">
                  <div style="font-size:12px;font-weight:600;color:#64748b;margin-bottom:6px;text-transform:uppercase;letter-spacing:0.05em">Flags</div>
                  {flags_html}
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)

        if displayed == 0:
            st.info("No products match the current filters.")


# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 — Catalog
# ════════════════════════════════════════════════════════════════════════════════

with tab_catalog:
    if not st.session_state["catalog_loaded"]:
        st.warning("Catalog not loaded. Check your env vars and click **Reload Catalog** in the sidebar.")
    elif not catalog:
        st.info("No active listings in the Catalog sheet.")
    else:
        import pandas as pd

        col_ca, col_cb = st.columns([3, 1])
        with col_ca:
            search_q = st.text_input("🔍 Search catalog", placeholder="Product name, platform, URL…")
        with col_cb:
            st.markdown("<br>", unsafe_allow_html=True)
            st.caption(f"{len(catalog)} active listing(s)")

        rows_data = [
            {
                "Product": r.product_name,
                "Platform": r.platform_name,
                "URL": r.url,
                "Active": "✅ Yes",
            }
            for r in catalog
        ]
        if search_q:
            q = search_q.lower()
            rows_data = [
                d for d in rows_data
                if q in d["Product"].lower() or q in d["Platform"].lower() or q in d["URL"].lower()
            ]

        df_cat = pd.DataFrame(rows_data)
        st.dataframe(
            df_cat,
            use_container_width=True,
            hide_index=True,
            column_config={
                "URL": st.column_config.LinkColumn("URL", display_text="🔗 Open"),
            },
        )

        # Per-product breakdown
        st.markdown("#### Per-product platform coverage")
        by_prod = defaultdict(list)
        for r in catalog:
            by_prod[r.product_name].append(r.platform_name)

        for prod, plats in sorted(by_prod.items()):
            with st.expander(f"**{prod}** — {len(plats)} platform(s)"):
                for p in plats:
                    st.markdown(f"• {p}")


# ════════════════════════════════════════════════════════════════════════════════
# TAB 3 — Run History
# ════════════════════════════════════════════════════════════════════════════════

with tab_history:
    st.markdown("#### Historical run data from Google Sheets Reports tab")

    if not _all_env_ok():
        st.warning("Configure all env vars to load history from Google Sheets.")
    else:
        if st.button("📥 Load history from Google Sheets"):
            with st.spinner("Reading Reports sheet…"):
                try:
                    import gspread
                    from google.oauth2.service_account import Credentials

                    SCOPES = [
                        "https://www.googleapis.com/auth/spreadsheets",
                        "https://www.googleapis.com/auth/drive.readonly",
                    ]
                    creds_path = os.environ.get("GOOGLE_SHEETS_CREDENTIALS_PATH")
                    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
                    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
                    client = gspread.authorize(creds)
                    sheet = client.open_by_key(sheet_id)
                    ws = sheet.worksheet("Reports")
                    data = ws.get_all_records()
                    st.session_state["history_data"] = data
                    st.success(f"Loaded {len(data)} history row(s)")
                except Exception as exc:
                    st.error(f"Failed to load history: {exc}")

        if "history_data" in st.session_state and st.session_state["history_data"]:
            import pandas as pd
            df_hist = pd.DataFrame(st.session_state["history_data"])

            # Filters
            col_h1, col_h2 = st.columns(2)
            with col_h1:
                if "Run Timestamp" in df_hist.columns:
                    run_times = sorted(df_hist["Run Timestamp"].unique(), reverse=True)
                    sel_run = st.selectbox("Filter by run timestamp", ["All"] + list(run_times))
                    if sel_run != "All":
                        df_hist = df_hist[df_hist["Run Timestamp"] == sel_run]
            with col_h2:
                if "Status" in df_hist.columns:
                    sel_status = st.multiselect("Filter by status", df_hist["Status"].unique().tolist())
                    if sel_status:
                        df_hist = df_hist[df_hist["Status"].isin(sel_status)]

            # Color rows
            def _row_color(row):
                s = row.get("Status", "")
                if s == "GREEN":  return ["background-color:#f0fdf4"] * len(row)
                if s == "YELLOW": return ["background-color:#fefce8"] * len(row)
                if s in ("RED", "ERROR"): return ["background-color:#fef2f2"] * len(row)
                return [""] * len(row)

            st.dataframe(
                df_hist.style.apply(_row_color, axis=1),
                use_container_width=True,
                hide_index=True,
            )
        elif "history_data" not in st.session_state:
            st.info("Click **Load history** to fetch past run data from the Reports sheet.")


# ════════════════════════════════════════════════════════════════════════════════
# TAB 4 — Setup Guide
# ════════════════════════════════════════════════════════════════════════════════

with tab_setup:

    # ── Live credential status ────────────────────────────────────────────────
    st.markdown("### 🔑 Credential Status")
    env = _env_status()

    status_cols = st.columns(3)
    labels = {
        "SCRAPINGBEE_API_KEY": ("ScrapingBee Key", "app.scrapingbee.com"),
        "GOOGLE_SHEET_ID": ("Google Sheet ID", "From your Sheet URL"),
        "GOOGLE_SHEETS_CREDENTIALS_PATH": ("GSheet Credentials", "Service-account JSON"),
    }
    for col, (var, ok) in zip(status_cols, env.items()):
        label, hint = labels[var]
        bg = "#f0fdf4" if ok else "#fef2f2"
        border = "#86efac" if ok else "#fca5a5"
        icon = "✅" if ok else "❌"
        col.markdown(f"""
        <div style="background:{bg};border:1px solid {border};border-radius:10px;padding:14px 16px;text-align:center">
          <div style="font-size:24px">{icon}</div>
          <div style="font-weight:600;font-size:14px;margin-top:6px">{label}</div>
          <div style="color:#64748b;font-size:12px;margin-top:2px">{"Configured" if ok else hint}</div>
        </div>""", unsafe_allow_html=True)

    if not _all_env_ok():
        st.info("👈 Open **Configure API Keys** in the sidebar to enter your credentials directly — no `.env` file needed.")

    st.markdown("---")

    # ── Setup instructions ─────────────────────────────────────────────────
    col_s1, col_s2 = st.columns(2)

    with col_s1:
        st.markdown("""
### Step 1 — ScrapingBee API Key
1. Sign up at [app.scrapingbee.com](https://app.scrapingbee.com) *(free trial available)*
2. Copy your API key from the dashboard homepage
3. Paste it into **🔑 Configure API Keys → ScrapingBee API Key** in the sidebar

---

### Step 2 — Google Service Account JSON
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. **IAM & Admin → Service Accounts → Create new**
3. Click **Keys → Add Key → JSON** — download the file
4. Enable **Google Sheets API** and **Google Drive API** for your project
5. Upload the downloaded JSON via **🔑 Configure API Keys → Google Service Account JSON**
""")

    with col_s2:
        st.markdown("""
### Step 3 — Google Sheet
1. Create a new Google Sheet
2. Add two tabs named exactly: `Catalog` and `Reports`
3. Row 1 of `Catalog` must have these headers:
   ```
   Product Internal Name | Platform Name | Platform URL | Active
   ```
4. Find the Sheet ID in the URL:
   `docs.google.com/spreadsheets/d/`**`← this part →`**`/edit`
5. Paste it into **🔑 Configure API Keys → Google Sheet ID** in the sidebar
6. Share the sheet with the service-account email *(ends in `@...gserviceaccount.com`)* as **Editor**

---

### Step 4 — Adding a new platform
Just add a row to `Catalog`. No code change needed.
*(Optional)* Add a parser in `parsers.py` for precise size/color data.
""")

    st.markdown("---")

    # ── Catalog example ────────────────────────────────────────────────────
    st.markdown("### Google Sheet `Catalog` tab — example rows")
    import pandas as pd
    st.dataframe(pd.DataFrame([
        {"Product Internal Name": "Knit Runner", "Platform Name": "Amazon",   "Platform URL": "https://amazon.in/dp/XXX",  "Active": "TRUE"},
        {"Product Internal Name": "Knit Runner", "Platform Name": "Flipkart", "Platform URL": "https://flipkart.com/...",  "Active": "TRUE"},
        {"Product Internal Name": "Knit Runner", "Platform Name": "Myntra",   "Platform URL": "https://myntra.com/...",    "Active": "TRUE"},
        {"Product Internal Name": "Hemp Runner", "Platform Name": "Amazon",   "Platform URL": "https://amazon.in/dp/YYY",  "Active": "TRUE"},
        {"Product Internal Name": "Hemp Runner", "Platform Name": "Nykaa",    "Platform URL": "https://nykaa.com/...",     "Active": "FALSE"},
    ]), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### Need to use a `.env` file instead?")
    st.code("""# neemans_monitor/.env
SCRAPINGBEE_API_KEY=your_scrapingbee_api_key_here
GOOGLE_SHEETS_CREDENTIALS_PATH=/absolute/path/to/service-account.json
GOOGLE_SHEET_ID=your_google_sheet_id_here
""", language="bash")
