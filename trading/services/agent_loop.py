"""
Phase 3: Autonomous Agent Loop — Background Worker.

Runs on a configurable interval, pulling market data for the watchlist,
feeding it to Claude via tool-use, and processing the resulting actions.

The loop runs in a background thread and writes status updates to a shared
state dict that the Streamlit UI can read. All actions are logged to the
database for full auditability.
"""

import threading
import time
from datetime import datetime
from typing import Optional

from trading.services.broker import BrokerClient
from trading.services.claude_brain import register_tool_handlers, run_agent_cycle
from trading.services.risk_manager import RiskManager
from trading.ui.charts import compute_indicators, fetch_yfinance, get_indicator_summary
from trading.utils.database import log_event


class AgentState:
    def __init__(self):
        self.running = False
        self.last_cycle_time: Optional[str] = None
        self.last_cycle_result: Optional[dict] = None
        self.cycle_count = 0
        self.errors = 0
        self.total_tool_calls = 0
        self.total_trades = 0
        self.status = "idle"
        self.history: list[dict] = []
        self._lock = threading.Lock()

    def update(self, **kwargs):
        with self._lock:
            for k, v in kwargs.items():
                setattr(self, k, v)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "last_cycle_time": self.last_cycle_time,
                "last_cycle_result": self.last_cycle_result,
                "cycle_count": self.cycle_count,
                "errors": self.errors,
                "total_tool_calls": self.total_tool_calls,
                "total_trades": self.total_trades,
                "status": self.status,
                "history": list(self.history[-20:]),
            }

    def add_history(self, entry: dict):
        with self._lock:
            self.history.append(entry)
            if len(self.history) > 50:
                self.history = self.history[-50:]


def _fetch_analysis_for_tool(symbol: str, timeframe: str = "1d", bars: int = 200) -> Optional[dict]:
    df = fetch_yfinance(symbol, timeframe, bars)
    if df is None or len(df) < 20:
        return None
    df = compute_indicators(df)
    summary = get_indicator_summary(df)
    ema_stack = "bullish" if summary["ema_bullish_stack"] else ("bearish" if summary["ema_bearish_stack"] else "mixed")
    summary["ema_stack"] = ema_stack
    return summary


def _run_cycle(
    watchlist: list[str],
    broker: Optional[BrokerClient],
    risk: RiskManager,
    state: AgentState,
):
    state.update(status="running cycle")
    cycle_start = time.time()

    account_equity = 100_000.0
    positions = []
    if broker:
        try:
            acct = broker.get_account_balance()
            if acct:
                account_equity = acct["portfolio_value"]
            positions = broker.get_current_positions() or []
        except Exception:
            pass

    market_context = {}
    for sym in watchlist[:8]:
        try:
            data = _fetch_analysis_for_tool(sym, "1d", 200)
            if data:
                market_context[sym] = data
        except Exception:
            market_context[sym] = None

    risk_status = risk.get_status()

    try:
        result = run_agent_cycle(
            watchlist=watchlist,
            market_context=market_context,
            account_equity=account_equity,
            positions=positions,
            risk_status=risk_status,
        )

        trade_count = sum(1 for tc in result.get("tool_calls", []) if tc["tool"] == "execute_trade")
        tool_count = len(result.get("tool_calls", []))

        state.update(
            last_cycle_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            last_cycle_result=result,
            cycle_count=state.cycle_count + 1,
            total_tool_calls=state.total_tool_calls + tool_count,
            total_trades=state.total_trades + trade_count,
            status="idle",
        )

        duration = time.time() - cycle_start
        state.add_history({
            "time": datetime.now().strftime("%H:%M:%S"),
            "duration": f"{duration:.1f}s",
            "tools": tool_count,
            "trades": trade_count,
            "rounds": result.get("rounds", 0),
            "success": result.get("success", False),
        })

        log_event(
            "agent_loop",
            f"Cycle #{state.cycle_count} complete — {tool_count} tool calls, {trade_count} trades, {result.get('rounds',0)} rounds in {duration:.1f}s",
            "info",
        )

    except Exception as e:
        state.update(
            errors=state.errors + 1,
            status="error",
            last_cycle_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        log_event("agent_loop", f"Cycle error: {e}", "error")


_agent_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


def start_agent_loop(
    watchlist: list[str],
    broker: Optional[BrokerClient],
    risk: RiskManager,
    state: AgentState,
    interval_seconds: int = 300,
):
    global _agent_thread, _stop_event

    if _agent_thread and _agent_thread.is_alive():
        return False

    register_tool_handlers(broker, risk, _fetch_analysis_for_tool)

    _stop_event = threading.Event()
    state.update(running=True, status="starting")
    log_event("agent_loop", f"Agent loop starting — interval {interval_seconds}s, watchlist: {', '.join(watchlist)}", "info")

    def loop():
        while not _stop_event.is_set():
            if risk.kill_switch_active:
                state.update(status="paused (kill switch)")
                time.sleep(10)
                continue

            _run_cycle(watchlist, broker, risk, state)

            state.update(status=f"waiting ({interval_seconds}s)")
            _stop_event.wait(timeout=interval_seconds)

        state.update(running=False, status="stopped")
        log_event("agent_loop", "Agent loop stopped", "info")

    _agent_thread = threading.Thread(target=loop, daemon=True, name="alchemical-agent")
    _agent_thread.start()
    return True


def stop_agent_loop(state: AgentState):
    global _stop_event
    _stop_event.set()
    state.update(status="stopping")
    log_event("agent_loop", "Agent loop stop requested", "info")


def run_single_cycle(
    watchlist: list[str],
    broker: Optional[BrokerClient],
    risk: RiskManager,
    state: AgentState,
):
    register_tool_handlers(broker, risk, _fetch_analysis_for_tool)
    _run_cycle(watchlist, broker, risk, state)
