"""
Claude Brain — the Alchemical Trading intelligence layer.

Exposes:
  register_tool_handlers(broker, risk, fetch_fn)
      Wire up live broker / risk objects so _process_tool_call can execute
      real orders and fetch real market data.

  run_agent_cycle(...)
      Multi-round agentic loop.  Returns a rich dict consumed by BotManager
      and ManagedAgent (tool_calls, rounds, success, reasoning, …).

  analyze_symbol(symbol, indicators, account_equity, current_positions,
                 support, ceiling)
      Single-symbol Claude analysis used by the Streamlit chart tab.

  get_token_usage() / reset_token_usage()
      Cumulative token accounting across all calls in this process.
"""

import json
import logging
import threading
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from anthropic import Anthropic

from trading.utils.config import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
#  Model — always use the latest and most capable available
# ------------------------------------------------------------------ #
_MODEL = "claude-sonnet-4-6"

# ------------------------------------------------------------------ #
#  Token tracking (process-wide, thread-safe)
# ------------------------------------------------------------------ #
_token_lock = threading.Lock()
_total_tokens: int = 0


def get_token_usage() -> dict:
    with _token_lock:
        return {"total_tokens": _total_tokens}


def reset_token_usage():
    global _total_tokens
    with _token_lock:
        _total_tokens = 0


def _add_tokens(n: int):
    global _total_tokens
    with _token_lock:
        _total_tokens += n


# ------------------------------------------------------------------ #
#  Registered tool handlers (set via register_tool_handlers)
# ------------------------------------------------------------------ #
_handlers: Dict[str, Any] = {
    "broker":   None,
    "risk":     None,
    "fetch_fn": None,
}


def register_tool_handlers(
    broker,
    risk,
    fetch_fn: Callable,
):
    """
    Wire in live objects so the agent loop can actually execute trades
    and fetch real market data instead of returning placeholders.

    Parameters
    ----------
    broker   : BrokerClient instance (or None for paper/simulation)
    risk     : RiskManager instance
    fetch_fn : callable(symbol, timeframe, bars) -> dict | None
    """
    _handlers["broker"]   = broker
    _handlers["risk"]     = risk
    _handlers["fetch_fn"] = fetch_fn


# ------------------------------------------------------------------ #
#  System prompt
# ------------------------------------------------------------------ #
SYSTEM_PROMPT = """
You are the "Alchemical Trader," a world-class quantitative hedge fund manager
modelled on Ray Dalio's all-weather philosophy.  Your mission is superior
risk-adjusted returns through the disciplined combination of:

  • Technical Analysis  — EMA stacks, RSI, MACD, Bollinger Bands, ATR, Fibonacci
  • Global Macro Context — yield curve, VIX regime, inflation proxies
  • Behavioural Edge     — avoid recency bias; think in base rates

## Available Tools
1. execute_trade          — Submit a live Alpaca order (buy or sell).
2. get_market_analysis    — Fetch technical indicators for any symbol.
3. log_alchemical_reasoning — Record your thought process for the audit trail.
4. get_macro_regime       — Get the current macro regime classification.

## Inviolable Rules
1. Call `get_macro_regime` at the start of every session if regime is unknown.
2. ALWAYS record your reasoning with `log_alchemical_reasoning` before trading.
3. Minimum 70 % conviction to execute any trade.  Below that: stay FLAT.
4. In HIGH_VOLATILITY or RECESSION_RISK regimes: reduce size by the provided
   `position_size_modifier`; do NOT fight the macro tape.
5. Never average into a losing position.
6. Cash is a valid, high-conviction position.
7. Every reasoning entry must be audit-ready and transparent.
"""

# ------------------------------------------------------------------ #
#  Tool schemas
# ------------------------------------------------------------------ #
TOOLS = [
    {
        "name": "execute_trade",
        "description": "Submit a trade order through the Alpaca broker.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol":     {"type": "string", "description": "Ticker symbol"},
                "side":       {"type": "string", "enum": ["buy", "sell"]},
                "qty":        {"type": "number", "description": "Number of shares"},
                "order_type": {"type": "string", "enum": ["market", "limit"],
                               "default": "market"},
                "reason":     {"type": "string", "description": "Justification for the trade"},
            },
            "required": ["symbol", "side", "qty", "reason"],
        },
    },
    {
        "name": "get_market_analysis",
        "description": "Retrieve technical indicators for a given symbol.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol":    {"type": "string"},
                "timeframe": {"type": "string", "default": "1d"},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "log_alchemical_reasoning",
        "description": "Log the internal thought process for a decision.",
        "input_schema": {
            "type": "object",
            "properties": {
                "thought_process":  {"type": "string"},
                "conviction_score": {"type": "number", "minimum": 0, "maximum": 100},
            },
            "required": ["thought_process", "conviction_score"],
        },
    },
    {
        "name": "get_macro_regime",
        "description": (
            "Analyse the global macro environment (VIX, yield curve, SPY trend). "
            "Returns the current regime and a position-size modifier."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


# ------------------------------------------------------------------ #
#  Tool dispatcher
# ------------------------------------------------------------------ #
def _process_tool_call(
    tool_name: str,
    tool_input: Dict,
    account_equity: float,
) -> Dict:
    """Route a tool call to the appropriate handler."""
    try:
        if tool_name == "get_market_analysis":
            symbol    = tool_input.get("symbol", "SPY")
            timeframe = tool_input.get("timeframe", "1d")
            fetch_fn  = _handlers.get("fetch_fn")
            if fetch_fn:
                data = fetch_fn(symbol, timeframe, 200)
                return {"status": "success", "symbol": symbol, "data": data}
            # Fallback: use charts module directly
            try:
                from trading.ui.charts import compute_indicators, fetch_yfinance, get_indicator_summary
                df = fetch_yfinance(symbol, timeframe, 200)
                if df is not None and len(df) >= 20:
                    df = compute_indicators(df)
                    return {"status": "success", "symbol": symbol,
                            "data": get_indicator_summary(df)}
            except Exception:
                pass
            return {"status": "error", "message": "Market data unavailable"}

        elif tool_name == "get_macro_regime":
            from trading.services.macro_engine import get_macro_regime_analysis
            return get_macro_regime_analysis()

        elif tool_name == "log_alchemical_reasoning":
            thought    = tool_input.get("thought_process", "")
            conviction = tool_input.get("conviction_score", 0)
            logger.info(f"ALCHEMICAL REASONING [{conviction}%]: {thought[:200]}")
            try:
                from trading.utils.database import log_event
                log_event("reasoning", f"[{conviction}%] {thought[:500]}", "info")
            except Exception:
                pass
            return {"status": "logged", "conviction": conviction}

        elif tool_name == "execute_trade":
            symbol     = tool_input.get("symbol")
            side       = tool_input.get("side")
            qty        = int(tool_input.get("qty", 0))
            order_type = tool_input.get("order_type", "market")
            reason     = tool_input.get("reason", "")

            broker = _handlers.get("broker")
            risk   = _handlers.get("risk")

            if not broker:
                return {"status": "simulated", "message": "No broker connected — trade logged only",
                        "symbol": symbol, "side": side, "qty": qty}

            if risk and risk.kill_switch_active:
                return {"status": "blocked", "message": "Kill switch active"}

            if risk:
                try:
                    acct   = broker.get_account_balance() or {}
                    equity = float(acct.get("portfolio_value", account_equity))
                    pos    = broker.get_current_positions() or []
                    price  = 0.0
                    try:
                        q     = broker.get_latest_quote(symbol)
                        price = q["mid"] if q else 0.0
                    except Exception:
                        pass
                    approved, msg = risk.approve_trade(side, symbol, qty, price, equity, pos)
                    if not approved:
                        return {"status": "blocked", "message": msg}
                except Exception as e:
                    return {"status": "error", "message": f"Risk check error: {e}"}

            order = broker.submit_order(
                symbol, qty, side, order_type=order_type, notes=f"Claude: {reason[:100]}"
            )
            if order:
                return {"status": "success", "order": order}
            return {"status": "error", "message": "Order submission failed"}

        return {"error": f"Unknown tool: {tool_name}"}

    except Exception as e:
        logger.error(f"Tool error [{tool_name}]: {e}")
        return {"error": str(e)}


# ------------------------------------------------------------------ #
#  Main agentic cycle
# ------------------------------------------------------------------ #
def run_agent_cycle(
    watchlist: List[str],
    market_context: Dict,
    account_equity: float,
    positions: List,
    risk_status: Dict,
    macro_context: Optional[Dict] = None,
    max_tool_rounds: int = 8,
) -> Dict:
    """
    Multi-round agentic loop.  Claude analyses the market and optionally
    executes trades.

    Returns
    -------
    dict
        status        : 'completed' | 'max_rounds_reached' | 'error'
        success       : bool
        rounds        : int — number of tool-use rounds consumed
        tool_calls    : list[dict] — each tool invocation with inputs/outputs
        reasoning     : list[dict] — log_alchemical_reasoning entries
        trades        : list[dict] — execute_trade calls that succeeded
        final_response: str | None
        tokens_used   : int
    """
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    env_summary = {
        "timestamp":        datetime.utcnow().isoformat() + "Z",
        "account_equity":   account_equity,
        "positions":        positions,
        "risk_status":      risk_status,
        "macro_environment": macro_context or "Not yet analysed — call get_macro_regime first.",
    }

    messages = [
        {
            "role": "user",
            "content": (
                f"Market State:\n{json.dumps(market_context, default=str)}\n\n"
                f"Account & Macro State:\n{json.dumps(env_summary, default=str)}\n\n"
                "Analyse the watchlist against the macro regime. "
                "Execute trades only when conviction exceeds 70 %. "
                "Record all reasoning via log_alchemical_reasoning."
            ),
        }
    ]

    tool_calls_log: List[Dict] = []
    reasoning_log:  List[Dict] = []
    trades_log:     List[Dict] = []
    tokens_used = 0
    round_num   = 0

    try:
        for round_num in range(max_tool_rounds):
            response = client.messages.create(
                model=_MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

            # Track tokens
            if hasattr(response, "usage") and response.usage:
                used = (response.usage.input_tokens or 0) + (response.usage.output_tokens or 0)
                tokens_used += used
                _add_tokens(used)

            if response.stop_reason != "tool_use":
                # Claude finished — extract text
                final_text = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        final_text = block.text
                        break
                return {
                    "status":         "completed",
                    "success":        True,
                    "rounds":         round_num + 1,
                    "tool_calls":     tool_calls_log,
                    "reasoning":      reasoning_log,
                    "trades":         trades_log,
                    "final_response": final_text,
                    "tokens_used":    tokens_used,
                }

            # Claude wants to call tools
            tool_blocks = [b for b in response.content if b.type == "tool_use"]
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for tool in tool_blocks:
                result = _process_tool_call(tool.name, tool.input, account_equity)

                entry = {
                    "tool":      tool.name,
                    "input":     tool.input,
                    "output":    result,
                    "timestamp": datetime.utcnow().isoformat(),
                }
                tool_calls_log.append(entry)

                if tool.name == "log_alchemical_reasoning":
                    reasoning_log.append({
                        "thought":    tool.input.get("thought_process", ""),
                        "conviction": tool.input.get("conviction_score", 0),
                        "timestamp":  entry["timestamp"],
                    })
                elif tool.name == "execute_trade" and result.get("status") == "success":
                    trades_log.append({
                        "symbol":    tool.input.get("symbol"),
                        "side":      tool.input.get("side"),
                        "qty":       tool.input.get("qty"),
                        "reason":    tool.input.get("reason", ""),
                        "timestamp": entry["timestamp"],
                    })

                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": tool.id,
                    "content":     json.dumps(result, default=str),
                })

            messages.append({"role": "user", "content": tool_results})

    except Exception as e:
        logger.error(f"run_agent_cycle error: {e}")
        return {
            "status":         "error",
            "success":        False,
            "rounds":         round_num,
            "tool_calls":     tool_calls_log,
            "reasoning":      reasoning_log,
            "trades":         trades_log,
            "final_response": None,
            "tokens_used":    tokens_used,
            "error":          str(e),
        }

    return {
        "status":         "max_rounds_reached",
        "success":        True,
        "rounds":         max_tool_rounds,
        "tool_calls":     tool_calls_log,
        "reasoning":      reasoning_log,
        "trades":         trades_log,
        "final_response": None,
        "tokens_used":    tokens_used,
    }


# ------------------------------------------------------------------ #
#  Single-symbol analysis (used by the Streamlit chart tab)
# ------------------------------------------------------------------ #
_ANALYZE_SYSTEM = """
You are the Alchemical Trader.  You will be given technical indicator data for
a single equity symbol and must return a JSON object (no markdown fencing) with
exactly these keys:

  action        : "buy" | "sell" | "hold"
  confidence    : float 0.0–1.0
  signal_type   : short label, e.g. "EMA Bullish Crossover + BB Squeeze Breakout"
  time_horizon  : e.g. "3–5 days", "1–2 weeks"
  entry_price   : float | null
  stop_loss     : float | null
  target_price  : float | null
  reasoning     : detailed multi-sentence explanation (minimum 80 words)
  risks         : list of 2–4 concise risk strings

Rules:
- Only recommend buy or sell when confidence >= 0.70.
- Consider the macro regime modifier — scale conviction accordingly.
- Your stop_loss MUST be below (buy) or above (sell) the current price.
- entry_price should be the current close unless you have a specific level.
"""


def analyze_symbol(
    symbol: str,
    indicators: Dict,
    account_equity: float,
    current_positions: List,
    support: Optional[float] = None,
    ceiling: Optional[float] = None,
) -> Optional[Dict]:
    """
    Ask Claude for a single-symbol trade decision.

    Parameters
    ----------
    symbol           : ticker
    indicators       : dict from get_indicator_summary + detect_signal
    account_equity   : current portfolio value
    current_positions: list of open position dicts
    support          : user-drawn support level (or None)
    ceiling          : user-drawn resistance/ceiling level (or None)

    Returns
    -------
    dict matching the schema in _ANALYZE_SYSTEM, or None on failure.
    """
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    payload = {
        "symbol":            symbol,
        "indicators":        indicators,
        "account_equity":    account_equity,
        "current_positions": current_positions,
        "user_levels":       {"support": support, "ceiling": ceiling},
    }

    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=_ANALYZE_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Analyse {symbol} and return a JSON decision object.\n\n"
                        f"Data:\n{json.dumps(payload, default=str)}"
                    ),
                }
            ],
        )

        # Token tracking
        if hasattr(response, "usage") and response.usage:
            _add_tokens(
                (response.usage.input_tokens or 0) + (response.usage.output_tokens or 0)
            )

        raw = ""
        for block in response.content:
            if hasattr(block, "text"):
                raw = block.text.strip()
                break

        # Strip any accidental markdown fencing
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        result = json.loads(raw)

        # Normalise confidence to 0-1 if model returned 0-100
        conf = result.get("confidence", 0)
        if isinstance(conf, (int, float)) and conf > 1.0:
            result["confidence"] = conf / 100.0

        return result

    except json.JSONDecodeError as e:
        logger.error(f"analyze_symbol JSON parse error for {symbol}: {e}\nRaw: {raw[:300]}")
        return None
    except Exception as e:
        logger.error(f"analyze_symbol error for {symbol}: {e}")
        return None
