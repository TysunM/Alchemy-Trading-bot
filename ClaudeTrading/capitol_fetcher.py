"""
Capitol Trades Fetcher
Pulls politician stock trade disclosures from capitoltrades.com
using their public Next.js RSC (React Server Component) endpoint.

No API key required. Rate-limited to ~1 request/second.
Data source: STOCK Act mandatory disclosures (public government data).

Trade record fields returned:
  txId, politician, politicianId, party, chamber,
  ticker, companyName, sector,
  txType (buy/sell), txDate, pubDate, reportingGap (days)
"""

import re
import json
import time
import requests
from datetime import datetime, timezone
from config import CT_BASE_URL, CT_PAGE_SIZE, CT_HISTORY_PAGES

# ──────────────────────────────────────────────────────────────
# Request setup
# ──────────────────────────────────────────────────────────────

_HEADERS = {
    "Accept":           "text/x-component",
    "RSC":              "1",
    "Next-Router-State-Tree": (
        "%5B%22%22%2C%7B%22children%22%3A%5B%22(public)%22%2C%7B%22children%22%3A"
        "%5B%22trades%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%5D%7D%5D%7D"
        "%5D%7D%2Cnull%2Cnull%2Ctrue%5D"
    ),
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer": f"{CT_BASE_URL}/trades",
}

_SESSION = requests.Session()
_SESSION.headers.update(_HEADERS)


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

def fetch_recent_trades(pages: int = 1) -> list:
    """
    Fetch the most recent N pages of political trade disclosures.
    Returns list of normalized trade dicts sorted newest-first.
    """
    trades = []
    for page in range(1, pages + 1):
        batch = _fetch_page(page)
        if not batch:
            break
        trades.extend(batch)
        if page < pages:
            time.sleep(1.2)   # Polite rate limiting

    return trades


def fetch_politician_history(politician_id: str, pages: int = 5) -> list:
    """Fetch all trades for a specific politician."""
    trades = []
    for page in range(1, pages + 1):
        batch = _fetch_page(page, politician_id=politician_id)
        if not batch:
            break
        trades.extend(batch)
        if page < pages:
            time.sleep(1.2)
    return trades


def fetch_history_for_ranking(pages: int = CT_HISTORY_PAGES) -> list:
    """
    Fetch enough historical pages to build politician performance scores.
    Called once at startup (or once per day to refresh).
    """
    print(f"[CapitolFetcher] Fetching {pages} pages of history "
          f"(~{pages * CT_PAGE_SIZE} trades)...")
    return fetch_recent_trades(pages=pages)


# ──────────────────────────────────────────────────────────────
# Internal
# ──────────────────────────────────────────────────────────────

def _fetch_page(page: int, politician_id: str = None) -> list:
    """Fetch one page of trades from the Capitol Trades RSC endpoint."""
    params = {"pageSize": CT_PAGE_SIZE, "page": page, "sort": "-pubDate"}
    if politician_id:
        params["politician"] = politician_id

    try:
        resp = _SESSION.get(
            f"{CT_BASE_URL}/trades",
            params=params,
            timeout=20,
        )
        resp.raise_for_status()
        return _parse_rsc_payload(resp.text)

    except requests.HTTPError as e:
        print(f"[CapitolFetcher] HTTP {e.response.status_code} on page {page}")
        return []
    except Exception as e:
        print(f"[CapitolFetcher] Error fetching page {page}: {e}")
        return []


def _parse_rsc_payload(text: str) -> list:
    """
    Parse the Next.js RSC (React Server Component) text payload.
    The RSC format embeds JSON data inline in a streaming text format.
    We extract trade objects by locating the _txId anchor.
    """
    trades = []

    # Each trade object starts with "_txId" — extract everything from there
    # through the end of the encompassing JSON object
    pattern = re.compile(
        r'"_txId"\s*:\s*(\d+)\s*,'
        r'.*?"chamber"\s*:\s*"([^"]+)"'
        r'.*?"issuerName"\s*:\s*"([^"]+)"'
        r'.*?"issuerTicker"\s*:\s*"([^"]+)"'
        r'.*?"sector"\s*:\s*"([^"]*)"'
        r'.*?"firstName"\s*:\s*"([^"]+)"'
        r'.*?"lastName"\s*:\s*"([^"]+)"'
        r'.*?"_politicianId"\s*:\s*"([^"]+)"'
        r'.*?"party"\s*:\s*"([^"]*)"'
        r'.*?"txDate"\s*:\s*"([^"]+)"'
        r'.*?"txType"\s*:\s*"([^"]+)"'
        r'.*?"pubDate"\s*:\s*"([^"]+)"'
        r'.*?"reportingGap"\s*:\s*(\d+)',
        re.DOTALL
    )

    for m in pattern.finditer(text):
        (tx_id, chamber, company, ticker_raw, sector,
         first, last, pol_id, party,
         tx_date, tx_type, pub_date, gap) = m.groups()

        # Normalize ticker: "AAPL:US" → "AAPL"
        ticker = ticker_raw.split(":")[0].strip()

        trade = {
            "txId":           int(tx_id),
            "politicianId":   pol_id,
            "politician":     f"{first} {last}",
            "party":          party,
            "chamber":        chamber,
            "ticker":         ticker,
            "companyName":    company,
            "sector":         sector,
            "txType":         tx_type.lower(),       # "buy" or "sell"
            "txDate":         tx_date,
            "pubDate":        pub_date,
            "reportingGap":   int(gap),
        }
        trades.append(trade)

    return trades


def get_latest_pub_date(trades: list) -> str | None:
    """Return the most recent publication date from a list of trades."""
    dates = [t["pubDate"] for t in trades if t.get("pubDate")]
    return max(dates) if dates else None


def filter_new_trades(trades: list, seen_ids: set) -> list:
    """Return only trades not in seen_ids set."""
    return [t for t in trades if t["txId"] not in seen_ids]
