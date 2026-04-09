"""
Political Trade Mirror Service
Integrates Capitol Trades scraping, politician ranking, and trade mirroring
into the Alchemical Trading Command Center.

Uses existing BrokerClient for execution and SQLite for persistence.
Respects kill switch and emergency stop protocol.
"""

import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
import schedule

from trading.services.broker import BrokerClient
from trading.services.capitol_fetcher import (
    fetch_history_for_ranking,
    fetch_recent_trades,
    filter_new_trades,
)
from trading.services.notifications import send_notification
from trading.services.politician_ranker import (
    get_top_politicians,
    load_scores,
    rank_politicians,
)
from trading.services.risk_manager import RiskManager
from trading.utils.config import ALPACA_API_KEY, ALPACA_SECRET_KEY
from trading.utils.database import SessionLocal, log_event

ALPACA_DATA_URL = "https://data.alpaca.markets"

TOP_N_POLITICIANS = 5
MAX_POSITION_SIZE_PCT = 0.05
MIRROR_STOP_LOSS_PCT = 0.05
MIRROR_TAKE_PROFIT_PCT = 0.12
MAX_OPEN_POSITIONS = 10
SKIP_IF_DISCLOSED_DAYS = 7


class PoliticalMirrorState:
    def __init__(self):
        self.running = False
        self.last_scan_time: Optional[str] = None
        self.scans_completed = 0
        self.trades_mirrored = 0
        self.trades_skipped = 0
        self.errors = 0
        self.last_scan_result: Optional[dict] = None
        self.status = "idle"
        self._lock = threading.Lock()
        self._scan_lock = threading.Lock()

    def update(self, **kwargs):
        with self._lock:
            for k, v in kwargs.items():
                setattr(self, k, v)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "last_scan_time": self.last_scan_time,
                "scans_completed": self.scans_completed,
                "trades_mirrored": self.trades_mirrored,
                "trades_skipped": self.trades_skipped,
                "errors": self.errors,
                "last_scan_result": self.last_scan_result,
                "status": self.status,
            }


_mirror_instance = None
_mirror_lock = threading.Lock()


class PoliticalMirrorService:
    @staticmethod
    def get_instance():
        global _mirror_instance
        if _mirror_instance is None:
            with _mirror_lock:
                if _mirror_instance is None:
                    _mirror_instance = PoliticalMirrorService()
        return _mirror_instance

    def __init__(self):
        self.state = PoliticalMirrorState()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.broker: Optional[BrokerClient] = None
        self.risk: Optional[RiskManager] = None
        self._ensure_tables()

    def _ensure_tables(self):
        db = SessionLocal()
        try:
            from sqlalchemy import text
            db.execute(text("""CREATE TABLE IF NOT EXISTS politician_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                politician_id TEXT NOT NULL,
                name TEXT NOT NULL,
                party TEXT DEFAULT '',
                chamber TEXT DEFAULT '',
                evaluated INTEGER DEFAULT 0,
                total_trades INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                win_rate REAL DEFAULT 0,
                avg_return REAL DEFAULT 0,
                score REAL DEFAULT 0
            )"""))
            db.execute(text("""CREATE TABLE IF NOT EXISTS seen_political_trades (
                tx_id INTEGER PRIMARY KEY,
                seen_at TEXT NOT NULL
            )"""))
            db.execute(text("""CREATE TABLE IF NOT EXISTS mirrored_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tx_id INTEGER NOT NULL,
                politician TEXT NOT NULL,
                party TEXT DEFAULT '',
                ticker TEXT NOT NULL,
                tx_type TEXT NOT NULL,
                order_id TEXT,
                qty INTEGER DEFAULT 0,
                price REAL DEFAULT 0,
                sl REAL DEFAULT 0,
                tp REAL DEFAULT 0,
                status TEXT DEFAULT 'executed',
                mirrored_at TEXT NOT NULL
            )"""))
            db.commit()
        except Exception as e:
            log_event("mirror", f"Table creation error: {e}", "error")
        finally:
            db.close()

    def _load_seen_ids(self) -> set:
        db = SessionLocal()
        try:
            from sqlalchemy import text
            rows = db.execute(text("SELECT tx_id FROM seen_political_trades")).fetchall()
            return {r[0] for r in rows}
        except Exception:
            return set()
        finally:
            db.close()

    def _mark_seen(self, tx_id: int):
        db = SessionLocal()
        try:
            from sqlalchemy import text
            db.execute(
                text("INSERT OR IGNORE INTO seen_political_trades (tx_id, seen_at) VALUES (:tid, :at)"),
                {"tid": tx_id, "at": datetime.now(timezone.utc).isoformat()},
            )
            db.commit()
        except Exception:
            pass
        finally:
            db.close()

    def _log_mirrored_trade(self, trade: dict, order: dict):
        db = SessionLocal()
        try:
            from sqlalchemy import text
            db.execute(
                text("""INSERT INTO mirrored_trades
                    (tx_id, politician, party, ticker, tx_type, order_id, qty, price, sl, tp, status, mirrored_at)
                    VALUES (:tx_id, :politician, :party, :ticker, :tx_type, :order_id, :qty, :price, :sl, :tp, :status, :at)"""),
                {
                    "tx_id": trade["txId"],
                    "politician": trade["politician"],
                    "party": trade.get("party", ""),
                    "ticker": trade["ticker"],
                    "tx_type": trade["txType"],
                    "order_id": order.get("order_id", ""),
                    "qty": order.get("qty", 0),
                    "price": order.get("price", 0),
                    "sl": order.get("sl", 0),
                    "tp": order.get("tp", 0),
                    "status": order.get("status", "submitted"),
                    "at": datetime.now(timezone.utc).isoformat(),
                },
            )
            db.commit()
        except Exception as e:
            log_event("mirror", f"Log trade error: {e}", "error")
        finally:
            db.close()

    def get_mirrored_trades(self, limit: int = 50) -> list:
        db = SessionLocal()
        try:
            from sqlalchemy import text
            rows = db.execute(
                text("SELECT * FROM mirrored_trades ORDER BY id DESC LIMIT :lim"),
                {"lim": limit},
            ).fetchall()
            return [
                {
                    "id": r[0], "tx_id": r[1], "politician": r[2], "party": r[3],
                    "ticker": r[4], "tx_type": r[5], "order_id": r[6], "qty": r[7],
                    "price": r[8], "sl": r[9], "tp": r[10], "status": r[11],
                    "mirrored_at": r[12],
                }
                for r in rows
            ]
        except Exception:
            return []
        finally:
            db.close()

    def _get_latest_price(self, ticker: str) -> float | None:
        headers = {
            "APCA-API-KEY-ID": ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
        }
        try:
            resp = requests.get(
                f"{ALPACA_DATA_URL}/v2/stocks/{ticker}/snapshot",
                headers=headers,
                timeout=8,
            )
            resp.raise_for_status()
            price = float(resp.json().get("latestTrade", {}).get("p", 0))
            return price if price > 0 else None
        except Exception:
            return None

    def _is_valid_ticker(self, ticker: str) -> bool:
        return bool(re.match(r"^[A-Z]{1,5}$", ticker))

    def _should_skip(self, trade: dict) -> str | None:
        ticker = trade["ticker"]
        tx_type = trade["txType"]

        if not self._is_valid_ticker(ticker):
            return f"Invalid ticker '{ticker}'"

        pub_date = _parse_date(trade["pubDate"])
        age_days = (datetime.now(timezone.utc) - pub_date).days
        if age_days > SKIP_IF_DISCLOSED_DAYS:
            return f"Disclosure is {age_days}d old (max {SKIP_IF_DISCLOSED_DAYS}d)"

        if self.broker:
            positions = self.broker.get_current_positions()
            if len(positions) >= MAX_OPEN_POSITIONS:
                return f"Max open positions ({MAX_OPEN_POSITIONS}) reached"

            held = [p for p in positions if p["symbol"] == ticker]
            if held:
                if tx_type == "buy" and any(p["side"] == "long" for p in held):
                    return f"Already long {ticker}"
                if tx_type == "sell" and any(p["side"] == "short" for p in held):
                    return f"Already short {ticker}"

        return None

    def mirror_trade(self, trade: dict) -> dict | None:
        if not self.broker:
            return None

        if self.risk and self.risk.kill_switch_active:
            log_event("mirror", "Trade blocked — kill switch active", "warning")
            return None

        ticker = trade["ticker"]
        tx_type = trade["txType"]
        tx_id = trade["txId"]

        skip_reason = self._should_skip(trade)
        if skip_reason:
            log_event("mirror", f"SKIP {ticker} ({trade['politician']}): {skip_reason}", "info")
            return None

        if not self.broker.is_market_open():
            log_event("mirror", f"Market closed — {ticker} deferred (will retry next scan)", "info")
            return None

        existing_orders = self.broker.get_open_orders()
        if any(o["symbol"] == ticker for o in existing_orders):
            log_event("mirror", f"BLOCKED — open order already exists for {ticker}", "info")
            self._mark_seen(tx_id)
            return None

        price = self._get_latest_price(ticker)
        if price is None or price <= 0:
            log_event("mirror", f"Cannot get price for {ticker} — will retry next scan", "warning")
            return None

        acct = self.broker.get_account_balance()
        equity = acct["equity"] if acct else 100_000
        notional = equity * MAX_POSITION_SIZE_PCT
        qty = max(1, int(notional / price))

        if tx_type == "buy":
            sl = round(price * (1 - MIRROR_STOP_LOSS_PCT), 2)
            tp = round(price * (1 + MIRROR_TAKE_PROFIT_PCT), 2)
        else:
            sl = round(price * (1 + MIRROR_STOP_LOSS_PCT), 2)
            tp = round(price * (1 - MIRROR_TAKE_PROFIT_PCT), 2)

        log_event(
            "mirror",
            f"{tx_type.upper()} {qty}x {ticker} @ ~${price:.2f} | SL=${sl:.2f} TP=${tp:.2f} | {trade['politician']} ({trade.get('party', '')})",
            "info",
        )

        side = "buy" if tx_type == "buy" else "sell"
        result = self.broker.submit_order(
            symbol=ticker,
            qty=qty,
            side=side,
            notes=f"Political mirror: {trade['politician']} {tx_type} (txId={tx_id})",
        )

        if result and result.get("order_id"):
            self._mark_seen(tx_id)
            order_data = {**result, "sl": sl, "tp": tp, "price": price}
            self._log_mirrored_trade(trade, order_data)
            send_notification(
                f"Political Mirror: {tx_type.upper()} {ticker}",
                f"{trade['politician']} ({trade.get('party', '')}) {tx_type} {ticker}. Mirrored {qty} shares @ ~${price:.2f}",
            )
            return order_data

        self._mark_seen(tx_id)
        log_event("mirror", f"Order for {ticker} failed — marking as seen to avoid retry loop", "warning")
        return None

    def run_scan(self) -> dict:
        if self.risk and self.risk.kill_switch_active:
            log_event("mirror", "Scan blocked — kill switch active", "warning")
            return {"error": "Kill switch active"}

        if not self.state._scan_lock.acquire(blocking=False):
            log_event("mirror", "Scan already in progress — skipping", "info")
            return {"error": "Scan already in progress"}

        try:
            return self._run_scan_inner()
        finally:
            self.state._scan_lock.release()

    def _run_scan_inner(self) -> dict:
        self.state.update(status="scanning")
        log_event("mirror", "Running political trade scan...", "info")

        top = get_top_politicians(TOP_N_POLITICIANS)
        if not top:
            log_event("mirror", "No politician scores — need to build rankings first.", "warning")
            self.state.update(status="idle")
            return {"error": "No politician rankings available"}

        top_ids = {p["politicianId"] for p in top}

        recent = fetch_recent_trades(pages=2)
        if not recent:
            log_event("mirror", "Failed to fetch recent Capitol Trades data.", "error")
            self.state.update(status="idle", errors=self.state.errors + 1)
            return {"error": "Failed to fetch trades"}

        seen_ids = self._load_seen_ids()
        new_trades = filter_new_trades(recent, seen_ids)

        executed = []
        skipped = 0
        for trade in new_trades:
            if trade["politicianId"] not in top_ids:
                self._mark_seen(trade["txId"])
                skipped += 1
                continue

            if self.risk and self.risk.kill_switch_active:
                log_event("mirror", "Kill switch activated during scan — aborting", "warning")
                break

            result = self.mirror_trade(trade)
            if result:
                executed.append({**trade, "order": result})
                time.sleep(0.5)
            else:
                skipped += 1

        scan_result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_fetched": len(recent),
            "new_trades": len(new_trades),
            "executed": len(executed),
            "skipped": skipped,
            "top_politicians": [p["politician"] for p in top[:5]],
        }

        self.state.update(
            last_scan_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            scans_completed=self.state.scans_completed + 1,
            trades_mirrored=self.state.trades_mirrored + len(executed),
            trades_skipped=self.state.trades_skipped + skipped,
            last_scan_result=scan_result,
            status="idle",
        )

        if executed:
            log_event("mirror", f"Mirrored {len(executed)} political trade(s).", "info")
        else:
            log_event("mirror", f"Scan complete — {len(new_trades)} new, 0 mirrored.", "info")

        return scan_result

    def build_rankings(self) -> list:
        self.state.update(status="building rankings")
        log_event("mirror", "Building politician rankings...", "info")

        history = fetch_history_for_ranking()
        if not history:
            log_event("mirror", "Failed to fetch trade history for ranking.", "error")
            self.state.update(status="idle", errors=self.state.errors + 1)
            return []

        scores = rank_politicians(history)
        self.state.update(status="idle")
        return scores

    def start(self, broker: BrokerClient, risk: RiskManager):
        if self.state.running:
            return

        self.broker = broker
        self.risk = risk
        self._stop_event.clear()
        self.state.update(running=True, status="starting")

        if not load_scores():
            self.build_rankings()

        def loop():
            try:
                self.run_scan()
            except Exception as e:
                log_event("mirror", f"Initial scan error: {e}", "error")
                self.state.update(errors=self.state.errors + 1)

            schedule.every(4).hours.do(self.run_scan)
            schedule.every().sunday.at("00:00").do(self.build_rankings)

            while not self._stop_event.is_set():
                if self.risk and self.risk.kill_switch_active:
                    self.state.update(status="paused (kill switch)")
                    self._stop_event.wait(timeout=60)
                    continue

                try:
                    schedule.run_pending()
                except Exception as e:
                    log_event("mirror", f"Scheduled job error: {e}", "error")
                    self.state.update(errors=self.state.errors + 1)

                self._stop_event.wait(timeout=60)

            self.state.update(running=False, status="stopped")
            schedule.clear()
            log_event("mirror", "Political Mirror service stopped.", "info")

        self._thread = threading.Thread(target=loop, daemon=True, name="political-mirror")
        self._thread.start()
        log_event("mirror", "Political Mirror service started.", "info")

    def stop(self):
        self._stop_event.set()
        self.state.update(status="stopping")
        log_event("mirror", "Political Mirror stop requested.", "info")


def _parse_date(date_str: str) -> datetime:
    if "T" in date_str:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    else:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
