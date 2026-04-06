# Neeman's Listing Health Monitor

A Python tool that reads Neeman's product listings from a Google Sheet, scrapes each URL via ScrapingBee, and produces a structured health report — in the terminal and written back to the same sheet.

---

## Quick Start

```bash
cd neemans_monitor
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # fill in your keys
python monitor.py --all
```

---

## Prerequisites

### 1. Python 3.11+

### 2. ScrapingBee account
1. Sign up at [https://app.scrapingbee.com](https://app.scrapingbee.com)
2. Copy your **API key** from the dashboard
3. Set it in `.env`:
   ```
   SCRAPINGBEE_API_KEY=your_key_here
   ```

### 3. Google Sheets service account
1. Go to [Google Cloud Console](https://console.cloud.google.com/) → **IAM & Admin → Service Accounts**
2. Create a new service account (name it anything, e.g. `neemans-monitor`)
3. Click **Keys → Add Key → Create new key → JSON** — download the file
4. Enable the **Google Sheets API** and **Google Drive API** for your project
5. Open your Google Sheet → **Share** → paste the service account email (ends in `@...iam.gserviceaccount.com`) → give it **Editor** access
6. Set the path in `.env`:
   ```
   GOOGLE_SHEETS_CREDENTIALS_PATH=/absolute/path/to/service-account.json
   ```

### 4. Google Sheet ID
The ID is the long string in the URL:
```
https://docs.google.com/spreadsheets/d/THIS_IS_THE_ID/edit
```
Set it in `.env`:
```
GOOGLE_SHEET_ID=your_sheet_id_here
```

---

## Google Sheet Structure

### "Catalog" tab (you manage this)

| Product Internal Name | Platform Name | Platform URL | Active |
|-----------------------|---------------|--------------|--------|
| Knit Runner | Amazon | https://amazon.in/dp/XXX | TRUE |
| Knit Runner | Flipkart | https://flipkart.com/... | TRUE |
| Knit Runner | Myntra | https://myntra.com/... | TRUE |
| Hemp Runner | Amazon | https://amazon.in/dp/YYY | TRUE |
| Hemp Runner | Nykaa | https://nykaa.com/... | TRUE |

- **Active = FALSE** → row is skipped
- Platform Name is free text — domain auto-detection picks the right parser
- Add any number of rows; no code changes needed for new platforms

### "Reports" tab (auto-created by the script)

Written on every run:
`Run Timestamp | Product Name | Platform | Price | Buy Box | Sizes Available | Colors Available | Flags | Status`

---

## CLI Usage

```bash
# Scrape everything active
python monitor.py --all

# Scrape one product across all its platforms
python monitor.py --product "Knit Runner"

# Scrape all products on one platform
python monitor.py --platform "Myntra"

# Preview what would be scraped — no API calls
python monitor.py --dry-run
```

---

## Adding a New Platform

### Automatic (zero code)
Just add a row to the **Catalog** sheet with the new platform URL.
The generic fallback parser handles price detection and buy-box detection automatically.
Sizes and colors will show as "Could not parse".

### With precise size/color extraction (recommended)
1. Open `parsers.py`
2. Write a new function following this template:
   ```python
   def parse_mynewsite_com(soup: BeautifulSoup) -> dict:
       result = _empty_result()
       try:
           price_tag = soup.select_one("span.price")
           result["price"] = _clean_price(_text(price_tag))
           result["buy_box"] = bool(soup.select_one("button.add-to-cart"))
           result["sizes"] = [_text(el) for el in soup.select("ul.sizes li")]
           result["colors"] = [_text(el) for el in soup.select("ul.colors li")]
           result["error"] = None
       except Exception as exc:
           result["error"] = f"mynewsite parser error: {exc}"
       return result
   ```
3. Register it at the bottom of `parsers.py` in `PARSER_REGISTRY`:
   ```python
   "mynewsite.com": parse_mynewsite_com,
   "www.mynewsite.com": parse_mynewsite_com,
   ```
4. Add rows to the Catalog sheet. Done.

---

## Flag Logic

| Flag | Trigger |
|------|---------|
| **PRICE GAP** | Any platform price differs by more than ₹50 |
| **NOT PURCHASABLE** | Buy box is missing/unavailable on a platform |
| **MISSING SIZES** | A platform is missing sizes present on other platforms |
| **MISSING COLORS** | A platform is missing colors present on other platforms |
| **PARSE ERROR / FETCH ERROR** | Scraping or parsing failed for a platform |

### Status
| Status | Condition |
|--------|-----------|
| 🟢 GREEN | No flags |
| 🟡 YELLOW | 1–2 flags, no critical issues |
| 🔴 RED | 3+ flags, or buy box missing, or parse/fetch error |

---

## Project Structure

```
neemans_monitor/
├── monitor.py        # Main entry point + CLI
├── parsers.py        # Platform-specific HTML parsers
├── sheets.py         # Google Sheets read/write
├── report.py         # Rich terminal output
├── requirements.txt
├── .env.example
└── README.md
```

---

## Supported Platforms (built-in parsers)

| Platform | Domain |
|----------|--------|
| Amazon India | amazon.in |
| Flipkart | flipkart.com |
| Myntra | myntra.com |
| Nykaa / Nykaa Fashion | nykaa.com, nykaafashion.com |
| Tata CLiQ | tatacliq.com |
| Neemans.com | neemans.com |
| Any other | Generic fallback (price + buy-box only) |
