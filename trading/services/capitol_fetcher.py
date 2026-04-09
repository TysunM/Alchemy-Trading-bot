"""
Capitol Trades Fetcher
Pulls politician stock trade disclosures from capitoltrades.com
using their public Next.js RSC (React Server Component) endpoint.

No API key required. Rate-limited to ~1 request/second.
Data source: STOCK Act mandatory disclosures (public government data).
"""

import re
import time

import requests

from trading.utils.database import log_event

CT_BASE_URL = "https://www.capitoltrades.com"
CT_PAGE_SIZE = 96
CT_HISTORY_PAGES = 15

_HEADERS = {
    "Accept": "text/x-component",
    "RSC": "1",
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


def fetch_recent_trades(pages: int = 1) -> list:
    trades = []
    for page in range(1, pages + 1):
        batch = _fetch_page(page)
        if not batch:
            break
        trades.extend(batch)
        if page < pages:
            time.sleep(1.2)
    return trades


def fetch_history_for_ranking(pages: int = CT_HISTORY_PAGES) -> list:
    log_event("capitol", f"Fetching {pages} pages of history (~{pages * CT_PAGE_SIZE} trades)...", "info")
    return fetch_recent_trades(pages=pages)


def _fetch_page(page: int, politician_id: str = None) -> list:
    params = {"pageSize": CT_PAGE_SIZE, "page": page, "sort": "-pubDate"}
    if politician_id:
        params["politician"] = politician_id

    try:
        resp = _SESSION.get(f"{CT_BASE_URL}/trades", params=params, timeout=20)
        resp.raise_for_status()
        return _parse_rsc_payload(resp.text)
    except requests.HTTPError as e:
        log_event("capitol", f"HTTP {e.response.status_code} on page {page}", "error")
        return []
    except Exception as e:
        log_event("capitol", f"Error fetching page {page}: {e}", "error")
        return []


def _parse_rsc_payload(text: str) -> list:
    trades = []
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
        re.DOTALL,
    )

    for m in pattern.finditer(text):
        (tx_id, chamber, company, ticker_raw, sector,
         first, last, pol_id, party,
         tx_date, tx_type, pub_date, gap) = m.groups()

        ticker = ticker_raw.split(":")[0].strip()

        trades.append({
            "txId": int(tx_id),
            "politicianId": pol_id,
            "politician": f"{first} {last}",
            "party": party,
            "chamber": chamber,
            "ticker": ticker,
            "companyName": company,
            "sector": sector,
            "txType": tx_type.lower(),
            "txDate": tx_date,
            "pubDate": pub_date,
            "reportingGap": int(gap),
        })

    return trades


def filter_new_trades(trades: list, seen_ids: set) -> list:
    return [t for t in trades if t["txId"] not in seen_ids]
