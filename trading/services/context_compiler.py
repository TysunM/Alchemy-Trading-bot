import json
from datetime import datetime, timedelta
from typing import Optional

from trading.utils.database import (
    SessionLocal,
    SnapshotCheckpoint,
    DailySummary,
    ReasoningLedger,
    TradeLog,
    ToolCallLog,
    log_event,
)

TOKEN_BUDGET = 1_000_000
SUMMARY_TARGET_TOKENS = 2000
CHECKPOINT_INTERVAL_MINUTES = 15


class ContextCompiler:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.total_tokens_used = 0

    def save_checkpoint(
        self,
        positions: list,
        open_orders: list,
        market_context: dict,
        reasoning_summary: str,
        token_usage: int,
        cycle_count: int,
        account_equity: float,
        extra_metadata: Optional[dict] = None,
    ):
        db = SessionLocal()
        try:
            checkpoint = SnapshotCheckpoint(
                session_id=self.session_id,
                positions_json=json.dumps(positions, default=str),
                open_orders_json=json.dumps(open_orders, default=str),
                market_context_json=json.dumps(market_context, default=str),
                reasoning_summary=reasoning_summary,
                token_usage=token_usage,
                cycle_count=cycle_count,
                account_equity=account_equity,
                metadata_json=json.dumps(extra_metadata, default=str) if extra_metadata else None,
            )
            db.add(checkpoint)
            db.commit()
            self.total_tokens_used = token_usage
            return checkpoint.id
        except Exception as e:
            log_event("context_compiler", f"Checkpoint save error: {e}", "error")
            return None
        finally:
            db.close()

    def generate_daily_summary(self, date_str: Optional[str] = None) -> Optional[str]:
        if not date_str:
            date_str = datetime.utcnow().strftime("%Y-%m-%d")

        db = SessionLocal()
        try:
            day_start = datetime.strptime(date_str, "%Y-%m-%d")
            day_end = day_start + timedelta(days=1)

            reasoning_entries = (
                db.query(ReasoningLedger)
                .filter(
                    ReasoningLedger.timestamp >= day_start,
                    ReasoningLedger.timestamp < day_end,
                )
                .order_by(ReasoningLedger.timestamp)
                .all()
            )

            trades = (
                db.query(TradeLog)
                .filter(
                    TradeLog.timestamp >= day_start,
                    TradeLog.timestamp < day_end,
                )
                .order_by(TradeLog.timestamp)
                .all()
            )

            checkpoints = (
                db.query(SnapshotCheckpoint)
                .filter(
                    SnapshotCheckpoint.timestamp >= day_start,
                    SnapshotCheckpoint.timestamp < day_end,
                    SnapshotCheckpoint.session_id == self.session_id,
                )
                .order_by(SnapshotCheckpoint.timestamp.desc())
                .limit(5)
                .all()
            )

            summary_parts = [f"Daily Summary for {date_str}:"]

            if trades:
                total_pnl = sum(t.pnl or 0 for t in trades)
                buys = sum(1 for t in trades if t.side == "buy")
                sells = sum(1 for t in trades if t.side == "sell")
                symbols_traded = list(set(t.symbol for t in trades))
                summary_parts.append(
                    f"Trades: {len(trades)} total ({buys} buys, {sells} sells). "
                    f"Symbols: {', '.join(symbols_traded)}. P&L: ${total_pnl:,.2f}"
                )
            else:
                total_pnl = 0.0
                summary_parts.append("No trades executed.")

            if reasoning_entries:
                symbols_analyzed = list(set(r.symbol for r in reasoning_entries))
                high_conf = [r for r in reasoning_entries if (r.confidence or 0) >= 0.7]
                summary_parts.append(
                    f"Analysis: {len(reasoning_entries)} reasoning entries across "
                    f"{', '.join(symbols_analyzed)}. {len(high_conf)} high-conviction signals."
                )

                for entry in reasoning_entries[-5:]:
                    conf_str = f" ({entry.confidence:.0%})" if entry.confidence else ""
                    summary_parts.append(
                        f"  - {entry.symbol} {entry.action.upper()}{conf_str}: "
                        f"{(entry.reasoning or '')[:150]}"
                    )

            if checkpoints:
                latest = checkpoints[0]
                summary_parts.append(
                    f"Latest checkpoint: equity=${latest.account_equity:,.2f}, "
                    f"tokens={latest.token_usage:,}, cycles={latest.cycle_count}"
                )

            key_decisions = []
            for r in reasoning_entries:
                if r.action in ("buy", "sell") and (r.confidence or 0) >= 0.6:
                    key_decisions.append({
                        "symbol": r.symbol,
                        "action": r.action,
                        "confidence": r.confidence,
                        "reasoning": (r.reasoning or "")[:200],
                    })

            summary_text = "\n".join(summary_parts)

            existing = (
                db.query(DailySummary)
                .filter(DailySummary.date == date_str, DailySummary.session_id == self.session_id)
                .first()
            )

            if existing:
                existing.summary_text = summary_text
                existing.trades_count = len(trades)
                existing.total_pnl = total_pnl
                existing.key_decisions_json = json.dumps(key_decisions, default=str)
                existing.token_budget_used = self.total_tokens_used
            else:
                daily = DailySummary(
                    date=date_str,
                    session_id=self.session_id,
                    summary_text=summary_text,
                    trades_count=len(trades),
                    total_pnl=total_pnl,
                    key_decisions_json=json.dumps(key_decisions, default=str),
                    token_budget_used=self.total_tokens_used,
                )
                db.add(daily)

            db.commit()
            return summary_text

        except Exception as e:
            log_event("context_compiler", f"Daily summary error: {e}", "error")
            return None
        finally:
            db.close()

    def get_context_payload(self, hours: int = 24) -> dict:
        db = SessionLocal()
        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)

            reasoning = (
                db.query(ReasoningLedger)
                .filter(ReasoningLedger.timestamp >= cutoff)
                .order_by(ReasoningLedger.timestamp.desc())
                .limit(50)
                .all()
            )

            trades = (
                db.query(TradeLog)
                .filter(TradeLog.timestamp >= cutoff)
                .order_by(TradeLog.timestamp.desc())
                .limit(30)
                .all()
            )

            checkpoints = (
                db.query(SnapshotCheckpoint)
                .filter(
                    SnapshotCheckpoint.timestamp >= cutoff,
                    SnapshotCheckpoint.session_id == self.session_id,
                )
                .order_by(SnapshotCheckpoint.timestamp.desc())
                .limit(10)
                .all()
            )

            summaries = (
                db.query(DailySummary)
                .order_by(DailySummary.date.desc())
                .limit(7)
                .all()
            )

            return {
                "reasoning_entries": [
                    {
                        "timestamp": r.timestamp.isoformat(),
                        "symbol": r.symbol,
                        "action": r.action,
                        "confidence": r.confidence,
                        "signal_type": r.signal_type,
                        "reasoning": (r.reasoning or "")[:500],
                    }
                    for r in reasoning
                ],
                "recent_trades": [
                    {
                        "timestamp": t.timestamp.isoformat(),
                        "symbol": t.symbol,
                        "side": t.side,
                        "qty": t.qty,
                        "price": t.price,
                        "pnl": t.pnl,
                        "status": t.status,
                    }
                    for t in trades
                ],
                "checkpoints": [
                    {
                        "timestamp": c.timestamp.isoformat(),
                        "account_equity": c.account_equity,
                        "token_usage": c.token_usage,
                        "cycle_count": c.cycle_count,
                        "reasoning_summary": (c.reasoning_summary or "")[:300],
                    }
                    for c in checkpoints
                ],
                "daily_summaries": [
                    {
                        "date": s.date,
                        "summary": (s.summary_text or "")[:500],
                        "trades_count": s.trades_count,
                        "total_pnl": s.total_pnl,
                    }
                    for s in summaries
                ],
                "token_budget": {
                    "limit": TOKEN_BUDGET,
                    "used": self.total_tokens_used,
                    "remaining": TOKEN_BUDGET - self.total_tokens_used,
                    "utilization_pct": round(self.total_tokens_used / TOKEN_BUDGET * 100, 2),
                },
            }

        except Exception as e:
            log_event("context_compiler", f"Context payload error: {e}", "error")
            return {"error": str(e)}
        finally:
            db.close()

    def log_tool_call(
        self,
        tool_name: str,
        input_data: dict,
        result_data: dict,
        duration_ms: int,
        success: bool = True,
    ):
        db = SessionLocal()
        try:
            entry = ToolCallLog(
                session_id=self.session_id,
                tool_name=tool_name,
                input_json=json.dumps(input_data, default=str)[:2000],
                result_json=json.dumps(result_data, default=str)[:2000],
                duration_ms=duration_ms,
                success=1 if success else 0,
            )
            db.add(entry)
            db.commit()
        except Exception:
            pass
        finally:
            db.close()

    def get_recent_tool_calls(self, limit: int = 20) -> list:
        db = SessionLocal()
        try:
            calls = (
                db.query(ToolCallLog)
                .filter(ToolCallLog.session_id == self.session_id)
                .order_by(ToolCallLog.timestamp.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "timestamp": c.timestamp.isoformat(),
                    "tool_name": c.tool_name,
                    "input": c.input_json,
                    "duration_ms": c.duration_ms,
                    "success": bool(c.success),
                }
                for c in calls
            ]
        except Exception:
            return []
        finally:
            db.close()


def get_recent_checkpoints(session_id: str, limit: int = 10) -> list:
    db = SessionLocal()
    try:
        rows = (
            db.query(SnapshotCheckpoint)
            .filter(SnapshotCheckpoint.session_id == session_id)
            .order_by(SnapshotCheckpoint.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat(),
                "account_equity": r.account_equity,
                "token_usage": r.token_usage,
                "cycle_count": r.cycle_count,
                "reasoning_summary": r.reasoning_summary,
            }
            for r in rows
        ]
    except Exception:
        return []
    finally:
        db.close()


def get_recent_summaries(limit: int = 7) -> list:
    db = SessionLocal()
    try:
        rows = (
            db.query(DailySummary)
            .order_by(DailySummary.date.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "date": r.date,
                "summary": r.summary_text,
                "trades_count": r.trades_count,
                "total_pnl": r.total_pnl,
                "token_budget_used": r.token_budget_used,
            }
            for r in rows
        ]
    except Exception:
        return []
    finally:
        db.close()
