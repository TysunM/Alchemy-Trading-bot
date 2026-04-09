"""
Strategy Backtester — Test trading strategies against historical data.

Supports configurable strategies with entry/exit rules based on indicators.
Tracks simulated P&L, win rate, max drawdown, Sharpe ratio, and trade log.
Uses yfinance historical data and the same indicator engine as live trading.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from trading.ui.charts import compute_indicators, fetch_yfinance


@dataclass
class BacktestConfig:
    symbol: str = "SPY"
    strategy: str = "ema_crossover"
    timeframe: str = "1d"
    bars: int = 500
    initial_capital: float = 100_000.0
    risk_pct: float = 0.02
    atr_multiplier: float = 1.5
    max_position_pct: float = 0.10
    commission_per_share: float = 0.0
    ema_fast: int = 9
    ema_slow: int = 50
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    bb_entry_threshold: float = 0.0
    bb_exit_threshold: float = 1.0


@dataclass
class BacktestTrade:
    entry_date: str
    exit_date: str
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    qty: int
    pnl: float
    pnl_pct: float
    hold_bars: int
    exit_reason: str


@dataclass
class BacktestResult:
    config: BacktestConfig
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    total_return: float = 0.0
    total_return_pct: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    avg_hold_bars: float = 0.0
    buy_and_hold_return: float = 0.0
    buy_and_hold_pct: float = 0.0


STRATEGY_REGISTRY = {
    "ema_crossover": "EMA Crossover — Buy when fast EMA crosses above slow EMA, sell on cross below",
    "mean_reversion": "Mean Reversion — Buy at BB lower band (oversold RSI), sell at BB upper band (overbought RSI)",
    "momentum": "Momentum — Buy on RSI breakout + MACD histogram positive, sell on reversal",
    "triple_ema_trend": "Triple EMA Trend — Trade only in direction of 9/50/200 EMA stack alignment",
    "bb_squeeze": "Bollinger Squeeze — Enter on BB squeeze breakout in direction of EMA trend",
}


def _calculate_position_size(equity: float, atr: float, risk_pct: float, atr_mult: float, price: float, max_pct: float) -> int:
    if atr <= 0 or price <= 0:
        return 0
    risk_dollars = equity * risk_pct
    stop_distance = atr * atr_mult
    shares = int(risk_dollars / stop_distance)
    max_shares = int(equity * max_pct / price)
    return max(1, min(shares, max_shares))


def run_backtest(config: BacktestConfig) -> Optional[BacktestResult]:
    df = fetch_yfinance(config.symbol, config.timeframe, config.bars)
    if df is None or len(df) < 50:
        return None

    df = compute_indicators(df)
    df = df.dropna(subset=["ema9", "ema50", "rsi", "atr"]).reset_index(drop=True)

    if len(df) < 30:
        return None

    result = BacktestResult(config=config)
    equity = config.initial_capital
    position = None
    equity_curve = []
    dates = []

    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]
        price = row["close"]
        date_str = str(row.name) if hasattr(row, "name") else str(i)
        try:
            date_str = pd.Timestamp(df.index[i]).strftime("%Y-%m-%d")
        except Exception:
            date_str = str(i)

        if position:
            current_pnl = (price - position["entry_price"]) * position["qty"] if position["side"] == "buy" else (position["entry_price"] - price) * position["qty"]
            unrealized = equity + current_pnl
        else:
            unrealized = equity

        equity_curve.append(unrealized)
        dates.append(date_str)

        if position:
            exit_signal, exit_reason = _check_exit(config, row, prev, position)
            if exit_signal:
                if position["side"] == "buy":
                    pnl = (price - position["entry_price"]) * position["qty"]
                else:
                    pnl = (position["entry_price"] - price) * position["qty"]

                pnl -= config.commission_per_share * position["qty"] * 2
                pnl_pct = pnl / (position["entry_price"] * position["qty"]) * 100

                trade = BacktestTrade(
                    entry_date=position["entry_date"],
                    exit_date=date_str,
                    symbol=config.symbol,
                    side=position["side"],
                    entry_price=position["entry_price"],
                    exit_price=price,
                    qty=position["qty"],
                    pnl=round(pnl, 2),
                    pnl_pct=round(pnl_pct, 2),
                    hold_bars=i - position["entry_bar"],
                    exit_reason=exit_reason,
                )
                result.trades.append(trade)
                equity += pnl
                position = None
        else:
            entry_signal, side = _check_entry(config, row, prev, df, i)
            if entry_signal:
                atr = row.get("atr", 1.0)
                qty = _calculate_position_size(equity, atr, config.risk_pct, config.atr_multiplier, price, config.max_position_pct)
                if qty > 0 and qty * price < equity * 0.95:
                    position = {
                        "side": side,
                        "entry_price": price,
                        "qty": qty,
                        "entry_bar": i,
                        "entry_date": date_str,
                        "stop_loss": price - atr * config.atr_multiplier if side == "buy" else price + atr * config.atr_multiplier,
                    }

    if position:
        last_price = df.iloc[-1]["close"]
        if position["side"] == "buy":
            pnl = (last_price - position["entry_price"]) * position["qty"]
        else:
            pnl = (position["entry_price"] - last_price) * position["qty"]
        equity += pnl
        result.trades.append(BacktestTrade(
            entry_date=position["entry_date"],
            exit_date=dates[-1] if dates else "end",
            symbol=config.symbol,
            side=position["side"],
            entry_price=position["entry_price"],
            exit_price=last_price,
            qty=position["qty"],
            pnl=round(pnl, 2),
            pnl_pct=round(pnl / (position["entry_price"] * position["qty"]) * 100, 2),
            hold_bars=len(df) - 1 - position["entry_bar"],
            exit_reason="end_of_data",
        ))

    result.equity_curve = equity_curve
    result.dates = dates

    result.total_return = round(equity - config.initial_capital, 2)
    result.total_return_pct = round(result.total_return / config.initial_capital * 100, 2)
    result.total_trades = len(result.trades)

    wins = [t for t in result.trades if t.pnl > 0]
    losses = [t for t in result.trades if t.pnl <= 0]
    result.winning_trades = len(wins)
    result.losing_trades = len(losses)
    result.win_rate = round(len(wins) / len(result.trades) * 100, 1) if result.trades else 0

    result.avg_win = round(sum(t.pnl for t in wins) / len(wins), 2) if wins else 0
    result.avg_loss = round(sum(t.pnl for t in losses) / len(losses), 2) if losses else 0

    total_wins = sum(t.pnl for t in wins)
    total_losses = abs(sum(t.pnl for t in losses))
    result.profit_factor = round(total_wins / total_losses, 2) if total_losses > 0 else float("inf") if total_wins > 0 else 0

    result.avg_hold_bars = round(sum(t.hold_bars for t in result.trades) / len(result.trades), 1) if result.trades else 0

    if equity_curve:
        peak = equity_curve[0]
        max_dd = 0
        max_dd_pct = 0
        for v in equity_curve:
            if v > peak:
                peak = v
            dd = peak - v
            dd_pct = dd / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
                max_dd_pct = dd_pct
        result.max_drawdown = round(max_dd, 2)
        result.max_drawdown_pct = round(max_dd_pct, 2)

    if len(equity_curve) > 1:
        returns = []
        for j in range(1, len(equity_curve)):
            if equity_curve[j - 1] > 0:
                returns.append((equity_curve[j] - equity_curve[j - 1]) / equity_curve[j - 1])
        if returns and np.std(returns) > 0:
            result.sharpe_ratio = round(np.mean(returns) / np.std(returns) * math.sqrt(252), 2)

    first_price = df.iloc[0]["close"]
    last_price = df.iloc[-1]["close"]
    result.buy_and_hold_return = round((last_price - first_price) / first_price * config.initial_capital, 2)
    result.buy_and_hold_pct = round((last_price - first_price) / first_price * 100, 2)

    return result


def _check_entry(config: BacktestConfig, row, prev, df, idx) -> tuple[bool, str]:
    strategy = config.strategy

    if strategy == "ema_crossover":
        if prev["ema9"] <= prev["ema50"] and row["ema9"] > row["ema50"]:
            return True, "buy"
        if prev["ema9"] >= prev["ema50"] and row["ema9"] < row["ema50"]:
            return True, "sell"

    elif strategy == "mean_reversion":
        if row["rsi"] < config.rsi_oversold and row["bb_pct_b"] < config.bb_entry_threshold:
            return True, "buy"
        if row["rsi"] > config.rsi_overbought and row["bb_pct_b"] > config.bb_exit_threshold:
            return True, "sell"

    elif strategy == "momentum":
        if row["rsi"] > 50 and prev["rsi"] <= 50 and row.get("macd_hist", 0) > 0:
            return True, "buy"
        if row["rsi"] < 50 and prev["rsi"] >= 50 and row.get("macd_hist", 0) < 0:
            return True, "sell"

    elif strategy == "triple_ema_trend":
        if row["ema9"] > row["ema50"] > row.get("ema200", 0) and prev["ema9"] <= prev["ema50"]:
            return True, "buy"
        if row["ema9"] < row["ema50"] < row.get("ema200", float("inf")) and prev["ema9"] >= prev["ema50"]:
            return True, "sell"

    elif strategy == "bb_squeeze":
        bb_width = (row["bb_upper"] - row["bb_lower"]) / row["bb_mid"] if row.get("bb_mid", 0) > 0 else 999
        prev_width = (prev["bb_upper"] - prev["bb_lower"]) / prev["bb_mid"] if prev.get("bb_mid", 0) > 0 else 999
        if prev_width < 0.04 and bb_width >= 0.04:
            if row["ema9"] > row["ema50"]:
                return True, "buy"
            else:
                return True, "sell"

    return False, ""


def _check_exit(config: BacktestConfig, row, prev, position: dict) -> tuple[bool, str]:
    price = row["close"]
    side = position["side"]
    stop = position["stop_loss"]

    if side == "buy" and price <= stop:
        return True, "stop_loss"
    if side == "sell" and price >= stop:
        return True, "stop_loss"

    strategy = config.strategy

    if strategy == "ema_crossover":
        if side == "buy" and row["ema9"] < row["ema50"] and prev["ema9"] >= prev["ema50"]:
            return True, "ema_cross_exit"
        if side == "sell" and row["ema9"] > row["ema50"] and prev["ema9"] <= prev["ema50"]:
            return True, "ema_cross_exit"

    elif strategy == "mean_reversion":
        if side == "buy" and row["bb_pct_b"] > 0.5:
            return True, "bb_midline_target"
        if side == "sell" and row["bb_pct_b"] < 0.5:
            return True, "bb_midline_target"

    elif strategy == "momentum":
        if side == "buy" and row.get("macd_hist", 0) < 0 and prev.get("macd_hist", 0) >= 0:
            return True, "macd_reversal"
        if side == "sell" and row.get("macd_hist", 0) > 0 and prev.get("macd_hist", 0) <= 0:
            return True, "macd_reversal"

    elif strategy == "triple_ema_trend":
        if side == "buy" and row["ema9"] < row["ema50"]:
            return True, "ema_stack_broken"
        if side == "sell" and row["ema9"] > row["ema50"]:
            return True, "ema_stack_broken"

    elif strategy == "bb_squeeze":
        if side == "buy" and row["rsi"] > config.rsi_overbought:
            return True, "rsi_overbought_exit"
        if side == "sell" and row["rsi"] < config.rsi_oversold:
            return True, "rsi_oversold_exit"

    return False, ""
