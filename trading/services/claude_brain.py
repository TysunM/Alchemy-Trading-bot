import json
import time
import logging
from datetime import datetime
from typing import Optional, Dict, List, Any

from trading.utils.config import ANTHROPIC_API_KEY
from anthropic import Anthropic

# Set up logging
logger = logging.getLogger(__name__)

# --- SYSTEM PROMPT ---
SYSTEM_PROMPT = """
You are the "Alchemical Trader," a world-class quantitative hedge fund manager. 
Your goal is to achieve superior risk-adjusted returns by combining technical analysis, 
sentiment data, and global macro-economic context.

## Advanced Tools
1. **Execute Trade** — Finalize a buy/sell order via Alpaca.
2. **Market Analysis** — Fetch technical indicators (EMA, RSI, MACD).
3. **Sentiment Analysis** — Check news and analyst ratings.
4. **Multi-Timeframe Analysis** — Cross-reference 15m, 1h, and Daily trends.
5. **Portfolio Rebalancing** — Check if positions drift from targets.
6. **Sector Rotation** — Monitor relative strength of sector ETFs.
7. **Memory Recall** — Search past reasoning and outcomes.
8. **Macro-Aware Risk** — Use `get_macro_regime` to calibrate your aggression.
   - **Recession/Inversion**: Drastically reduce position sizes; look for defensive assets like Gold or stay flat.
   - **High VIX (>25)**: Market fear is high. Wide stops are mandatory; reduce leverage.
   - **Expansionary**: Be more aggressive with Growth and Tech breakouts.

## Rules
- You MUST use `get_macro_regime` at the start of a session if market direction is unclear.
- ALWAYS record your thought process using `log_alchemical_reasoning`.
- High conviction (>70%) is required for any trade execution.
- If unsure, stay FLAT. Cash is a valid position.
- Your reasoning should be transparent, audit-ready, and detailed.
"""

# --- TOOLS DEFINITION ---
TOOLS = [
    {
        "name": "execute_trade",
        "description": "Submit a trade order through the Alpaca broker.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "side": {"type": "string", "enum": ["buy", "sell"]},
                "qty": {"type": "number"},
                "type": {"type": "string", "enum": ["market", "limit"]},
                "reason": {"type": "string"}
            },
            "required": ["symbol", "side", "qty", "reason"]
        }
    },
    {
        "name": "get_market_analysis",
        "description": "Retrieve technical indicators for a given symbol.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "timeframe": {"type": "string", "default": "1d"}
            },
            "required": ["symbol"]
        }
    },
    {
        "name": "log_alchemical_reasoning",
        "description": "Log the internal logic and 'alchemical' thought process for a decision.",
        "input_schema": {
            "type": "object",
            "properties": {
                "thought_process": {"type": "string"},
                "conviction_score": {"type": "number", "minimum": 0, "maximum": 100}
            },
            "required": ["thought_process", "conviction_score"]
        }
    },
    {
        "name": "get_macro_regime",
        "description": "Analyze the global macro environment, including yield curve, inflation proxies, and VIX.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    }
]

# --- TOOL HANDLERS ---
def _process_tool_call(tool_name: str, tool_input: Dict, account_equity: float):
    """Processes the tool calls requested by Claude."""
    try:
        if tool_name == "get_market_analysis":
            # This would call your existing technical analysis service
            return {"status": "success", "data": "Technical indicators fetched."}

        elif tool_name == "get_macro_regime":
            # Direct import to avoid circular dependency
            from trading.services.macro_engine import get_macro_regime_analysis
            return get_macro_regime_analysis()

        elif tool_name == "log_alchemical_reasoning":
            logger.info(f"ALCHEMICAL LOG: {tool_input.get('thought_process')}")
            return {"status": "logged"}

        elif tool_name == "execute_trade":
            # Integration with Alpaca Broker Client
            return {"status": "success", "order_id": "sim_12345", "message": "Trade simulated."}

        else:
            return {"error": f"Unknown tool: {tool_name}"}
    except Exception as e:
        return {"error": str(e)}

# --- MAIN AGENT CYCLE ---
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
    The main execution loop where Claude analyzes the market and makes decisions.
    """
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    
    # Prepare the initial environment summary
    env_summary = {
        "timestamp": datetime.now().isoformat(),
        "account_equity": account_equity,
        "positions": positions,
        "risk_status": risk_status,
        "macro_environment": macro_context or "Not yet analyzed. Use get_macro_regime."
    }

    messages = [
        {
            "role": "user",
            "content": f"Current Market State: {json.dumps(market_context)}\n\n"
                       f"Account & Macro State: {json.dumps(env_summary)}\n\n"
                       "Analyze the watchlist and the macro regime. Execute trades only if conviction is high."
        }
    ]

    for round_num in range(max_tool_rounds):
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages
        )

        # Process the response
        if response.stop_reason == "tool_use":
            # Extract tool calls
            tool_calls = [content for content in response.content if content.type == "tool_use"]
            
            # Add Claude's response to message history
            messages.append({"role": "assistant", "content": response.content})

            # Handle each tool call
            for tool in tool_calls:
                result = _process_tool_call(tool.name, tool.input, account_equity)
                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool.id,
                            "content": json.dumps(result)
                        }
                    ]
                })
        else:
            # Claude is finished or provided a text-only response
            return {"status": "completed", "final_response": response.content[0].text}

    return {"status": "max_rounds_reached", "message": "Agent cycle timed out."}
