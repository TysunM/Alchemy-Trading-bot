"""
Multi-Bot Manager — Create, configure, and deploy multiple trading bots.

Each bot runs its own independent agent loop with:
  - Custom name and strategy prompt
  - Its own watchlist
  - Its own risk parameters (risk %, ATR multiplier, max position %)
  - Its own cycle interval
  - Independent start/stop lifecycle
  - Its own AgentState for monitoring

Bots are persisted to SQLite so they survive restarts.
"""

import json
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

from trading.services.broker import BrokerClient
from trading.services.claude_brain import register_tool_handlers, run_agent_cycle
from trading.services.risk_manager import RiskManager
from trading.ui.charts import compute_indicators, fetch_yfinance, get_indicator_summary
from trading.utils.database import log_event, SessionLocal


STRATEGY_PRESETS = {
    "alchemical_default": {
        "label": "Alchemical Default",
        "description": "Triple EMA + Bollinger Bands + Fibonacci. ATR-based stops. Claude decides entry/exit with full reasoning.",
    },
    "momentum_rider": {
        "label": "Momentum Rider",
        "description": "Focus on RSI breakouts and MACD crossovers. High conviction entries only. Rides strong trends with trailing stops.",
    },
    "mean_reversion": {
        "label": "Mean Reversion",
        "description": "Buys oversold (RSI < 30, BB %B < 0) and sells overbought (RSI > 70, BB %B > 1). Targets BB midline. Tight stops.",
    },
    "scalper": {
        "label": "Scalper",
        "description": "Short timeframe analysis. Quick entries and exits. Small position sizes, high frequency. Uses 15-min and 1-hour charts.",
    },
    "political_mirror": {
        "label": "Political Mirror",
        "description": "Mirrors trades from top-ranked US politicians (STOCK Act disclosures). Scrapes Capitol Trades, ranks politicians by performance, auto-mirrors their trades with bracket orders (SL/TP).",
    },
    "custom": {
        "label": "Custom Strategy",
        "description": "Write your own strategy instructions for Claude to follow.",
    },
}


@dataclass
class BotConfig:
    bot_id: str = ""
    name: str = "Untitled Bot"
    strategy: str = "alchemical_default"
    custom_prompt: str = ""
    watchlist: list[str] = field(default_factory=lambda: ["SPY", "QQQ"])
    interval_seconds: int = 300
    risk_pct: float = 0.02
    atr_multiplier: float = 1.5
    max_position_pct: float = 0.10
    enabled: bool = False
    created_at: str = ""

    def __post_init__(self):
        if not self.bot_id:
            self.bot_id = str(uuid.uuid4())[:8]
        if not self.created_at:
            self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        d = dict(d)
        if isinstance(d.get("watchlist"), str):
            try:
                d["watchlist"] = json.loads(d["watchlist"])
            except (json.JSONDecodeError, TypeError):
                d["watchlist"] = [s.strip() for s in d["watchlist"].split(",")]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class BotState:
    def __init__(self, bot_id: str):
        self.bot_id = bot_id
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
                "bot_id": self.bot_id,
                "running": self.running,
                "last_cycle_time": self.last_cycle_time,
                "last_cycle_result": self.last_cycle_result,
                "cycle_count": self.cycle_count,
                "errors": self.errors,
                "total_tool_calls": self.total_tool_calls,
                "total_trades": self.total_trades,
                "status": self.status,
                "history": list(self.history[-10:]),
            }

    def add_history(self, entry: dict):
        with self._lock:
            self.history.append(entry)
            if len(self.history) > 30:
                self.history = self.history[-30:]


def _fetch_analysis(symbol: str, timeframe: str = "1d", bars: int = 200) -> Optional[dict]:
    df = fetch_yfinance(symbol, timeframe, bars)
    if df is None or len(df) < 20:
        return None
    df = compute_indicators(df)
    summary = get_indicator_summary(df)
    ema_stack = "bullish" if summary["ema_bullish_stack"] else ("bearish" if summary["ema_bearish_stack"] else "mixed")
    summary["ema_stack"] = ema_stack
    return summary


_singleton_instance = None
_singleton_lock = threading.Lock()


class BotManager:
    @staticmethod
    def get_instance():
        global _singleton_instance
        if _singleton_instance is None:
            with _singleton_lock:
                if _singleton_instance is None:
                    _singleton_instance = BotManager()
        return _singleton_instance

    def __init__(self):
        self.bots: dict[str, BotConfig] = {}
        self.states: dict[str, BotState] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._stop_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._ensure_table()
        self._load_bots()

    def _ensure_table(self):
        db = SessionLocal()
        try:
            db.execute(
                __import__("sqlalchemy").text(
                    """CREATE TABLE IF NOT EXISTS bot_configs (
                        bot_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        strategy TEXT NOT NULL DEFAULT 'alchemical_default',
                        custom_prompt TEXT DEFAULT '',
                        watchlist TEXT NOT NULL DEFAULT '["SPY","QQQ"]',
                        interval_seconds INTEGER DEFAULT 300,
                        risk_pct REAL DEFAULT 0.02,
                        atr_multiplier REAL DEFAULT 1.5,
                        max_position_pct REAL DEFAULT 0.10,
                        enabled INTEGER DEFAULT 0,
                        created_at TEXT DEFAULT ''
                    )"""
                )
            )
            db.commit()
        except Exception:
            pass
        finally:
            db.close()

    def _load_bots(self):
        db = SessionLocal()
        try:
            from sqlalchemy import text
            rows = db.execute(text("SELECT * FROM bot_configs")).fetchall()
            for row in rows:
                d = dict(row._mapping)
                d["watchlist"] = json.loads(d.get("watchlist", '["SPY"]'))
                d["enabled"] = bool(d.get("enabled", 0))
                config = BotConfig.from_dict(d)
                self.bots[config.bot_id] = config
                self.states[config.bot_id] = BotState(config.bot_id)
        except Exception:
            pass
        finally:
            db.close()

    def _save_bot(self, config: BotConfig):
        db = SessionLocal()
        try:
            from sqlalchemy import text
            db.execute(
                text("""INSERT OR REPLACE INTO bot_configs
                    (bot_id, name, strategy, custom_prompt, watchlist, interval_seconds,
                     risk_pct, atr_multiplier, max_position_pct, enabled, created_at)
                    VALUES (:bot_id, :name, :strategy, :custom_prompt, :watchlist,
                            :interval_seconds, :risk_pct, :atr_multiplier, :max_position_pct,
                            :enabled, :created_at)"""),
                {
                    "bot_id": config.bot_id,
                    "name": config.name,
                    "strategy": config.strategy,
                    "custom_prompt": config.custom_prompt,
                    "watchlist": json.dumps(config.watchlist),
                    "interval_seconds": config.interval_seconds,
                    "risk_pct": config.risk_pct,
                    "atr_multiplier": config.atr_multiplier,
                    "max_position_pct": config.max_position_pct,
                    "enabled": 1 if config.enabled else 0,
                    "created_at": config.created_at,
                },
            )
            db.commit()
        except Exception as e:
            log_event("bot_manager", f"Save error for {config.name}: {e}", "error")
        finally:
            db.close()

    def _delete_bot_db(self, bot_id: str):
        db = SessionLocal()
        try:
            from sqlalchemy import text
            db.execute(text("DELETE FROM bot_configs WHERE bot_id = :bid"), {"bid": bot_id})
            db.commit()
        except Exception:
            pass
        finally:
            db.close()

    def create_bot(self, config: BotConfig) -> str:
        with self._lock:
            self.bots[config.bot_id] = config
            self.states[config.bot_id] = BotState(config.bot_id)
            self._save_bot(config)
            log_event("bot_manager", f"Bot created: {config.name} ({config.bot_id})", "info")
            return config.bot_id

    def update_bot(self, bot_id: str, **kwargs):
        with self._lock:
            if bot_id in self.bots:
                for k, v in kwargs.items():
                    if hasattr(self.bots[bot_id], k):
                        setattr(self.bots[bot_id], k, v)
                self._save_bot(self.bots[bot_id])

    def delete_bot(self, bot_id: str):
        self.stop_bot(bot_id)
        with self._lock:
            self.bots.pop(bot_id, None)
            self.states.pop(bot_id, None)
            self._delete_bot_db(bot_id)
            log_event("bot_manager", f"Bot deleted: {bot_id}", "info")

    def start_bot(self, bot_id: str, broker: Optional[BrokerClient] = None) -> bool:
        with self._lock:
            if bot_id not in self.bots:
                return False

            config = self.bots[bot_id]
            state = self.states[bot_id]

            if bot_id in self._threads and self._threads[bot_id].is_alive():
                return False

            bot_risk = RiskManager(
                max_risk_pct=config.risk_pct,
                atr_multiplier=config.atr_multiplier,
                max_position_pct=config.max_position_pct,
            )

            register_tool_handlers(broker, bot_risk, _fetch_analysis)

            stop_event = threading.Event()
            self._stop_events[bot_id] = stop_event
            state.update(running=True, status="starting")
            config.enabled = True
            self._save_bot(config)

            log_event("bot_manager", f"Bot '{config.name}' starting — interval {config.interval_seconds}s", "info")

            def loop():
                while not stop_event.is_set():
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
                    for sym in config.watchlist[:8]:
                        try:
                            data = _fetch_analysis(sym, "1d", 200)
                            if data:
                                market_context[sym] = data
                        except Exception:
                            market_context[sym] = None

                    risk_status = bot_risk.get_status()

                    try:
                        result = run_agent_cycle(
                            watchlist=config.watchlist,
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

                        log_event("bot", f"[{config.name}] Cycle #{state.cycle_count} — {tool_count} tools, {trade_count} trades", "info")

                    except Exception as e:
                        state.update(errors=state.errors + 1, status="error")
                        log_event("bot", f"[{config.name}] Cycle error: {e}", "error")

                    state.update(status=f"waiting ({config.interval_seconds}s)")
                    stop_event.wait(timeout=config.interval_seconds)

                state.update(running=False, status="stopped")
                log_event("bot_manager", f"Bot '{config.name}' stopped", "info")

            thread = threading.Thread(target=loop, daemon=True, name=f"bot-{bot_id}")
            self._threads[bot_id] = thread
            thread.start()
            return True

    def stop_bot(self, bot_id: str):
        if bot_id in self._stop_events:
            self._stop_events[bot_id].set()
        if bot_id in self.bots:
            self.bots[bot_id].enabled = False
            self._save_bot(self.bots[bot_id])
        if bot_id in self.states:
            self.states[bot_id].update(status="stopping")
        log_event("bot_manager", f"Bot stop requested: {bot_id}", "info")

    def run_single_cycle(self, bot_id: str, broker: Optional[BrokerClient] = None):
        if bot_id not in self.bots:
            return

        config = self.bots[bot_id]
        state = self.states[bot_id]

        bot_risk = RiskManager(
            max_risk_pct=config.risk_pct,
            atr_multiplier=config.atr_multiplier,
            max_position_pct=config.max_position_pct,
        )
        register_tool_handlers(broker, bot_risk, _fetch_analysis)

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
        for sym in config.watchlist[:8]:
            try:
                data = _fetch_analysis(sym, "1d", 200)
                if data:
                    market_context[sym] = data
            except Exception:
                market_context[sym] = None

        try:
            result = run_agent_cycle(
                watchlist=config.watchlist,
                market_context=market_context,
                account_equity=account_equity,
                positions=positions,
                risk_status=bot_risk.get_status(),
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

        except Exception as e:
            state.update(errors=state.errors + 1, status="error")
            log_event("bot", f"[{config.name}] Single cycle error: {e}", "error")

    def stop_all(self):
        for bot_id in list(self._stop_events.keys()):
            self.stop_bot(bot_id)

    def get_all_snapshots(self) -> list[dict]:
        result = []
        for bot_id, config in self.bots.items():
            state = self.states.get(bot_id)
            snap = state.snapshot() if state else {}
            result.append({
                "config": config.to_dict(),
                "state": snap,
            })
        return result
