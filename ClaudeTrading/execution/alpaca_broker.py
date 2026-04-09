"""
Alpaca Broker — Execution Layer
Wraps alpaca-py to provide clean order placement, position management,
and account information. All orders use bracket orders (entry + SL + TP)
so risk is always defined the moment a trade is placed.
"""

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest, LimitOrderRequest,
    TakeProfitRequest, StopLossRequest,
    GetOrdersRequest, ClosePositionRequest
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL


# Singleton clients
_trading_client = None
_data_client    = None


def _get_trading_client() -> TradingClient:
    global _trading_client
    if _trading_client is None:
        _trading_client = TradingClient(
            api_key=ALPACA_API_KEY,
            secret_key=ALPACA_SECRET_KEY,
            paper=True   # Always paper for now; change to False for live
        )
    return _trading_client


def _get_data_client() -> StockHistoricalDataClient:
    global _data_client
    if _data_client is None:
        _data_client = StockHistoricalDataClient(
            api_key=ALPACA_API_KEY,
            secret_key=ALPACA_SECRET_KEY
        )
    return _data_client


# ──────────────────────────────────────────────────────────────
# Account
# ──────────────────────────────────────────────────────────────

def get_account() -> dict:
    """Return account details including equity and buying power."""
    acct = _get_trading_client().get_account()
    return {
        "equity":        float(acct.equity),
        "cash":          float(acct.cash),
        "buying_power":  float(acct.buying_power),
        "portfolio_value": float(acct.portfolio_value),
        "daytrade_count": int(acct.daytrade_count),
    }


def get_equity() -> float:
    return get_account()["equity"]


# ──────────────────────────────────────────────────────────────
# Positions
# ──────────────────────────────────────────────────────────────

def get_positions() -> list:
    """Return list of open position dicts."""
    positions = _get_trading_client().get_all_positions()
    result = []
    for p in positions:
        result.append({
            "symbol":       p.symbol,
            "qty":          float(p.qty),
            "side":         p.side.value,
            "avg_cost":     float(p.avg_entry_price),
            "market_value": float(p.market_value),
            "unrealized_pl":float(p.unrealized_pl),
            "unrealized_plpc": float(p.unrealized_plpc),
        })
    return result


def get_position(symbol: str) -> dict | None:
    """Return a specific position or None if not held."""
    try:
        p = _get_trading_client().get_open_position(symbol)
        return {
            "symbol":       p.symbol,
            "qty":          float(p.qty),
            "side":         p.side.value,
            "avg_cost":     float(p.avg_entry_price),
            "market_value": float(p.market_value),
            "unrealized_pl":float(p.unrealized_pl),
        }
    except Exception:
        return None


def close_position(symbol: str) -> dict:
    """Market-close an open position. Returns order response."""
    resp = _get_trading_client().close_position(symbol)
    return {"order_id": str(resp.id), "status": resp.status.value}


def close_all_positions() -> list:
    """Emergency close — used by kill switch."""
    orders = _get_trading_client().close_all_positions(cancel_orders=True)
    return [{"symbol": o.symbol, "order_id": str(o.id)} for o in orders]


# ──────────────────────────────────────────────────────────────
# Orders
# ──────────────────────────────────────────────────────────────

def place_bracket_order(symbol: str, qty: int, side: str,
                         sl: float, tp: float) -> dict:
    """
    Place a bracket order: market entry + stop-loss + take-profit.

    Parameters
    ----------
    symbol : Ticker symbol
    qty    : Number of shares
    side   : 'BUY' or 'SELL'
    sl     : Stop-loss price
    tp     : Take-profit price

    Returns
    -------
    Order info dict including order_id and status
    """
    order_side = OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL

    order_req = MarketOrderRequest(
        symbol         = symbol,
        qty            = qty,
        side           = order_side,
        time_in_force  = TimeInForce.DAY,
        order_class    = "bracket",
        take_profit    = TakeProfitRequest(limit_price=round(tp, 2)),
        stop_loss      = StopLossRequest(stop_price=round(sl, 2)),
    )

    resp = _get_trading_client().submit_order(order_req)
    return {
        "order_id":  str(resp.id),
        "symbol":    resp.symbol,
        "qty":       float(resp.qty),
        "side":      resp.side.value,
        "status":    resp.status.value,
        "sl":        sl,
        "tp":        tp,
    }


def cancel_all_orders():
    """Cancel all open orders. Used by kill switch."""
    _get_trading_client().cancel_orders()


def get_open_orders(symbol: str = None) -> list:
    """Return list of open orders, optionally filtered by symbol."""
    req = GetOrdersRequest(status=OrderStatus.OPEN,
                           symbols=[symbol] if symbol else None)
    orders = _get_trading_client().get_orders(filter=req)
    return [{"order_id": str(o.id), "symbol": o.symbol,
             "side": o.side.value, "qty": float(o.qty),
             "status": o.status.value} for o in orders]


def is_market_open() -> bool:
    """Return True if the US stock market is currently open."""
    clock = _get_trading_client().get_clock()
    return clock.is_open
