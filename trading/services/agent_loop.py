"""
Agent loop — the heartbeat of the main Alchemical Trading agent.

Exports
-------
  AgentState           — re-exported from state_manager for app.py convenience
  start_agent_loop     — launch a background trading loop
  stop_agent_loop      — signal the loop to halt
  run_single_cycle     — execute exactly one analysis + decision cycle
"""

import logging
import threading
import time
from datetime import datetime
from typing import Any, List, Optional

from trading.services.claude_brain import run_agent_cycle
from trading.services.macro_engine import get_macro_regime_analysis
from trading.utils.config import DEFAULT_SYMBOLS
from trading.utils.state_manager import AgentState  # noqa: F401  (re-exported)

logger = logging.getLogger(__name__)

# Module-level loop controls
_stop_event: threading.Event = threading.Event()
_agent_thread: Optional[threading.Thread] = None


def _fetch_analysis_for_tool(
    symbol: str,
    timeframe: str = "1d",
    bars: int = 200,
) -> Optional[dict]:
    """
    Fetch live technical indicators for *symbol*.

    Uses the same indicator engine as the chart tab so the agent sees
    exactly the same data the operator sees.
    """
    try:
        from trading.ui.charts import compute_indicators, fetch_yfinance, get_indicator_summary

        df = fetch_yfinance(symbol, timeframe, bars)
        if df is None or len(df) < 20:
            return None

        df = compute_indicators(df)
        summary = get_indicator_summary(df)

        ema_stack = (
            "bullish" if summary["ema_bullish_stack"]
            else ("bearish" if summary["ema_bearish_stack"] else "mixed")
        )
        summary["ema_stack"] = ema_stack
        summary["symbol"]    = symbol
        summary["timeframe"] = timeframe
        return summary

    except Exception as e:
        logger.error(f"_fetch_analysis_for_tool({symbol}): {e}")
        return None


def _run_cycle(
    watchlist: List[str],
    broker: Any,
    risk: Any,
    state: AgentState,
):
    """Execute one complete analysis + decision cycle."""
    state.update(status="running cycle", last_run=datetime.now().isoformat())
    logger.info("--- Starting Alchemical Agent Cycle ---")

    try:
        # 1. Account data
        account_equity = 100_000.0
        positions: List = []

        if broker:
            try:
                acct = broker.get_account_balance()
                if acct:
                    account_equity = float(acct.get("portfolio_value", 100_000.0))
                positions = broker.get_current_positions() or []
                logger.info(f"Account equity: ${account_equity:,.2f}")
            except Exception as e:
                logger.error(f"Account fetch error: {e}")

        # 2. Macro regime (Dalio-inspired overlay)
        logger.info("Analysing global macro environment…")
        macro_context = get_macro_regime_analysis()
        logger.info(f"Macro regime: {macro_context.get('regime', 'unknown')} | "
                    f"modifier={macro_context.get('position_size_modifier', 1.0):.2f}x")

        # 3. Market data for watchlist
        market_context: dict = {}
        for sym in watchlist[:10]:
            try:
                data = _fetch_analysis_for_tool(sym)
                if data:
                    market_context[sym] = data
            except Exception as e:
                logger.error(f"Market data error for {sym}: {e}")

        # 4. Risk constraints
        risk_status = risk.get_status() if risk else {}

        # 5. Claude brain
        logger.info("Dispatching to Alchemical Brain (Claude)…")
        result = run_agent_cycle(
            watchlist=watchlist,
            market_context=market_context,
            account_equity=account_equity,
            positions=positions,
            risk_status=risk_status,
            macro_context=macro_context,
        )

        trades = len(result.get("trades", []))
        tools  = len(result.get("tool_calls", []))
        logger.info(
            f"Cycle complete — status={result.get('status')} "
            f"rounds={result.get('rounds', 0)} tools={tools} trades={trades} "
            f"tokens={result.get('tokens_used', 0):,}"
        )

        state.update(
            status="idle",
            last_result=result,
            last_cycle_result=result,
            last_cycle_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            cycle_count=state.cycle_count + 1,
            total_tool_calls=state.total_tool_calls + tools,
            total_trades=state.total_trades + trades,
        )
        state.add_history({
            "time":   datetime.now().strftime("%H:%M:%S"),
            "tools":  tools,
            "trades": trades,
            "rounds": result.get("rounds", 0),
        })

    except Exception as e:
        logger.error(f"Critical cycle error: {e}")
        state.update(status="error", last_error=str(e), errors=state.errors + 1)


def run_single_cycle(
    broker: Any = None,
    risk: Any = None,
    state: Optional[AgentState] = None,
):
    """Run exactly one analysis cycle (blocking).  Safe to call from the UI."""
    if state is None:
        state = AgentState()
    _run_cycle(DEFAULT_SYMBOLS, broker, risk, state)


def start_agent_loop(
    broker: Any,
    risk: Any,
    state: AgentState,
    interval_minutes: int = 15,
):
    """
    Spawn a background daemon thread that runs the agent cycle every
    *interval_minutes* minutes until stop_agent_loop() is called.
    """
    global _stop_event, _agent_thread

    _stop_event = threading.Event()
    state.update(running=True, status="starting")

    def _loop():
        logger.info(f"Agent loop started — interval {interval_minutes}m")
        while not _stop_event.is_set():
            _run_cycle(DEFAULT_SYMBOLS, broker, risk, state)
            logger.info(f"Sleeping {interval_minutes}m until next cycle…")
            _stop_event.wait(timeout=interval_minutes * 60)
        state.update(running=False, status="stopped")
        logger.info("Agent loop stopped.")

    _agent_thread = threading.Thread(target=_loop, daemon=True, name="agent-loop")
    _agent_thread.start()


def stop_agent_loop(state: Optional[AgentState] = None):
    """Signal the background loop to stop after the current cycle finishes."""
    _stop_event.set()
    if state:
        state.update(running=False, status="stopping")
    logger.info("Agent loop stop requested.")
