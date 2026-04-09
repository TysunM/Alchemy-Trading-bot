"""
Trade Mirror
Takes a Capitol Trades disclosure from a top-ranked politician and
executes the same trade on the Alpaca paper account.

SAFETY GUARANTEES (critical for live trading)
──────────────────────────────────────────────
1. Idempotency lock  — every txId is written to a JSON ledger BEFORE the order
   is placed. If the process crashes mid-execution and restarts, the txId is
   already locked so the order never fires twice.

2. Open-order dedup  — before placing any order, Alpaca is queried for existing
   open orders on the same symbol. Duplicate blocked at the broker level too.

3. Position dedup    — blocked if we already hold the symbol in the same
   direction.

4. Atomic lock/execute — lock → verify → execute → confirm. Any failure at
   any step leaves the lock in place so we never retry blindly.

5. No shell fallbacks — order placement code never uses try/except to retry
   the same order. Failures return None, logged, never silently re-fired.
"""

import json
import os
import re
import time
import requests
from datetime import datetime, timedelta, timezone

from config import (
    ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_DATA_URL,
    MAX_POSITION_SIZE_PCT, MIRROR_STOP_LOSS_PCT, MIRROR_TAKE_PROFIT_PCT,
    MAX_OPEN_POSITIONS, SKIP_IF_DISCLOSED_DAYS, SEEN_TRADES_PATH,
)
from execution.alpaca_broker import (
    get_equity, get_positions, place_bracket_order,
    is_market_open, get_position, get_open_orders, close_position,
)


# ──────────────────────────────────────────────────────────────
# Idempotency ledger
# Tracks every txId we have ATTEMPTED to act on.
# Written BEFORE the order fires — survives crashes.
# ──────────────────────────────────────────────────────────────

def _load_seen_ids() -> set:
    if not os.path.exists(SEEN_TRADES_PATH):
        return set()
    with open(SEEN_TRADES_PATH) as f:
        return set(json.load(f))


def _lock_trade_id(tx_id: int):
    """
    Persist txId to the seen-trades ledger immediately.
    Called BEFORE order placement — guarantees no retry even on crash.
    """
    seen = _load_seen_ids()
    seen.add(tx_id)
    os.makedirs(os.path.dirname(SEEN_TRADES_PATH), exist_ok=True)
    with open(SEEN_TRADES_PATH, "w") as f:
        json.dump(list(seen), f)


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

def mirror_trade(trade: dict) -> dict | None:
    """
    Attempt to mirror a single politician trade on Alpaca.
    Returns order result dict, or None if skipped/blocked.

    Safety order of operations:
      1. Pre-flight checks (ticker, freshness, position limits)
      2. LOCK the txId in the seen-trades ledger  ← before any money moves
      3. Broker-level dedup (open order check)
      4. Price fetch
      5. Single order placement — no retries, no fallbacks
      6. Confirm order ID returned before logging success
    """
    ticker  = trade["ticker"]
    tx_type = trade["txType"]
    tx_id   = trade["txId"]

    # ── Step 1: Pre-flight checks ─────────────────────────────
    skip_reason = _should_skip(trade)
    if skip_reason:
        print(f"  [Mirror] SKIP {ticker} ({trade['politician']}): {skip_reason}")
        return None

    if not is_market_open():
        print(f"  [Mirror] Market closed — {ticker} will not be queued (day order risk).")
        return None

    # ── Step 2: Lock txId BEFORE touching the broker ─────────
    # If we crash after this line, the trade won't retry on restart.
    _lock_trade_id(tx_id)

    # ── Step 3: Broker-level open-order dedup ─────────────────
    open_orders = get_open_orders(symbol=ticker)
    if open_orders:
        print(f"  [Mirror] BLOCKED — open order already exists for {ticker}. "
              f"Order IDs: {[o['order_id'] for o in open_orders]}")
        return None

    # ── Step 4: Price fetch — one attempt, no fallback retry ──
    price = _get_latest_price(ticker)
    if price is None or price <= 0:
        print(f"  [Mirror] Cannot get price for {ticker} — aborting (txId {tx_id} locked).")
        return None

    # ── Special case: politician sells a stock we hold long ───
    existing = get_position(ticker)
    if tx_type == "sell" and existing and existing["side"] == "long":
        print(f"  [Mirror] CLOSE long {ticker} — {trade['politician']} sold.")
        result = close_position(ticker)
        result["mirroring"]     = trade["politician"]
        result["source_tx_id"]  = tx_id
        result["action"]        = "closed_long_on_sell_signal"
        return result

    # ── Step 5: Position sizing ───────────────────────────────
    equity   = get_equity()
    notional = equity * MAX_POSITION_SIZE_PCT
    qty      = max(1, int(notional / price))

    # ── SL / TP ───────────────────────────────────────────────
    if tx_type == "buy":
        sl = round(price * (1 - MIRROR_STOP_LOSS_PCT),  2)
        tp = round(price * (1 + MIRROR_TAKE_PROFIT_PCT), 2)
    else:
        sl = round(price * (1 + MIRROR_STOP_LOSS_PCT),  2)
        tp = round(price * (1 - MIRROR_TAKE_PROFIT_PCT), 2)

    print(f"  [Mirror] {tx_type.upper()} {qty}x {ticker} @ ~${price:.2f} "
          f"| SL=${sl:.2f} TP=${tp:.2f} | {trade['politician']} ({trade['party']})")

    # ── Step 6: Single order placement — no retries ───────────
    try:
        order = place_bracket_order(
            symbol=ticker,
            qty=qty,
            side=tx_type.upper(),
            sl=sl,
            tp=tp,
        )
    except Exception as e:
        # Do NOT retry. txId is already locked. Log and return None.
        print(f"  [Mirror] ORDER FAILED for {ticker} (txId {tx_id} locked, no retry): {e}")
        return None

    # ── Step 7: Confirm order ID exists before declaring success
    if not order.get("order_id"):
        print(f"  [Mirror] WARNING — broker returned no order_id for {ticker}. "
              f"Check Alpaca dashboard manually. txId {tx_id} locked.")
        return None

    order["mirroring"]    = trade["politician"]
    order["source_tx_id"] = tx_id
    return order


def process_new_trades(new_trades: list, top_politician_ids: set) -> list:
    """
    Filter to top politicians, deduplicate against seen-trades ledger,
    then mirror each qualifying trade exactly once.
    """
    seen_ids = _load_seen_ids()
    executed = []

    for trade in new_trades:
        if trade["politicianId"] not in top_politician_ids:
            continue

        # Skip if already in ledger (covers restarts + duplicate scan cycles)
        if trade["txId"] in seen_ids:
            continue

        result = mirror_trade(trade)
        if result:
            executed.append({**trade, "order": result})
            # Refresh seen_ids after each lock so the next iteration is aware
            seen_ids = _load_seen_ids()
            time.sleep(0.5)

    return executed


# ──────────────────────────────────────────────────────────────
# Pre-flight checks
# ──────────────────────────────────────────────────────────────

def _should_skip(trade: dict) -> str | None:
    """Return a skip reason string, or None if safe to proceed."""
    ticker  = trade["ticker"]
    tx_type = trade["txType"]

    if not _is_valid_ticker(ticker):
        return f"Ticker '{ticker}' is not a valid US equity symbol"

    pub_date = _parse_date(trade["pubDate"])
    age_days = (datetime.now(timezone.utc) - pub_date).days
    if age_days > SKIP_IF_DISCLOSED_DAYS:
        return f"Disclosure is {age_days}d old (max {SKIP_IF_DISCLOSED_DAYS}d)"

    positions = get_positions()
    if len(positions) >= MAX_OPEN_POSITIONS:
        return f"Max open positions ({MAX_OPEN_POSITIONS}) reached"

    existing = get_position(ticker)
    if tx_type == "buy" and existing and existing["side"] == "long":
        return f"Already long {ticker}"
    if tx_type == "sell" and existing and existing["side"] == "short":
        return f"Already short {ticker}"

    return None


def _is_valid_ticker(ticker: str) -> bool:
    return bool(re.match(r'^[A-Z]{1,5}$', ticker))


# ──────────────────────────────────────────────────────────────
# Price fetch  (snapshot only — single call, no retry loop)
# ──────────────────────────────────────────────────────────────

def _get_latest_price(ticker: str) -> float | None:
    """
    Fetch latest trade price from Alpaca snapshot endpoint.
    One attempt. Returns None on any failure — caller decides what to do.
    """
    headers = {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }
    try:
        resp = requests.get(
            f"{ALPACA_DATA_URL}/v2/stocks/{ticker}/snapshot",
            headers=headers,
            timeout=8,
        )
        resp.raise_for_status()
        price = float(resp.json().get("latestTrade", {}).get("p", 0))
        return price if price > 0 else None
    except Exception as e:
        print(f"  [Mirror] Price fetch failed for {ticker}: {e}")
        return None


def _parse_date(date_str: str) -> datetime:
    if "T" in date_str:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    else:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
