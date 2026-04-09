"""
Quant-Automata — Political Trade Mirror Bot
═══════════════════════════════════════════════════════════════

Flow
────
STARTUP  (runs once)
  1. Fetch ~15 pages of Capitol Trades history
  2. Score and rank all politicians by trade performance
  3. Identify top 5 politicians to follow

DAILY SCAN  (runs every morning + every 4 hours)
  1. Fetch latest Capitol Trades disclosures
  2. Find any new trades from top politicians
  3. Mirror those trades on Alpaca paper account
  4. Log results + print daily report

Run:
    pip install -r requirements.txt
    python main.py
"""

import json
import os
import time
import schedule
from datetime import datetime, timezone

from config import (
    TOP_N_POLITICIANS, SEEN_TRADES_PATH, DAILY_REPORT_PATH,
    TRADE_LOG_PATH,
)
from capitol_fetcher import (
    fetch_recent_trades, fetch_history_for_ranking,
    filter_new_trades,
)
from politician_ranker import rank_politicians, get_top_politicians, load_scores
from trade_mirror import process_new_trades
from execution.alpaca_broker import get_account, get_positions
from utils.notifier import notify_info, notify_error, notify_trade_opened


# ──────────────────────────────────────────────────────────────
# Persistent state
# ──────────────────────────────────────────────────────────────

def _load_seen_ids() -> set:
    if not os.path.exists(SEEN_TRADES_PATH):
        return set()
    with open(SEEN_TRADES_PATH) as f:
        return set(json.load(f))


def _save_seen_ids(ids: set):
    os.makedirs(os.path.dirname(SEEN_TRADES_PATH), exist_ok=True)
    with open(SEEN_TRADES_PATH, "w") as f:
        json.dump(list(ids), f)


def _log_mirrored_trades(trades: list):
    os.makedirs(os.path.dirname(TRADE_LOG_PATH), exist_ok=True)
    existing = []
    if os.path.exists(TRADE_LOG_PATH):
        with open(TRADE_LOG_PATH) as f:
            existing = json.load(f)
    existing.extend(trades)
    with open(TRADE_LOG_PATH, "w") as f:
        json.dump(existing, f, indent=2, default=str)


# ──────────────────────────────────────────────────────────────
# Startup — build politician rankings
# ──────────────────────────────────────────────────────────────

def build_rankings():
    """
    Fetch historical trades and rank politicians.
    Called once at startup (or if scores file is missing).
    """
    print(f"\n{'='*60}")
    print("  BUILDING POLITICIAN RANKINGS")
    print(f"{'='*60}")

    history = fetch_history_for_ranking()
    if not history:
        notify_error("Failed to fetch trade history for ranking.")
        return

    notify_info(f"Fetched {len(history)} historical trades for analysis.")
    scores = rank_politicians(history)

    print(f"\nTop {TOP_N_POLITICIANS} politicians to follow:")
    for s in scores[:TOP_N_POLITICIANS]:
        print(f"  #{scores.index(s)+1} {s['politician']:30s}  "
              f"score={s['score']:.3f}  win={s['win_rate']*100:.0f}%  "
              f"trades={s['evaluated']}/{s['total_trades']}")


# ──────────────────────────────────────────────────────────────
# Daily scan — check for new trades to mirror
# ──────────────────────────────────────────────────────────────

def daily_scan():
    """
    Fetch latest Capitol Trades disclosures and mirror new trades
    from top-ranked politicians.
    """
    print(f"\n[{_now()}] Running daily scan...")

    # ── Load top politicians ──────────────────────────────────
    top = get_top_politicians(TOP_N_POLITICIANS)
    if not top:
        notify_error("No politician scores — run build_rankings() first.")
        return

    top_ids = {p["politicianId"] for p in top}
    print(f"  Following: {', '.join(p['politician'] for p in top)}")

    # ── Fetch recent disclosures ──────────────────────────────
    recent_trades = fetch_recent_trades(pages=2)
    if not recent_trades:
        notify_error("Failed to fetch recent Capitol Trades data.")
        return

    print(f"  Fetched {len(recent_trades)} recent disclosures.")

    # ── Filter to truly new trades ────────────────────────────
    seen_ids   = _load_seen_ids()
    new_trades = filter_new_trades(recent_trades, seen_ids)

    print(f"  {len(new_trades)} new trade(s) not yet seen.")

    # Mark all fetched trades as seen (including non-mirrored ones)
    seen_ids.update(t["txId"] for t in recent_trades)
    _save_seen_ids(seen_ids)

    # ── Mirror top-politician trades ──────────────────────────
    if not new_trades:
        print("  No new trades to act on.")
        _print_daily_report(top, [])
        return

    executed = process_new_trades(new_trades, top_ids)

    if executed:
        notify_info(f"Mirrored {len(executed)} new political trade(s).")
        _log_mirrored_trades(executed)
        for e in executed:
            notify_trade_opened({
                "symbol":      e["ticker"],
                "direction":   e["txType"].upper(),
                "qty":         e["order"]["qty"],
                "entry_price": 0,   # filled at market
                "strategy":    "POLITICAL_MIRROR",
                "regime":      e["politician"],
                "confidence":  0,
                "sl":          e["order"].get("sl", 0),
                "tp":          e["order"].get("tp", 0),
            })
    else:
        print("  No top-politician trades to mirror this scan.")

    _print_daily_report(top, executed)


# ──────────────────────────────────────────────────────────────
# Daily report
# ──────────────────────────────────────────────────────────────

def _print_daily_report(top_politicians: list, executed: list):
    try:
        acct      = get_account()
        positions = get_positions()
    except Exception:
        acct      = {}
        positions = []

    lines = [
        f"\n{'─'*60}",
        f"  DAILY REPORT — {_now()}",
        f"{'─'*60}",
        f"  Account equity:   ${acct.get('equity', 0):,.2f}",
        f"  Buying power:     ${acct.get('buying_power', 0):,.2f}",
        f"  Open positions:   {len(positions)}",
        "",
        "  TOP POLITICIANS BEING FOLLOWED:",
    ]
    for i, p in enumerate(top_politicians[:5], 1):
        lines.append(f"    #{i} {p['politician']:28s}  "
                     f"score={p['score']:.3f}  win={p['win_rate']*100:.0f}%")

    lines.append("")
    if executed:
        lines.append(f"  TRADES MIRRORED THIS SCAN: {len(executed)}")
        for e in executed:
            lines.append(f"    {e['txType'].upper()} {e['ticker']:6s}  "
                         f"({e['politician']})")
    else:
        lines.append("  No trades mirrored this scan.")

    if positions:
        lines.append("")
        lines.append("  OPEN POSITIONS:")
        for p in positions:
            lines.append(f"    {p['symbol']:6s}  qty={p['qty']:.0f}  "
                         f"P&L=${p['unrealized_pl']:+.2f}")

    lines.append(f"{'─'*60}\n")
    report = "\n".join(lines)
    print(report)

    os.makedirs(os.path.dirname(DAILY_REPORT_PATH), exist_ok=True)
    with open(DAILY_REPORT_PATH, "a") as f:
        f.write(report + "\n")


# ──────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def main():
    notify_info("Political Trade Mirror Bot starting up...")

    from politician_ranker import load_scores
    import config

    # Build rankings on startup if no saved scores
    if not load_scores():
        build_rankings()
    else:
        scores = load_scores()
        print(f"[Startup] Loaded {len(scores)} saved politician scores.")
        print(f"  Top 5: {', '.join(s['politician'] for s in scores[:5])}")

    # Run immediately, then on schedule
    daily_scan()

    # Scan every 4 hours (disclosures come in bursts throughout the day)
    schedule.every(4).hours.do(daily_scan)

    # Rebuild rankings every Sunday at midnight to incorporate new data
    schedule.every().sunday.at("00:00").do(build_rankings)

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
