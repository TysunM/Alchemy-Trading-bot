import alpaca_trade_api as tradeapi

from trading.utils.config import ALPACA_API_KEY, ALPACA_BASE_URL, ALPACA_SECRET_KEY
from trading.utils.database import get_all_active_annotations, get_annotations_for_symbol, log_event, log_trade


class BrokerClient:
    def __init__(self):
        self.api = tradeapi.REST(
            key_id=ALPACA_API_KEY,
            secret_key=ALPACA_SECRET_KEY,
            base_url=ALPACA_BASE_URL,
            api_version="v2",
        )
        self._connected = None

    def _verify_connection(self):
        if self._connected is not None:
            return
        try:
            account = self.api.get_account()
            self._connected = account.status == "ACTIVE"
            log_event("broker", f"Connected to Alpaca — account status: {account.status}", "info")
        except Exception as e:
            self._connected = False
            log_event("broker", f"Broker connection failed: {e}", "error")

    @property
    def is_connected(self):
        return self._connected

    def get_account_balance(self):
        try:
            acct = self.api.get_account()
            return {
                "equity": float(acct.equity),
                "cash": float(acct.cash),
                "buying_power": float(acct.buying_power),
                "portfolio_value": float(acct.portfolio_value),
                "daytrade_count": int(acct.daytrade_count),
                "pattern_day_trader": acct.pattern_day_trader,
                "trading_blocked": acct.trading_blocked,
                "account_blocked": acct.account_blocked,
                "status": acct.status,
            }
        except Exception as e:
            log_event("broker", f"Failed to get account balance: {e}", "error")
            return None

    def get_current_positions(self):
        try:
            positions = self.api.list_positions()
            return [
                {
                    "symbol": p.symbol,
                    "qty": float(p.qty),
                    "side": p.side,
                    "avg_entry_price": float(p.avg_entry_price),
                    "current_price": float(p.current_price),
                    "market_value": float(p.market_value),
                    "unrealized_pl": float(p.unrealized_pl),
                    "unrealized_plpc": float(p.unrealized_plpc),
                    "cost_basis": float(p.cost_basis),
                }
                for p in positions
            ]
        except Exception as e:
            log_event("broker", f"Failed to get positions: {e}", "error")
            return []

    def get_open_orders(self):
        try:
            orders = self.api.list_orders(status="open")
            return [
                {
                    "id": o.id,
                    "symbol": o.symbol,
                    "qty": float(o.qty),
                    "side": o.side,
                    "type": o.type,
                    "status": o.status,
                    "submitted_at": str(o.submitted_at),
                    "limit_price": float(o.limit_price) if o.limit_price else None,
                }
                for o in orders
            ]
        except Exception as e:
            log_event("broker", f"Failed to get open orders: {e}", "error")
            return []

    def submit_order(self, symbol, qty, side, order_type="market", limit_price=None, notes=None):
        if qty <= 0:
            log_event("broker", f"Order rejected — qty must be > 0 (got {qty})", "warning")
            return None
        try:
            kwargs = dict(symbol=symbol, qty=qty, side=side, type=order_type, time_in_force="day")
            if order_type == "limit" and limit_price:
                kwargs["limit_price"] = str(round(limit_price, 2))

            order = self.api.submit_order(**kwargs)
            log_trade(
                symbol=symbol,
                side=side,
                qty=qty,
                price=limit_price,
                order_id=order.id,
                status="submitted",
                notes=notes,
            )
            log_event("broker", f"Order submitted: {side.upper()} {qty} {symbol} @ {order_type}", "info")
            return {"order_id": order.id, "status": order.status, "symbol": symbol, "side": side, "qty": qty}
        except Exception as e:
            log_event("broker", f"Order failed for {symbol}: {e}", "error")
            return None

    def cancel_all_orders(self):
        try:
            self.api.cancel_all_orders()
            log_event("broker", "All open orders cancelled (Kill Switch)", "warning")
            return True
        except Exception as e:
            log_event("broker", f"Failed to cancel orders: {e}", "error")
            return False

    def liquidate_all(self):
        try:
            self.api.close_all_positions()
            log_event("broker", "ALL POSITIONS LIQUIDATED — Kill Switch activated", "warning")
            return True
        except Exception as e:
            log_event("broker", f"Failed to liquidate positions: {e}", "error")
            return False

    def get_bars(self, symbol, timeframe="1Day", limit=100):
        try:
            bars = self.api.get_bars(symbol, timeframe, limit=limit).df
            return bars
        except Exception as e:
            log_event("broker", f"Failed to get bars for {symbol}: {e}", "error")
            return None

    def get_latest_quote(self, symbol):
        try:
            quote = self.api.get_latest_quote(symbol)
            return {
                "symbol": symbol,
                "ask": float(quote.ask_price),
                "bid": float(quote.bid_price),
                "mid": (float(quote.ask_price) + float(quote.bid_price)) / 2,
            }
        except Exception as e:
            log_event("broker", f"Failed to get quote for {symbol}: {e}", "error")
            return None

    def is_market_open(self):
        try:
            clock = self.api.get_clock()
            return clock.is_open
        except Exception:
            return False


def get_active_annotations(symbol=None):
    try:
        if symbol:
            annotations = get_annotations_for_symbol(symbol)
        else:
            annotations = get_all_active_annotations()
        return [
            {
                "id": a.id,
                "symbol": a.symbol,
                "price_level": a.price_level,
                "annotation_type": a.annotation_type,
                "notes": a.notes,
                "timestamp": str(a.timestamp),
            }
            for a in annotations
        ]
    except Exception as e:
        log_event("annotations", f"Failed to get annotations: {e}", "error")
        return []
