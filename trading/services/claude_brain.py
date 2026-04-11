"""
Phase 3: Claude Brain with Anthropic Tool-Use (Function Calling).

Claude operates as an autonomous trading agent with access to three tools:
  1. execute_trade — submit orders through the broker
  2. get_market_analysis — pull live indicators for any symbol
  3. log_alchemical_reasoning — record thought process to the Reasoning Ledger

The agent loop sends Claude the current market state, and Claude decides
which tools to call. Every decision is fully auditable through the ledger.
"""

import json
import threading
import time
from datetime import datetime
from typing import Optional

import anthropic

from trading.utils.config import ANTHROPIC_API_KEY
from trading.utils.database import log_event, log_reasoning

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_thread_local = threading.local()
_trade_lock = threading.Lock()

_token_usage = {
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0,
}
_token_lock = threading.Lock()


def get_token_usage() -> dict:
    with _token_lock:
        return dict(_token_usage)


def _track_tokens(response):
    if hasattr(response, "usage") and response.usage:
        with _token_lock:
            _token_usage["input_tokens"] += getattr(response.usage, "input_tokens", 0)
            _token_usage["output_tokens"] += getattr(response.usage, "output_tokens", 0)
            _token_usage["total_tokens"] = _token_usage["input_tokens"] + _token_usage["output_tokens"]


def reset_token_usage():
    with _token_lock:
        _token_usage["input_tokens"] = 0
        _token_usage["output_tokens"] = 0
        _token_usage["total_tokens"] = 0

SYSTEM_PROMPT = """You are the Alchemical Trading Brain — an autonomous quantitative trading agent.

You have direct access to tools that let you analyze markets, execute trades, and record your reasoning.

## Your Trading Strategy

1. **Triple EMA Confirmation** — EMA 9 / 50 / 200 stack alignment determines trend direction.
   - Bullish stack: 9 > 50 > 200 (go long or hold)
   - Bearish stack: 9 < 50 < 200 (go short or stay flat)
   - Mixed: wait for confirmation

2. **Bollinger Band Cycles** — Mean reversion + breakout detection.
   - %B < 0.0 → oversold bounce candidate
   - %B > 1.0 → overbought pullback candidate
   - BB Squeeze (narrow bands) → breakout imminent, prepare for direction

3. **Fibonacci Levels** — Use for precision entries and exits.
   - Enter near 38.2% or 61.8% retracement during pullbacks
   - Set targets at extensions or prior swing highs/lows

4. **ATR-Based Risk Management** (MANDATORY)
   - Stop loss = entry ± (ATR × multiplier)
   - Position size = (equity × risk%) / (ATR × multiplier)
   - Never risk more than max_risk_pct per trade

5. **RSI + MACD as Confirmation Filters**
   - RSI divergence strengthens or weakens signals
   - MACD histogram flip confirms momentum shifts

## Advanced Tools
6. **Portfolio Rebalancing** — Check if portfolio drifts from target allocations.
7. **Sector Rotation** — Monitor sector ETF relative strength for rotation signals.
8. **News Sentiment** — Fetch headlines and analyst recommendations for fundamental context.
9. **Multi-Timeframe Analysis** — Cross-reference 15m, 1h, and daily signals for confluence confirmation. Higher confluence = stronger signal.
10. **Memory Recall** — Search your past reasoning and trade outcomes. Learn from history. Check your track record with a symbol before re-entering.


## Rules
- You MUST use `log_alchemical_reasoning` to record your thought process BEFORE making any trade.
- You MUST use `get_market_analysis` if you need fresh data for a symbol before deciding.
- Use `get_multi_timeframe_analysis` for confluence confirmation on high-conviction setups.
- Use `recall_past_decisions` to check your track record with a symbol before trading it again.
- Only call `execute_trade` when you have high conviction (>70% confidence).
- If unsure, log your reasoning and HOLD. Patience is a strategy.
- You think in probabilities. Every statement should reflect uncertainty honestly.
- Your reasoning should be transparent, detailed, and auditable — a human reviewing the ledger should understand exactly why you acted.
- Learn from your past: if you've been losing on a symbol, change your approach or reduce size.

## Current Session Context
You are running in an autonomous loop. Each cycle, you receive the latest market data and must decide what to do. Use your tools wisely."""

TOOLS = [
    {
        "name": "execute_trade",
        "description": "Submit a trade order through the Alpaca broker. This is a REAL order (paper or live depending on config). The risk manager will validate position sizing and exposure limits before execution. Only call this when you have high conviction.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "The ticker symbol to trade (e.g., 'AAPL', 'SPY')"
                },
                "side": {
                    "type": "string",
                    "enum": ["buy", "sell"],
                    "description": "Whether to buy or sell"
                },
                "qty": {
                    "type": "integer",
                    "description": "Number of shares to trade. Use the ATR-based position sizing formula: qty = (equity * risk_pct) / (ATR * atr_multiplier)"
                },
                "order_type": {
                    "type": "string",
                    "enum": ["market", "limit"],
                    "description": "Order type. Use 'market' for immediate fills, 'limit' for precise entries."
                },
                "limit_price": {
                    "type": "number",
                    "description": "Required if order_type is 'limit'. The limit price for the order."
                },
                "reasoning": {
                    "type": "string",
                    "description": "Brief explanation of why this trade is being placed"
                }
            },
            "required": ["symbol", "side", "qty", "order_type", "reasoning"]
        }
    },
    {
        "name": "get_market_analysis",
        "description": "Fetch current technical indicator data for a symbol. Returns price, EMA stack, Bollinger Bands, RSI, MACD, ATR, volume, and signal analysis. Use this to get fresh data before making decisions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "The ticker symbol to analyze (e.g., 'AAPL', 'SPY')"
                },
                "timeframe": {
                    "type": "string",
                    "enum": ["1d", "1h", "15m"],
                    "description": "Chart timeframe for analysis. Default '1d'."
                },
                "bars": {
                    "type": "integer",
                    "description": "Number of historical bars to fetch. Default 200."
                }
            },
            "required": ["symbol"]
        }
    },
    {
        "name": "log_alchemical_reasoning",
        "description": "Record your thought process to the Reasoning Ledger. This is your 'internal monologue' — use it to document your analysis, doubts, pattern recognition, and decision rationale. ALWAYS log reasoning before executing a trade. This creates a fully auditable trail.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "The symbol being analyzed"
                },
                "action": {
                    "type": "string",
                    "enum": ["buy", "sell", "hold", "analyzing", "monitoring"],
                    "description": "The action being considered or taken"
                },
                "thought_process": {
                    "type": "string",
                    "description": "Your detailed internal reasoning. Be thorough — explain what patterns you see, what confluence signals exist, what risks concern you, and why you're choosing this action."
                },
                "signal_type": {
                    "type": "string",
                    "description": "Primary signal pattern (e.g., 'EMA bullish crossover', 'BB squeeze breakout', 'RSI divergence')"
                },
                "confidence": {
                    "type": "number",
                    "description": "Your confidence level from 0.0 to 1.0"
                }
            },
            "required": ["symbol", "action", "thought_process", "signal_type", "confidence"]
        }
    },
    {
        "name": "rebalance_portfolio",
        "description": "Analyze current portfolio positions against target allocations and suggest rebalancing trades. Returns which positions are over/underweight and the trades needed to rebalance.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_allocations": {
                    "type": "object",
                    "description": "Target allocation percentages by symbol, e.g. {'SPY': 40, 'QQQ': 30, 'IWM': 15, 'TLT': 15}. Values should sum to 100."
                },
                "tolerance_pct": {
                    "type": "number",
                    "description": "Rebalance threshold — only suggest trades when allocation deviates more than this %. Default 5."
                }
            },
            "required": ["target_allocations"]
        }
    },
    {
        "name": "analyze_sector_rotation",
        "description": "Compare performance of sector ETFs (XLK, XLF, XLE, XLV, XLI, XLP, XLU, XLY, XLC, XLRE, XLB) to identify sector rotation patterns — which sectors are gaining/losing relative strength.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lookback_days": {
                    "type": "integer",
                    "description": "Number of days to compare sector performance. Default 20."
                }
            },
            "required": []
        }
    },
    {
        "name": "get_news_sentiment",
        "description": "Fetch recent news headlines and basic info for a symbol using yfinance. Returns headlines, company info, and analyst recommendations to gauge market sentiment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "The ticker symbol to get news for (e.g., 'AAPL', 'TSLA')"
                }
            },
            "required": ["symbol"]
        }
    },
    {
        "name": "get_multi_timeframe_analysis",
        "description": "Cross-reference technical signals across 15-minute, 1-hour, and daily timeframes for a symbol. Returns alignment status and confluence score — stronger signals when all timeframes agree.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "The ticker symbol to analyze across timeframes"
                }
            },
            "required": ["symbol"]
        }
    },
    {
        "name": "recall_past_decisions",
        "description": "Search your memory for past reasoning entries and trade outcomes for a symbol or across all symbols. Use this to learn from your own history — what worked, what didn't, and why.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Filter by specific symbol, or omit for all symbols"
                },
                "lookback_days": {
                    "type": "integer",
                    "description": "How many days back to search. Default 30."
                },
                "include_trades": {
                    "type": "boolean",
                    "description": "Whether to include trade outcomes with P&L. Default true."
                }
            },
            "required": []
        }
    },
    {
        "name": "get_active_annotations",
        "description": "Retrieve the operator's manually drawn support/resistance levels and price annotations saved from the chart. These are key price levels the human operator has identified — use them to inform entry/exit decisions, validate your own technical analysis, and respect human-identified zones.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Filter annotations by symbol. Omit to get annotations for all symbols."
                }
            },
            "required": []
     },
     {
        "name": "get_macro_regime",
        "description": "Analyze the global macro environment, including yield curve, inflation proxies, and market volatility (VIX) to determine the current trading regime.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    }
]

_tool_handlers = {}


def register_tool_handlers(broker_client, risk_manager, analysis_fn):
    _thread_local.broker = broker_client
    _thread_local.risk = risk_manager
    _thread_local.analysis_fn = analysis_fn
    _tool_handlers["broker"] = broker_client
    _tool_handlers["risk"] = risk_manager
    _tool_handlers["analysis_fn"] = analysis_fn


def _get_handler(key):
    val = getattr(_thread_local, key, None)
    if val is not None:
        return val
    return _tool_handlers.get(key)


def _handle_execute_trade(params: dict, account_equity: float, positions: list) -> dict:
    broker = _get_handler("broker")
    risk = _get_handler("risk")

    if not broker:
        return {"success": False, "error": "Broker not connected"}

    if risk and risk.kill_switch_active:
        return {"success": False, "error": "Kill switch is active — all trading halted"}

    symbol = params["symbol"]
    side = params["side"]
    qty = params["qty"]
    order_type = params.get("order_type", "market")
    limit_price = params.get("limit_price")
    reasoning = params.get("reasoning", "No reasoning provided")

    with _trade_lock:
        if risk:
            try:
                latest_quote = broker.get_latest_quote(symbol)
                price = latest_quote["mid"] if latest_quote else 0
            except Exception:
                price = 0

            try:
                fresh_positions = broker.get_current_positions() or positions
            except Exception:
                fresh_positions = positions

            try:
                acct = broker.get_account_balance()
                if acct:
                    account_equity = acct["portfolio_value"]
            except Exception:
                pass

            approved, reason = risk.approve_trade(side, symbol, qty, price, account_equity, fresh_positions)
            if not approved:
                log_event("agent", f"Trade blocked by risk manager: {reason}", "warning")
                return {"success": False, "error": f"Risk manager blocked: {reason}"}

        result = broker.submit_order(symbol, qty, side, order_type, limit_price, notes=f"Agent: {reasoning[:100]}")
        if result:
            log_event("agent", f"Trade executed: {side.upper()} {qty} {symbol} — {reasoning[:80]}", "info")
            return {"success": True, "order": result}
        else:
            return {"success": False, "error": "Order submission failed — check broker logs"}


def _handle_get_market_analysis(params: dict) -> dict:
    analysis_fn = _get_handler("analysis_fn")
    if not analysis_fn:
        return {"error": "Analysis function not registered"}

    symbol = params["symbol"]
    timeframe = params.get("timeframe", "1d")
    bars = params.get("bars", 200)

    try:
        result = analysis_fn(symbol, timeframe, bars)
        return result if result else {"error": f"No data available for {symbol}"}
    except Exception as e:
        return {"error": f"Analysis failed: {str(e)}"}


def _handle_log_reasoning(params: dict) -> dict:
    symbol = params["symbol"]
    action = params["action"]
    thought = params["thought_process"]
    signal_type = params.get("signal_type", "analysis")
    confidence = params.get("confidence", 0.0)

    entry_id = log_reasoning(
        symbol=symbol,
        action=action,
        reasoning=thought,
        signal_type=signal_type,
        confidence=confidence,
        indicators=None,
    )
    log_event("agent", f"Reasoning logged for {symbol}: {action} ({confidence:.0%} confidence)", "info")
    return {"success": True, "ledger_entry_id": entry_id}


def _handle_rebalance_portfolio(params: dict, account_equity: float, positions: list) -> dict:
    target = params.get("target_allocations", {})
    tolerance = params.get("tolerance_pct", 5.0)

    if not target:
        return {"error": "No target allocations provided"}

    current = {}
    total_value = sum(abs(p.get("market_value", 0)) for p in positions)
    cash = account_equity - total_value

    for p in positions:
        sym = p["symbol"]
        val = abs(p.get("market_value", 0))
        current[sym] = {
            "value": val,
            "pct": round(val / account_equity * 100, 2) if account_equity > 0 else 0,
            "qty": p.get("qty", 0),
            "price": p.get("current_price", 0),
        }

    suggestions = []
    for sym, target_pct in target.items():
        current_pct = current.get(sym, {}).get("pct", 0)
        diff = target_pct - current_pct

        if abs(diff) > tolerance:
            target_value = account_equity * target_pct / 100
            current_value = current.get(sym, {}).get("value", 0)
            trade_value = target_value - current_value
            price = current.get(sym, {}).get("price", 0)

            if price <= 0:
                broker = _get_handler("broker")
                if broker:
                    try:
                        q = broker.get_latest_quote(sym)
                        price = q["mid"] if q else 0
                    except Exception:
                        pass

            qty = int(abs(trade_value) / price) if price > 0 else 0
            suggestions.append({
                "symbol": sym,
                "current_pct": current_pct,
                "target_pct": target_pct,
                "deviation": round(diff, 2),
                "action": "buy" if diff > 0 else "sell",
                "suggested_qty": qty,
                "trade_value": round(abs(trade_value), 2),
            })

    return {
        "account_equity": account_equity,
        "cash_available": round(cash, 2),
        "total_invested": round(total_value, 2),
        "current_allocations": {s: d["pct"] for s, d in current.items()},
        "rebalance_suggestions": sorted(suggestions, key=lambda x: abs(x["deviation"]), reverse=True),
        "needs_rebalancing": len(suggestions) > 0,
    }


def _handle_sector_rotation(params: dict) -> dict:
    from trading.ui.charts import fetch_yfinance

    sectors = {
        "XLK": "Technology", "XLF": "Financials", "XLE": "Energy",
        "XLV": "Healthcare", "XLI": "Industrials", "XLP": "Consumer Staples",
        "XLU": "Utilities", "XLY": "Consumer Discretionary", "XLC": "Communication",
        "XLRE": "Real Estate", "XLB": "Materials",
    }

    lookback = params.get("lookback_days", 20)
    results = []

    for sym, name in sectors.items():
        try:
            df = fetch_yfinance(sym, "1d", lookback + 5)
            if df is not None and len(df) >= 2:
                start_price = df.iloc[0]["close"]
                end_price = df.iloc[-1]["close"]
                perf = (end_price - start_price) / start_price * 100
                results.append({
                    "symbol": sym,
                    "sector": name,
                    "performance_pct": round(perf, 2),
                    "current_price": round(end_price, 2),
                })
        except Exception:
            pass

    results.sort(key=lambda x: x["performance_pct"], reverse=True)

    leaders = results[:3] if results else []
    laggards = results[-3:] if len(results) >= 3 else []

    spread = results[0]["performance_pct"] - results[-1]["performance_pct"] if len(results) >= 2 else 0

    return {
        "lookback_days": lookback,
        "sectors": results,
        "leaders": [f"{r['sector']} ({r['symbol']}) +{r['performance_pct']:.1f}%" for r in leaders],
        "laggards": [f"{r['sector']} ({r['symbol']}) {r['performance_pct']:.1f}%" for r in laggards],
        "rotation_spread": round(spread, 2),
        "rotation_signal": "strong" if spread > 10 else "moderate" if spread > 5 else "weak",
    }


def _handle_news_sentiment(params: dict) -> dict:
    import yfinance as yf

    symbol = params["symbol"]
    try:
        ticker = yf.Ticker(symbol)
        news = ticker.news or []

        headlines = []
        for item in news[:10]:
            content = item.get("content", {})
            headlines.append({
                "title": content.get("title", item.get("title", "No title")),
                "publisher": content.get("provider", {}).get("displayName", "Unknown"),
            })

        info = ticker.info or {}
        company_info = {
            "name": info.get("longName", symbol),
            "sector": info.get("sector", "Unknown"),
            "industry": info.get("industry", "Unknown"),
            "market_cap": info.get("marketCap", 0),
            "pe_ratio": info.get("trailingPE", None),
            "forward_pe": info.get("forwardPE", None),
            "dividend_yield": info.get("dividendYield", None),
            "52w_high": info.get("fiftyTwoWeekHigh", None),
            "52w_low": info.get("fiftyTwoWeekLow", None),
            "avg_volume": info.get("averageVolume", None),
            "recommendation": info.get("recommendationKey", "none"),
        }

        recs = None
        try:
            rec_df = ticker.recommendations
            if rec_df is not None and len(rec_df) > 0:
                latest = rec_df.iloc[-1]
                recs = {k: int(v) if isinstance(v, (int, float)) else str(v) for k, v in latest.items()}
        except Exception:
            pass

        return {
            "symbol": symbol,
            "headlines": headlines,
            "company_info": company_info,
            "analyst_recommendations": recs,
            "headline_count": len(headlines),
        }
    except Exception as e:
        return {"error": f"News fetch failed for {symbol}: {str(e)}"}


def _handle_multi_timeframe(params: dict) -> dict:
    from trading.ui.charts import fetch_yfinance, compute_indicators, get_indicator_summary

    symbol = params["symbol"]
    timeframes = {"15m": 100, "1h": 200, "1d": 200}
    results = {}

    for tf, bars in timeframes.items():
        try:
            df = fetch_yfinance(symbol, tf, bars)
            if df is not None and len(df) >= 20:
                df = compute_indicators(df)
                summary = get_indicator_summary(df)
                ema_stack = "bullish" if summary["ema_bullish_stack"] else ("bearish" if summary["ema_bearish_stack"] else "mixed")

                results[tf] = {
                    "price": summary["price"],
                    "rsi": round(summary["rsi"], 1),
                    "ema_stack": ema_stack,
                    "macd_hist": round(summary["macd_hist"], 6),
                    "bb_pct_b": round(summary["bb_pct_b"], 3),
                    "atr": round(summary["atr"], 4),
                    "above_200": summary["above_200"],
                    "bb_squeeze": summary["bb_squeeze"],
                    "trend": "bullish" if summary["rsi"] > 50 and ema_stack == "bullish" else "bearish" if summary["rsi"] < 50 and ema_stack == "bearish" else "neutral",
                }
        except Exception:
            results[tf] = None

    trends = [r["trend"] for r in results.values() if r]
    bullish_count = trends.count("bullish")
    bearish_count = trends.count("bearish")
    total = len(trends)

    if bullish_count == total and total > 0:
        alignment = "full_bullish"
        confluence = 1.0
    elif bearish_count == total and total > 0:
        alignment = "full_bearish"
        confluence = 1.0
    elif bullish_count > bearish_count:
        alignment = "mostly_bullish"
        confluence = bullish_count / total if total > 0 else 0
    elif bearish_count > bullish_count:
        alignment = "mostly_bearish"
        confluence = bearish_count / total if total > 0 else 0
    else:
        alignment = "mixed"
        confluence = 0.0

    return {
        "symbol": symbol,
        "timeframes": results,
        "alignment": alignment,
        "confluence_score": round(confluence, 2),
        "recommendation": f"{'Strong' if confluence >= 0.8 else 'Moderate' if confluence >= 0.5 else 'Weak'} {alignment.replace('_', ' ')} signal across {total} timeframes",
    }


def _handle_recall_memory(params: dict) -> dict:
    from trading.services.agent_memory import recall_decisions, recall_trades, get_symbol_track_record

    symbol = params.get("symbol")
    days = params.get("lookback_days", 30)
    include_trades = params.get("include_trades", True)

    result = {}

    decisions = recall_decisions(symbol=symbol, limit=10, days=days)
    result["past_decisions"] = decisions

    if include_trades:
        trades = recall_trades(symbol=symbol, limit=10, days=days)
        result["trade_history"] = trades

    if symbol:
        track = get_symbol_track_record(symbol)
        result["track_record"] = track

    return result


def _handle_get_annotations(params: dict) -> dict:
    from trading.services.broker import get_active_annotations
    symbol = params.get("symbol")
    annotations = get_active_annotations(symbol=symbol)
    return {
        "annotations": annotations,
        "count": len(annotations),
        "note": "These are price levels manually identified by the operator on the chart."
    }


def _process_tool_call(tool_name: str, tool_input: dict, account_equity: float, positions: list) -> str:
    if tool_name == "execute_trade":
        result = _handle_execute_trade(tool_input, account_equity, positions)
    elif tool_name == "get_market_analysis":
        result = _handle_get_market_analysis(tool_input)
    elif tool_name == "log_alchemical_reasoning":
        result = _handle_log_reasoning(tool_input)
    elif tool_name == "rebalance_portfolio":
        result = _handle_rebalance_portfolio(tool_input, account_equity, positions)
    elif tool_name == "analyze_sector_rotation":
        result = _handle_sector_rotation(tool_input)
    elif tool_name == "get_news_sentiment":
        result = _handle_news_sentiment(tool_input)
    elif tool_name == "get_multi_timeframe_analysis":
        result = _handle_multi_timeframe(tool_input)
    elif tool_name == "recall_past_decisions":
        result = _handle_recall_memory(tool_input)
    elif tool_name == "get_active_annotations":
        result = _handle_get_annotations(tool_input)
    else:
        result = {"error": f"Unknown tool: {tool_name}"}

    return json.dumps(result, default=str)


def run_agent_cycle(
    watchlist: list[str],
    market_context: dict,
    account_equity: float,
    positions: list,
    risk_status: dict,
    max_tool_rounds: int = 8,
) -> dict:
    positions_str = json.dumps(positions[:10], indent=2) if positions else "No positions"
    watchlist_str = ", ".join(watchlist)

    context_lines = []
    for sym, data in market_context.items():
        if data:
            price = data.get("price", 0)
            rsi = data.get("rsi", 0)
            ema_stack = data.get("ema_stack", "unknown")
            atr = data.get("atr", 0)
            bb_pct = data.get("bb_pct_b", 0)
            macd_h = data.get("macd_hist", 0)
            squeeze = "🔥 SQUEEZE" if data.get("bb_squeeze") else ""
            above_200 = "↑200" if data.get("above_200") else "↓200"
            context_lines.append(
                f"  {sym}: ${price:.2f} | RSI {rsi:.1f} | EMA {ema_stack} | ATR {atr:.4f} | BB%B {bb_pct:.3f} | MACD-H {macd_h:.6f} | {above_200} {squeeze}"
            )

    context_block = "\n".join(context_lines) if context_lines else "  No market data available — use get_market_analysis to fetch"

    memory_block = ""
    try:
        from trading.services.agent_memory import build_memory_context
        memory_block = build_memory_context(watchlist)
    except Exception:
        memory_block = ""

    user_message = f"""AUTONOMOUS CYCLE — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

WATCHLIST: {watchlist_str}

MARKET SNAPSHOT:
{context_block}

ACCOUNT:
  Equity: ${account_equity:,.2f}
  Risk per trade: {risk_status.get('max_risk_pct', 0.02):.1%}
  ATR multiplier: {risk_status.get('atr_multiplier', 1.5)}
  Kill switch: {'🔴 ACTIVE' if risk_status.get('kill_switch') else '🟢 OFF'}

CURRENT POSITIONS:
{positions_str}

{memory_block}

AVAILABLE TOOLS (10 total):
- execute_trade — submit orders
- get_market_analysis — single-timeframe indicator data
- get_multi_timeframe_analysis — cross-reference 15m/1h/daily signals for confluence
- log_alchemical_reasoning — record your thought process
- rebalance_portfolio — analyze allocation vs targets
- analyze_sector_rotation — compare sector ETF performance
- get_news_sentiment — fetch headlines and analyst recommendations
- recall_past_decisions — search your memory for past reasoning and trade outcomes
- get_active_annotations — retrieve operator's manually identified support/resistance levels from the chart

Analyze the watchlist. For each symbol of interest:
1. Use recall_past_decisions to check your history with this symbol
2. Use get_active_annotations to check for operator-drawn support/resistance levels
3. Use get_multi_timeframe_analysis for confluence confirmation
4. Use get_market_analysis if you need deeper single-timeframe data
5. Log your reasoning with log_alchemical_reasoning
6. Execute trades only with high conviction (>70%)
7. If nothing meets your criteria, log a 'monitoring' or 'hold' entry explaining why

Begin your analysis."""

    messages = [{"role": "user", "content": user_message}]
    all_tool_calls = []
    all_reasoning = []
    final_text = ""

    for round_num in range(max_tool_rounds):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )
            _track_tokens(response)
        except Exception as e:
            log_event("agent", f"Claude API error in round {round_num}: {e}", "error")
            return {
                "success": False,
                "error": str(e),
                "rounds": round_num,
                "tool_calls": all_tool_calls,
                "reasoning": all_reasoning,
                "final_text": final_text,
            }

        tool_use_blocks = []
        for block in response.content:
            if block.type == "text":
                final_text += block.text + "\n"
            elif block.type == "tool_use":
                tool_use_blocks.append(block)
                all_tool_calls.append({
                    "round": round_num,
                    "tool": block.name,
                    "input": block.input,
                    "timestamp": datetime.now().isoformat(),
                })
                if block.name == "log_alchemical_reasoning":
                    all_reasoning.append({
                        "symbol": block.input.get("symbol"),
                        "action": block.input.get("action"),
                        "thought": block.input.get("thought_process", "")[:200],
                        "confidence": block.input.get("confidence", 0),
                    })

        if response.stop_reason == "end_turn" or not tool_use_blocks:
            break

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for tool_block in tool_use_blocks:
            result_str = _process_tool_call(
                tool_block.name,
                tool_block.input,
                account_equity,
                positions,
            )
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_block.id,
                "content": result_str,
            })

        messages.append({"role": "user", "content": tool_results})

    return {
        "success": True,
        "rounds": round_num + 1 if 'round_num' in dir() else 1,
        "tool_calls": all_tool_calls,
        "reasoning": all_reasoning,
        "final_text": final_text.strip(),
        "timestamp": datetime.now().isoformat(),
    }


def analyze_symbol(
    symbol: str,
    indicators: dict,
    account_equity: float,
    current_positions: list,
    support: float = None,
    ceiling: float = None,
) -> dict:
    positions_str = json.dumps(current_positions, indent=2) if current_positions else "None"

    levels_str = ""
    if support:
        levels_str += f"\n- Support line: ${support:.2f}"
    if ceiling:
        levels_str += f"\n- Ceiling line: ${ceiling:.2f}"

    user_content = f"""Analyze {symbol} and provide a trading decision.

CURRENT TECHNICAL STATE:
- Price: ${indicators.get('price', 0):.2f}
- ATR (14): {indicators.get('atr', 0):.4f}
- RSI (14): {indicators.get('rsi', 0):.2f}
- EMA 9 (Short): {indicators.get('ema_fast', indicators.get('ema9', 0)):.4f}
- EMA 50 (Medium): {indicators.get('ema_mid', indicators.get('ema50', 0)):.4f}
- EMA 200 (Long): {indicators.get('ema_slow', indicators.get('ema200', 0)):.4f}
- Bollinger Upper: {indicators.get('bb_upper', 0):.4f}
- Bollinger Middle: {indicators.get('bb_middle', indicators.get('bb_mid', 0)):.4f}
- Bollinger Lower: {indicators.get('bb_lower', 0):.4f}
- BB %B: {indicators.get('bb_pct_b', 0):.3f}
- BB Squeeze: {indicators.get('bb_squeeze', False)}
- MACD: {indicators.get('macd', 0):.6f}
- MACD Signal: {indicators.get('macd_signal', 0):.6f}
- MACD Histogram: {indicators.get('macd_hist', 0):.6f}
- EMA Stack: {indicators.get('ema_stack', 'unknown')}
- Above 200 EMA: {indicators.get('above_200', 'unknown')}
- VWAP: {indicators.get('vwap', 0):.4f}

ALGORITHMIC PRE-SIGNALS: {', '.join(indicators.get('signals', [])) or 'None detected'}

ACCOUNT EQUITY: ${account_equity:,.2f}
OPEN POSITIONS: {positions_str}
{f'MANUAL LEVELS:{levels_str}' if levels_str else ''}

First, log your reasoning using the log_alchemical_reasoning tool.
Then provide your trading decision. If you want to trade, use execute_trade.
If holding, explain why in your reasoning."""

    messages = [{"role": "user", "content": user_content}]

    result = {
        "action": "hold",
        "confidence": 0,
        "reasoning": "",
        "signal_type": "analysis",
        "entry_price": None,
        "stop_loss": None,
        "target_price": None,
        "risks": [],
        "time_horizon": "intraday",
    }

    for round_num in range(6):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )
            _track_tokens(response)
        except Exception as e:
            log_event("claude", f"Claude API error for {symbol}: {e}", "error")
            result["reasoning"] = f"API error: {e}"
            result["signal_type"] = "error"
            return result

        tool_use_blocks = []
        for block in response.content:
            if block.type == "text":
                text = block.text.strip()
                if text:
                    result["reasoning"] += text + "\n"

                    try:
                        parsed = json.loads(text)
                        if isinstance(parsed, dict) and "action" in parsed:
                            result.update({
                                "action": parsed.get("action", result["action"]),
                                "confidence": parsed.get("confidence", result["confidence"]),
                                "signal_type": parsed.get("signal_type", result["signal_type"]),
                                "entry_price": parsed.get("entry_price", result["entry_price"]),
                                "stop_loss": parsed.get("stop_loss", result["stop_loss"]),
                                "target_price": parsed.get("target_price", result["target_price"]),
                                "risks": parsed.get("risks", result["risks"]),
                                "time_horizon": parsed.get("time_horizon", result["time_horizon"]),
                            })
                    except (json.JSONDecodeError, ValueError):
                        pass

            elif block.type == "tool_use":
                tool_use_blocks.append(block)

                if block.name == "log_alchemical_reasoning":
                    inp = block.input
                    result["action"] = inp.get("action", result["action"])
                    result["confidence"] = inp.get("confidence", result["confidence"])
                    result["signal_type"] = inp.get("signal_type", result["signal_type"])
                    if not result["reasoning"]:
                        result["reasoning"] = inp.get("thought_process", "")

                elif block.name == "execute_trade":
                    inp = block.input
                    result["action"] = inp.get("side", result["action"])

        if response.stop_reason == "end_turn" or not tool_use_blocks:
            break

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for tool_block in tool_use_blocks:
            result_str = _process_tool_call(
                tool_block.name,
                tool_block.input,
                account_equity,
                current_positions,
            )
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_block.id,
                "content": result_str,
            })

        messages.append({"role": "user", "content": tool_results})

    if not result["reasoning"]:
        result["reasoning"] = "Analysis completed via tool-use loop."

    result["reasoning"] = result["reasoning"].strip()

    log_event("claude", f"Analysis for {symbol} → {result['action'].upper()} ({result['confidence']:.0%})", "info")
    return result
