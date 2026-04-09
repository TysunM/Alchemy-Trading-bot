"""
Agent Memory — Gives Claude access to its past reasoning and trade outcomes.

Retrieves historical decisions, trade results, and performance patterns from
the SQLite database so Claude can learn from its own history and avoid
repeating mistakes.
"""

import json
from datetime import datetime, timedelta
from typing import Optional

from trading.utils.database import SessionLocal, TradeLog, ReasoningLedger, SystemEvent


def recall_decisions(symbol: Optional[str] = None, limit: int = 15, days: int = 30) -> dict:
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)

        q = db.query(ReasoningLedger).filter(ReasoningLedger.timestamp >= cutoff)
        if symbol:
            q = q.filter(ReasoningLedger.symbol == symbol.upper())
        entries = q.order_by(ReasoningLedger.timestamp.desc()).limit(limit).all()

        decisions = []
        for e in entries:
            decisions.append({
                "timestamp": e.timestamp.strftime("%Y-%m-%d %H:%M"),
                "symbol": e.symbol,
                "action": e.action,
                "signal_type": e.signal_type or "unknown",
                "confidence": e.confidence or 0,
                "reasoning_excerpt": (e.reasoning or "")[:300],
                "outcome": e.outcome or "pending",
            })

        return {
            "total_found": len(decisions),
            "filter_symbol": symbol,
            "lookback_days": days,
            "decisions": decisions,
        }
    finally:
        db.close()


def recall_trades(symbol: Optional[str] = None, limit: int = 20, days: int = 30) -> dict:
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)

        q = db.query(TradeLog).filter(TradeLog.timestamp >= cutoff)
        if symbol:
            q = q.filter(TradeLog.symbol == symbol.upper())
        trades = q.order_by(TradeLog.timestamp.desc()).limit(limit).all()

        trade_list = []
        total_pnl = 0.0
        wins = 0
        losses = 0
        for t in trades:
            pnl = t.pnl or 0.0
            total_pnl += pnl
            if pnl > 0:
                wins += 1
            elif pnl < 0:
                losses += 1
            trade_list.append({
                "timestamp": t.timestamp.strftime("%Y-%m-%d %H:%M"),
                "symbol": t.symbol,
                "side": t.side,
                "qty": t.qty,
                "price": t.price,
                "status": t.status,
                "pnl": pnl,
                "notes": (t.notes or "")[:100],
            })

        win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0

        return {
            "total_found": len(trade_list),
            "filter_symbol": symbol,
            "lookback_days": days,
            "summary": {
                "total_pnl": round(total_pnl, 2),
                "wins": wins,
                "losses": losses,
                "win_rate": round(win_rate, 1),
            },
            "trades": trade_list,
        }
    finally:
        db.close()


def get_symbol_track_record(symbol: str) -> dict:
    db = SessionLocal()
    try:
        trades = db.query(TradeLog).filter(TradeLog.symbol == symbol.upper()).order_by(TradeLog.timestamp.desc()).limit(20).all()
        reasoning = db.query(ReasoningLedger).filter(ReasoningLedger.symbol == symbol.upper()).order_by(ReasoningLedger.timestamp.desc()).limit(10).all()

        trade_pnls = [t.pnl for t in trades if t.pnl is not None]
        total_pnl = sum(trade_pnls) if trade_pnls else 0
        wins = sum(1 for p in trade_pnls if p > 0)
        losses = sum(1 for p in trade_pnls if p < 0)

        last_actions = []
        for r in reasoning[:5]:
            last_actions.append({
                "date": r.timestamp.strftime("%Y-%m-%d"),
                "action": r.action,
                "confidence": r.confidence or 0,
                "signal": r.signal_type or "unknown",
                "thought": (r.reasoning or "")[:150],
            })

        return {
            "symbol": symbol.upper(),
            "total_trades": len(trades),
            "total_pnl": round(total_pnl, 2),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0,
            "recent_reasoning": last_actions,
            "lesson": _derive_lesson(symbol, trade_pnls, last_actions),
        }
    finally:
        db.close()


def _derive_lesson(symbol: str, pnls: list, actions: list) -> str:
    if not pnls and not actions:
        return f"No prior history with {symbol}. This is a fresh analysis."

    if not pnls:
        return f"Analyzed {symbol} before but no trades executed. Review past reasoning for patterns."

    win_rate = sum(1 for p in pnls if p > 0) / len(pnls) * 100 if pnls else 0
    avg_pnl = sum(pnls) / len(pnls) if pnls else 0

    if win_rate >= 70:
        return f"Strong track record with {symbol} ({win_rate:.0f}% win rate, avg P&L ${avg_pnl:.2f}). Strategy is working — stay consistent."
    elif win_rate >= 50:
        return f"Mixed results with {symbol} ({win_rate:.0f}% win rate, avg P&L ${avg_pnl:.2f}). Review what differentiates wins from losses."
    elif win_rate > 0:
        return f"Poor track record with {symbol} ({win_rate:.0f}% win rate, avg P&L ${avg_pnl:.2f}). Consider changing approach or reducing size."
    else:
        return f"All trades on {symbol} were losers (avg P&L ${avg_pnl:.2f}). Strongly reconsider strategy before re-entering."


def build_memory_context(watchlist: list[str], max_tokens: int = 2000) -> str:
    lines = ["## AGENT MEMORY — Past Decisions & Outcomes"]

    recent = recall_trades(limit=10, days=14)
    if recent["trades"]:
        lines.append(f"\n### Recent Trade Performance (14d)")
        lines.append(f"P&L: ${recent['summary']['total_pnl']:+.2f} | Win Rate: {recent['summary']['win_rate']:.0f}% | W:{recent['summary']['wins']} L:{recent['summary']['losses']}")
        for t in recent["trades"][:5]:
            pnl_str = f"${t['pnl']:+.2f}" if t["pnl"] else "pending"
            lines.append(f"  {t['timestamp']} {t['side'].upper()} {t['qty']} {t['symbol']} → {pnl_str}")

    for sym in watchlist[:4]:
        record = get_symbol_track_record(sym)
        if record["total_trades"] > 0 or record["recent_reasoning"]:
            lines.append(f"\n### {sym} Track Record")
            lines.append(f"Trades: {record['total_trades']} | P&L: ${record['total_pnl']:+.2f} | Win Rate: {record['win_rate']:.0f}%")
            lines.append(f"Lesson: {record['lesson']}")
            if record["recent_reasoning"]:
                latest = record["recent_reasoning"][0]
                lines.append(f"Last analysis ({latest['date']}): {latest['action'].upper()} at {latest['confidence']:.0%} — {latest['thought'][:100]}")

    result = "\n".join(lines)
    if len(result) > max_tokens * 4:
        result = result[:max_tokens * 4] + "\n... (truncated)"
    return result
