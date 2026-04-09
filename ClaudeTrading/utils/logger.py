"""
Trade Logger
Persists every completed trade as a JSON record.
Also provides loading utilities used by the Feedback Analyzer.

Trade schema
────────────
{
    "id":           str,    unique trade ID
    "symbol":       str,
    "strategy":     str,    "A", "B", or "C"
    "regime":       str,    "TRENDING" | "RANGE_BOUND" | "HIGH_VOL"
    "direction":    str,    "BUY" | "SELL"
    "entry_price":  float,
    "exit_price":   float,
    "qty":          int,
    "sl":           float,
    "tp":           float,
    "entry_time":   str,    ISO format
    "exit_time":    str,    ISO format
    "candles_held": int,    bars between entry and exit
    "exit_reason":  str,    "TP_HIT" | "SL_HIT" | "MANUAL" | "KILL_SWITCH"
    "pnl":          float,  gross P&L in USD
    "pnl_pct":      float,  P&L as fraction of entry value
    "confidence":   float,  signal confidence at entry (0–1)
}
"""

import json
import os
import uuid
from datetime import datetime, timezone
from config import TRADE_LOG_PATH


def log_trade(trade: dict):
    """Append a completed trade record to the trade log JSON file."""
    os.makedirs(os.path.dirname(TRADE_LOG_PATH), exist_ok=True)

    if "id" not in trade:
        trade["id"] = str(uuid.uuid4())[:8]

    trades = load_trades()
    trades.append(trade)

    with open(TRADE_LOG_PATH, "w") as f:
        json.dump(trades, f, indent=2, default=str)

    print(f"[Logger] Trade {trade['id']} logged — "
          f"{trade.get('symbol')} {trade.get('direction')} "
          f"P&L: ${trade.get('pnl', 0):.2f}")


def load_trades(last_n: int = None) -> list:
    """Load all (or last N) trade records from the log file."""
    if not os.path.exists(TRADE_LOG_PATH):
        return []
    with open(TRADE_LOG_PATH) as f:
        trades = json.load(f)
    if last_n:
        return trades[-last_n:]
    return trades


def build_open_trade_record(symbol: str, strategy: str, regime: str,
                             direction: str, entry_price: float,
                             qty: int, sl: float, tp: float,
                             confidence: float, order_id: str) -> dict:
    """Create a pending trade record (fill in exit fields when trade closes)."""
    return {
        "id":          order_id[:8],
        "order_id":    order_id,
        "symbol":      symbol,
        "strategy":    strategy,
        "regime":      regime,
        "direction":   direction,
        "entry_price": entry_price,
        "exit_price":  None,
        "qty":         qty,
        "sl":          sl,
        "tp":          tp,
        "entry_time":  datetime.now(timezone.utc).isoformat(),
        "exit_time":   None,
        "candles_held":None,
        "exit_reason": None,
        "pnl":         None,
        "pnl_pct":     None,
        "confidence":  confidence,
    }


def finalize_trade(trade: dict, exit_price: float, exit_reason: str,
                   candles_held: int = None) -> dict:
    """Fill in exit fields and calculate P&L for a closed trade."""
    trade = trade.copy()
    trade["exit_price"]   = exit_price
    trade["exit_time"]    = datetime.now(timezone.utc).isoformat()
    trade["exit_reason"]  = exit_reason
    trade["candles_held"] = candles_held

    qty = trade.get("qty", 0)
    direction = trade.get("direction", "BUY")

    if direction == "BUY":
        raw_pnl = (exit_price - trade["entry_price"]) * qty
    else:
        raw_pnl = (trade["entry_price"] - exit_price) * qty

    trade["pnl"]     = round(raw_pnl, 2)
    trade["pnl_pct"] = round(raw_pnl / (trade["entry_price"] * qty), 5) if qty > 0 else 0

    return trade
