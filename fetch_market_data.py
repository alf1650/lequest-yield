#!/usr/bin/env python3
"""Fetch Le Quest 2-bed/2-bath market data from URA (data.gov.sg) and write data.json.

Data source: URA Private Residential Property Transactions (data.gov.sg CKAN API)
Filters:     Project "LE QUEST", floor area 550–850 sqft (2-bedroom range)
Output:      data.json — loaded by index.html to show market context

Runs weekly via GitHub Actions. Uses stdlib only — no dependencies to install.
"""
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone, date
from pathlib import Path

# ── CONFIG ──────────────────────────────────────────────────────────────
PROJECT_NAME = "LE QUEST"

# Le Quest 2-bedroom units: ~592–807 sqft
BEDS2_SQFT_MIN = 550
BEDS2_SQFT_MAX = 850

# How many recent months to include in the transactions list
RECENT_MONTHS = 24

# How many transactions to keep in the output JSON
MAX_TRANSACTIONS = 20

# data.gov.sg URA Private Residential Property Transactions
# Dataset: https://data.gov.sg/datasets/d_ebc5ab87086db484f88045b47411ebc
URA_RESOURCE_ID = "d_ebc5ab87086db484f88045b47411ebc"
URA_API_BASE = "https://data.gov.sg/api/action/datastore_search"

OUT_PATH = Path(__file__).parent / "data.json"

# ── HELPERS ─────────────────────────────────────────────────────────────
def fetch_json(url: str) -> dict:
    for attempt in range(3):
        if attempt > 0:
            wait = attempt * 15
            print(f"  Rate limited — retrying in {wait}s …", flush=True)
            import time; time.sleep(wait)
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "lequest-yield-updater/1.0",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                # data.gov.sg returns rate-limit errors as 200 JSON with code=24
                if isinstance(data, dict) and data.get("code") == 24:
                    print(f"  Rate limit (attempt {attempt+1}): {data.get('errorMsg', '')}", flush=True)
                    if attempt == 2:
                        raise RuntimeError("Rate limit exceeded after 3 attempts")
                    continue
                return data
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"  HTTP 429 (attempt {attempt+1})", flush=True)
                if attempt == 2:
                    raise
                continue
            raise
    raise RuntimeError("fetch_json failed")


def get_field(record: dict, *candidates) -> str | None:
    """Return the first matching field value from a record (case-insensitive)."""
    lower_map = {k.lower(): v for k, v in record.items()}
    for name in candidates:
        v = lower_map.get(name.lower())
        if v is not None:
            return str(v).strip()
    return None


def parse_date(raw: str) -> date | None:
    """Parse URA date strings like 'Jan 2026', '2026-01', '01-2026'."""
    if not raw:
        return None
    raw = raw.strip()
    # Try "MMM YYYY" → "Jan 2026"
    for fmt in ("%b %Y", "%B %Y", "%Y-%m", "%m-%Y", "%m/%Y", "%Y/%m"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.date().replace(day=1)
        except ValueError:
            pass
    return None


def fmt_month(d: date) -> str:
    return d.strftime("%b %Y")


def fmt_sgd(n: float) -> str:
    return f"S${round(n):,}"


# ── FETCH ALL RECORDS ────────────────────────────────────────────────────
def fetch_all_records(resource_id: str, project: str) -> list[dict]:
    """Page through the CKAN API and return all records for the project."""
    records = []
    limit = 100
    offset = 0
    total = None

    while True:
        params = urllib.parse.urlencode({
            "resource_id": resource_id,
            "q": project,
            "limit": limit,
            "offset": offset,
        })
        url = f"{URA_API_BASE}?{params}"
        print(f"  Fetching offset={offset} …", flush=True)
        data = fetch_json(url)

        if not data.get("success"):
            print(f"  API error: {data.get('error')}", file=sys.stderr)
            break

        result = data["result"]
        batch = result.get("records", [])
        records.extend(batch)

        if total is None:
            total = result.get("total", 0)
            print(f"  Total records for '{project}': {total}")

        # Print column names on first batch
        if offset == 0 and batch:
            print(f"  Columns: {list(batch[0].keys())}")

        offset += limit
        if offset >= total or not batch:
            break

    return records


# ── PROCESS ─────────────────────────────────────────────────────────────
def process(records: list[dict]) -> dict:
    today = date.today()
    cutoff = date(today.year - RECENT_MONTHS // 12, today.month, 1)

    txns = []
    for rec in records:
        # Normalise project name check (in case API returns partial matches)
        proj = get_field(rec, "Project Name", "project", "project_name", "PROJECT NAME")
        if not proj or PROJECT_NAME.lower() not in proj.lower():
            continue

        # Floor area
        area_raw = get_field(rec, "Area (Sqft)", "area", "floor_area_sqft", "AREA (SQFT)")
        try:
            area_sqft = float(area_raw) if area_raw else 0
        except ValueError:
            area_sqft = 0

        # Filter for 2-bedroom range
        if not (BEDS2_SQFT_MIN <= area_sqft <= BEDS2_SQFT_MAX):
            continue

        # Price
        price_raw = get_field(rec, "Price ($)", "price", "transacted_price", "PRICE ($)")
        try:
            price = float(str(price_raw).replace(",", "")) if price_raw else 0
        except ValueError:
            price = 0

        # PSF
        psf_raw = get_field(rec, "Unit Price ($ PSF)", "unit_price_psf", "psf", "UNIT PRICE ($ PSF)")
        try:
            psf = float(str(psf_raw).replace(",", "")) if psf_raw else (price / area_sqft if area_sqft else 0)
        except ValueError:
            psf = price / area_sqft if area_sqft else 0

        # Date
        date_raw = get_field(rec, "Date of Sale", "sale_date", "contract_date", "DATE OF SALE", "Contract Date")
        txn_date = parse_date(date_raw) if date_raw else None

        # Type of sale
        sale_type = get_field(rec, "Type of Sale", "type_of_sale", "TYPE OF SALE") or ""

        # Floor level
        floor = get_field(rec, "Floor Level", "floor_level", "FLOOR LEVEL") or ""

        if price > 0 and area_sqft > 0:
            txns.append({
                "date": fmt_month(txn_date) if txn_date else date_raw or "",
                "date_sort": txn_date.isoformat() if txn_date else "0000-01-01",
                "price": round(price),
                "psf": round(psf),
                "area_sqft": round(area_sqft),
                "type": sale_type,
                "floor": floor,
            })

    # Sort newest first
    txns.sort(key=lambda t: t["date_sort"], reverse=True)

    # Filter to recent months
    recent = [
        t for t in txns
        if t["date_sort"] >= cutoff.isoformat()
    ]

    # Stats over recent period
    stats: dict = {}
    if recent:
        prices = [t["price"] for t in recent]
        psfs = [t["psf"] for t in recent]
        stats = {
            "count": len(recent),
            "avg_price": round(sum(prices) / len(prices)),
            "min_price": min(prices),
            "max_price": max(prices),
            "avg_psf": round(sum(psfs) / len(psfs)),
            "min_psf": min(psfs),
            "max_psf": max(psfs),
        }

    # Last transacted (most recent overall)
    last = txns[0] if txns else None

    return {
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
        "project": PROJECT_NAME,
        "filter": {
            "bedrooms": 2,
            "area_sqft_min": BEDS2_SQFT_MIN,
            "area_sqft_max": BEDS2_SQFT_MAX,
            "months_window": RECENT_MONTHS,
        },
        "lastTransacted": {
            "date": last["date"] if last else None,
            "price": last["price"] if last else None,
            "psf": last["psf"] if last else None,
            "area_sqft": last["area_sqft"] if last else None,
            "type": last["type"] if last else None,
        } if last else None,
        "stats": stats,
        "transactions": txns[:MAX_TRANSACTIONS],
    }


# ── MAIN ─────────────────────────────────────────────────────────────────
def main():
    print(f"Fetching URA transactions for '{PROJECT_NAME}' …")
    records = fetch_all_records(URA_RESOURCE_ID, PROJECT_NAME)
    print(f"Total raw records: {len(records)}")

    result = process(records)

    n_txns = len(result["transactions"])
    n_recent = result["stats"].get("count", 0) if result["stats"] else 0
    print(f"\n2BR transactions found: {n_txns} total, {n_recent} in last {RECENT_MONTHS} months")

    if result["lastTransacted"]:
        lt = result["lastTransacted"]
        print(f"Last transacted: {lt['date']}  {fmt_sgd(lt['price'])}  ({lt['psf']} psf)  {lt['area_sqft']} sqft")

    if result["stats"]:
        s = result["stats"]
        print(f"Avg psf ({RECENT_MONTHS}m): {s['avg_psf']}  range: {s['min_psf']}–{s['max_psf']}")

    OUT_PATH.write_text(json.dumps(result, indent=2))
    print(f"\nWrote {OUT_PATH}")


if __name__ == "__main__":
    main()
