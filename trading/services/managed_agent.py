import json
import secrets
import threading
import time
from datetime import datetime
from typing import Optional

from trading.services.agent_loop import AgentState, _fetch_analysis_for_tool
from trading.services.broker import BrokerClient
from trading.services.claude_brain import register_tool_handlers, run_agent_cycle
from trading.services.context_compiler import ContextCompiler
from trading.services.risk_manager import RiskManager
from trading.utils.database import log_event

TOKEN_BUDGET = 1_000_000
DEFAULT_RUNTIME_HOURS = 4
HEARTBEAT_INTERVAL = 30
CHECKPOINT_INTERVAL_CYCLES = 5


class ManagedAgent:
    def __init__(
        self,
        broker: Optional[BrokerClient] = None,
        risk: Optional[RiskManager] = None,
        watchlist: Optional[list] = None,
        runtime_hours: float = DEFAULT_RUNTIME_HOURS,
        cycle_interval: int = 300,
    ):
        self.broker = broker
        self.risk = risk or RiskManager()
        self.watchlist = watchlist or ["SPY", "QQQ", "AAPL"]
        self.runtime_hours = runtime_hours
        self.cycle_interval = cycle_interval

        self.session_id: Optional[str] = None
        self.session_token: Optional[str] = None
        self.api_key: Optional[str] = None

        self.state = AgentState()
        self.context_compiler: Optional[ContextCompiler] = None

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        self.start_time: Optional[float] = None
        self.last_heartbeat: Optional[float] = None
        self.heartbeat_latency_ms: float = 0
        self.token_usage: int = 0
        self.tool_call_log: list = []
        self.session_active = False
        self._state_lock = threading.Lock()

    def start_session(self, api_key: str) -> dict:
        with self._lock:
            if self.session_active:
                return {"error": "Session already active", "session_id": self.session_id}

            self.session_id = f"ma-{secrets.token_hex(8)}"
            self.session_token = secrets.token_urlsafe(32)
            self.api_key = api_key
            self.start_time = time.time()
            self.last_heartbeat = time.time()
            self.token_usage = 0
            self.tool_call_log = []
            self.session_active = True

            self.context_compiler = ContextCompiler(self.session_id)

            self.state = AgentState()
            self.state.update(running=True, status="session starting")

            self._stop_event = threading.Event()

            if self.broker:
                register_tool_handlers(self.broker, self.risk, _fetch_analysis_for_tool)

            self._thread = threading.Thread(
                target=self._run_loop, daemon=True, name=f"managed-agent-{self.session_id}"
            )
            self._thread.start()

            log_event(
                "managed_agent",
                f"Session started: {self.session_id} | Runtime: {self.runtime_hours}h | Interval: {self.cycle_interval}s",
                "info",
            )

            return {
                "session_id": self.session_id,
                "session_token": self.session_token,
                "runtime_hours": self.runtime_hours,
                "status": "started",
            }

    def heartbeat(self) -> dict:
        with self._state_lock:
            now = time.time()
            if self.last_heartbeat:
                self.heartbeat_latency_ms = (now - self.last_heartbeat) * 1000
            self.last_heartbeat = now

            runtime_elapsed = now - self.start_time if self.start_time else 0
            runtime_remaining = max(0, (self.runtime_hours * 3600) - runtime_elapsed)

            return {
                "session_id": self.session_id,
                "alive": self.session_active,
                "timestamp": datetime.utcnow().isoformat(),
                "latency_ms": round(self.heartbeat_latency_ms, 1),
                "runtime_elapsed_s": round(runtime_elapsed, 1),
                "runtime_remaining_s": round(runtime_remaining, 1),
                "cycle_count": self.state.cycle_count,
                "token_usage": self.token_usage,
                "status": self.state.status,
            }

    def terminate(self, force: bool = False) -> dict:
        with self._lock:
            if not self.session_active:
                return {"status": "already_terminated", "session_id": self.session_id}

            self._stop_event.set()
            self.session_active = False
            self.state.update(status="terminating")

            if self.context_compiler:
                try:
                    self.context_compiler.generate_daily_summary()
                except Exception:
                    pass

            if force and self.risk:
                self.risk.activate_kill_switch()
                if self.broker:
                    try:
                        self.broker.cancel_all_orders()
                    except Exception:
                        pass

            log_event(
                "managed_agent",
                f"Session terminated: {self.session_id} | Force: {force}",
                "warning" if force else "info",
            )

            return {
                "status": "terminated",
                "session_id": self.session_id,
                "cycles_completed": self.state.cycle_count,
                "token_usage": self.token_usage,
                "force": force,
            }

    def get_session_info(self) -> dict:
        with self._state_lock:
            runtime_elapsed = time.time() - self.start_time if self.start_time else 0
            runtime_budget = self.runtime_hours * 3600
            heartbeat_age = time.time() - self.last_heartbeat if self.last_heartbeat else 0

            return {
                "session_id": self.session_id,
                "active": self.session_active,
                "start_time": datetime.fromtimestamp(self.start_time).isoformat() if self.start_time else None,
                "runtime_elapsed_s": round(runtime_elapsed, 1),
                "runtime_budget_s": runtime_budget,
                "runtime_pct": round(runtime_elapsed / runtime_budget * 100, 2) if runtime_budget > 0 else 0,
                "cycle_count": self.state.cycle_count,
                "token_usage": self.token_usage,
                "token_budget": TOKEN_BUDGET,
                "token_pct": round(self.token_usage / TOKEN_BUDGET * 100, 2),
                "last_heartbeat": datetime.fromtimestamp(self.last_heartbeat).isoformat() if self.last_heartbeat else None,
                "heartbeat_age_s": round(heartbeat_age, 1),
                "heartbeat_latency_ms": round(self.heartbeat_latency_ms, 1),
                "status": self.state.status,
                "errors": self.state.errors,
                "total_tool_calls": self.state.total_tool_calls,
                "total_trades": self.state.total_trades,
                "recent_tool_calls": list(self.tool_call_log[-20:]),
            }

    def _append_tool_call(self, entry: dict):
        with self._state_lock:
            self.tool_call_log.append(entry)
            if len(self.tool_call_log) > 100:
                self.tool_call_log = self.tool_call_log[-100:]

    def validate_session_token(self, token: str) -> bool:
        return self.session_active and token == self.session_token

    def validate_api_key(self, key: str) -> bool:
        return key == self.api_key

    def broker_trade(self, symbol: str, side: str, qty: int) -> dict:
        if not self.session_active:
            return {"success": False, "error": "No active session"}

        if not self.broker:
            return {"success": False, "error": "Broker not connected"}

        if self.risk and self.risk.kill_switch_active:
            return {"success": False, "error": "Kill switch active"}

        start_ms = time.time()

        if self.risk:
            try:
                account_equity = 100_000.0
                positions = []
                acct = self.broker.get_account_balance()
                if acct:
                    account_equity = acct["portfolio_value"]
                positions = self.broker.get_current_positions() or []

                price = 0
                try:
                    q = self.broker.get_latest_quote(symbol)
                    price = q["mid"] if q else 0
                except Exception:
                    pass

                approved, reason = self.risk.approve_trade(
                    side, symbol, qty, price, account_equity, positions
                )
                if not approved:
                    return {"success": False, "error": f"Risk manager blocked: {reason}"}
            except Exception as e:
                return {"success": False, "error": f"Risk validation error: {e}"}

        result = self.broker.submit_order(
            symbol, qty, side, notes=f"ManagedAgent:{self.session_id}"
        )

        duration_ms = int((time.time() - start_ms) * 1000)

        self._append_tool_call({
            "timestamp": datetime.utcnow().isoformat(),
            "tool": "broker_trade",
            "input": {"symbol": symbol, "side": side, "qty": qty},
            "success": result is not None,
            "duration_ms": duration_ms,
        })

        if self.context_compiler:
            self.context_compiler.log_tool_call(
                "broker_trade",
                {"symbol": symbol, "side": side, "qty": qty},
                result or {"error": "failed"},
                duration_ms,
                success=result is not None,
            )

        if result:
            return {"success": True, "order": result}
        return {"success": False, "error": "Order submission failed"}

    def fetch_alchemical_context(self) -> dict:
        if not self.context_compiler:
            return {"error": "No active session"}

        start_ms = time.time()

        payload = self.context_compiler.get_context_payload(hours=24)

        support_levels = {}
        ceiling_levels = {}
        try:
            import streamlit as st
            support_levels = dict(st.session_state.get("support_levels", {}))
            ceiling_levels = dict(st.session_state.get("ceiling_levels", {}))
        except Exception:
            pass

        payload["user_levels"] = {
            "support": support_levels,
            "ceiling": ceiling_levels,
        }

        market_briefings = {}
        for sym in self.watchlist[:8]:
            try:
                data = _fetch_analysis_for_tool(sym, "1d", 200)
                if data:
                    market_briefings[sym] = data
            except Exception:
                pass

        payload["market_briefings"] = market_briefings

        duration_ms = int((time.time() - start_ms) * 1000)

        self._append_tool_call({
            "timestamp": datetime.utcnow().isoformat(),
            "tool": "fetch_alchemical_context",
            "input": {"hours": 24},
            "success": True,
            "duration_ms": duration_ms,
        })

        if self.context_compiler:
            self.context_compiler.log_tool_call(
                "fetch_alchemical_context", {"hours": 24}, {"entries": len(payload.get("reasoning_entries", []))},
                duration_ms,
            )

        return payload

    def _run_loop(self):
        self.state.update(status="running")
        log_event("managed_agent", f"Agent loop started for session {self.session_id}", "info")

        cycle_in_session = 0

        while not self._stop_event.is_set():
            runtime = time.time() - self.start_time if self.start_time else 0
            if runtime >= self.runtime_hours * 3600:
                log_event(
                    "managed_agent",
                    f"Runtime budget exhausted ({self.runtime_hours}h). Auto-terminating.",
                    "warning",
                )
                self.terminate()
                break

            if self.token_usage >= TOKEN_BUDGET:
                log_event(
                    "managed_agent",
                    f"Token budget exhausted ({TOKEN_BUDGET:,}). Auto-terminating.",
                    "warning",
                )
                self.terminate()
                break

            if self.risk and self.risk.kill_switch_active:
                self.state.update(status="paused (kill switch)")
                time.sleep(10)
                continue

            self.state.update(status="running cycle")
            cycle_start = time.time()

            account_equity = 100_000.0
            positions = []
            if self.broker:
                try:
                    acct = self.broker.get_account_balance()
                    if acct:
                        account_equity = acct["portfolio_value"]
                    positions = self.broker.get_current_positions() or []
                except Exception:
                    pass

            market_context = {}
            for sym in self.watchlist[:8]:
                try:
                    data = _fetch_analysis_for_tool(sym, "1d", 200)
                    if data:
                        market_context[sym] = data
                except Exception:
                    market_context[sym] = None

            risk_status = self.risk.get_status()

            try:
                result = run_agent_cycle(
                    watchlist=self.watchlist,
                    market_context=market_context,
                    account_equity=account_equity,
                    positions=positions,
                    risk_status=risk_status,
                )

                trade_count = sum(
                    1 for tc in result.get("tool_calls", []) if tc["tool"] == "execute_trade"
                )
                tool_count = len(result.get("tool_calls", []))

                estimated_tokens = tool_count * 500 + 1500
                with self._state_lock:
                    self.token_usage += estimated_tokens

                self.state.update(
                    last_cycle_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    last_cycle_result=result,
                    cycle_count=self.state.cycle_count + 1,
                    total_tool_calls=self.state.total_tool_calls + tool_count,
                    total_trades=self.state.total_trades + trade_count,
                    status="idle",
                )

                for tc in result.get("tool_calls", []):
                    self._append_tool_call({
                        "timestamp": tc.get("timestamp", datetime.utcnow().isoformat()),
                        "tool": tc["tool"],
                        "input": tc["input"],
                        "success": True,
                        "duration_ms": 0,
                    })

                duration = time.time() - cycle_start
                self.state.add_history({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "duration": f"{duration:.1f}s",
                    "tools": tool_count,
                    "trades": trade_count,
                    "rounds": result.get("rounds", 0),
                    "success": result.get("success", False),
                })

                cycle_in_session += 1

                if self.context_compiler and cycle_in_session % CHECKPOINT_INTERVAL_CYCLES == 0:
                    reasoning_texts = [
                        r.get("thought", "")[:100] for r in result.get("reasoning", [])
                    ]
                    self.context_compiler.save_checkpoint(
                        positions=positions,
                        open_orders=[],
                        market_context=market_context,
                        reasoning_summary=" | ".join(reasoning_texts),
                        token_usage=self.token_usage,
                        cycle_count=self.state.cycle_count,
                        account_equity=account_equity,
                    )

                log_event(
                    "managed_agent",
                    f"[{self.session_id}] Cycle #{self.state.cycle_count} — "
                    f"{tool_count} tools, {trade_count} trades, tokens: {self.token_usage:,}",
                    "info",
                )

            except Exception as e:
                self.state.update(errors=self.state.errors + 1, status="error")
                log_event("managed_agent", f"[{self.session_id}] Cycle error: {e}", "error")

            self.last_heartbeat = time.time()

            self.state.update(status=f"waiting ({self.cycle_interval}s)")
            self._stop_event.wait(timeout=self.cycle_interval)

        self.state.update(running=False, status="stopped")
        self.session_active = False
        log_event("managed_agent", f"Session {self.session_id} loop ended", "info")


MANAGED_AGENT_TOOL_SCHEMA = [
    {
        "name": "broker_trade",
        "description": "Submit a trade through the Alpaca broker with risk manager validation. Use for executing buy/sell orders during managed agent sessions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Ticker symbol (e.g. 'AAPL', 'SPY')",
                },
                "side": {
                    "type": "string",
                    "enum": ["buy", "sell"],
                    "description": "Buy or sell",
                },
                "qty": {
                    "type": "integer",
                    "description": "Number of shares",
                },
            },
            "required": ["symbol", "side", "qty"],
        },
    },
    {
        "name": "fetch_alchemical_context",
        "description": "Retrieve the last 24 hours of reasoning ledger entries, recent trades, market briefings, user-drawn support/ceiling lines, and daily summaries. Use to prime context with historical memory.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


_managed_agent_instance: Optional[ManagedAgent] = None
_instance_lock = threading.Lock()


def get_managed_agent() -> Optional[ManagedAgent]:
    return _managed_agent_instance


def set_managed_agent(agent: ManagedAgent):
    global _managed_agent_instance
    with _instance_lock:
        _managed_agent_instance = agent


def clear_managed_agent():
    global _managed_agent_instance
    with _instance_lock:
        _managed_agent_instance = None
