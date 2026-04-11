import time
import logging
import json
from datetime import datetime
from typing import List, Optional, Dict, Any

# Internal Service Imports
from trading.services.claude_brain import run_agent_cycle
from trading.services.macro_engine import get_macro_regime_analysis
from trading.utils.config import DEFAULT_SYMBOLS
from trading.utils.state_manager import AgentState

# Setup Logging
logger = logging.getLogger(__name__)

def _fetch_analysis_for_tool(symbol: str, timeframe: str = "1d", limit: int = 100):
    """
    Helper function to fetch technical data for the agent.
    In a real setup, this would call your technical analysis engine.
    """
    # Placeholder for the actual technical analysis data fetcher
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "indicators": {
            "rsi": 55.4,
            "ema_20": 150.2,
            "ema_50": 145.8,
            "macd": "bullish_cross"
        }
    }

def _run_cycle(
    watchlist: List[str],
    broker: Any,
    risk: Any,
    state: AgentState
):
    """
    The main heartbeat of the trading bot.
    Fetches account, market, and macro data then triggers Claude.
    """
    state.update(status="running cycle", last_run=datetime.now().isoformat())
    logger.info("--- Starting Alchemical Agent Cycle ---")

    try:
        # 1. Fetch Account Data from Broker
        account_equity = 100000.0  # Default if broker is unavailable
        positions = []
        
        if broker:
            try:
                acct = broker.get_account_balance()
                if acct:
                    # Pulling the real portfolio value from Alpaca
                    account_equity = float(acct.get("portfolio_value", 100000.0))
                positions = broker.get_current_positions() or []
                logger.info(f"Account Equity: ${account_equity}")
            except Exception as e:
                logger.error(f"Error fetching account data: {e}")

        # 2. FETCH MACRO CONTEXT (The Dalio Upgrade)
        logger.info("Analyzing Global Macro Environment...")
        macro_context = get_macro_regime_analysis()
        logger.info(f"Current Regime: {macro_context.get('regime', 'Unknown')}")

        # 3. Fetch Market Data for the Watchlist
        market_context = {}
        for sym in watchlist[:10]:
            try:
                data = _fetch_analysis_for_tool(sym)
                market_context[sym] = data
            except Exception as e:
                logger.error(f"Error fetching data for {sym}: {e}")

        # 4. Get Risk Constraints
        risk_status = {}
        if risk:
            risk_status = risk.get_status()

        # 5. EXECUTE CLAUDE BRAIN
        # Passing macro_context here so Claude can use Rule #11 in the system prompt
        logger.info("Sending data to Alchemical Brain (Claude)...")
        result = run_agent_cycle(
            watchlist=watchlist,
            market_context=market_context,
            account_equity=account_equity,
            positions=positions,
            risk_status=risk_status,
            macro_context=macro_context  # The bridge between the economy and the trade
        )

        logger.info(f"Cycle Result: {result.get('status')}")
        state.update(status="idle", last_result=result)

    except Exception as e:
        logger.error(f"Critical error in agent cycle: {e}")
        state.update(status="error", last_error=str(e))

def start_agent_loop(broker: Any, risk: Any, state: AgentState, interval_minutes: int = 15):
    """
    Starts the continuous background loop.
    """
    logger.info(f"Agent Loop started. Interval: {interval_minutes} minutes.")
    
    while True:
        watchlist = DEFAULT_SYMBOLS
        _run_cycle(watchlist, broker, risk, state)
        logger.info(f"Cycle complete. Sleeping for {interval_minutes} minutes...")
        time.sleep(interval_minutes * 60)
