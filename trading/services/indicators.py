import numpy as np
import pandas as pd


def compute_atr(df, period=14):
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)

    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    return atr


def compute_bollinger_bands(df, period=20, std_dev=2.0):
    close = df["close"]
    sma = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    width = (upper - lower) / sma
    pct_b = (close - lower) / (upper - lower)
    return pd.DataFrame({"bb_upper": upper, "bb_middle": sma, "bb_lower": lower, "bb_width": width, "bb_pct_b": pct_b})


def compute_moving_averages(df, fast=9, mid=21, slow=50):
    close = df["close"]
    return pd.DataFrame(
        {
            "ema_fast": close.ewm(span=fast, adjust=False).mean(),
            "ema_mid": close.ewm(span=mid, adjust=False).mean(),
            "ema_slow": close.ewm(span=slow, adjust=False).mean(),
        }
    )


def compute_fibonacci_levels(df, lookback=50):
    recent = df["close"].iloc[-lookback:]
    high = recent.max()
    low = recent.min()
    diff = high - low
    levels = {
        "fib_0": low,
        "fib_236": low + 0.236 * diff,
        "fib_382": low + 0.382 * diff,
        "fib_500": low + 0.500 * diff,
        "fib_618": low + 0.618 * diff,
        "fib_786": low + 0.786 * diff,
        "fib_100": high,
    }
    return levels, high, low


def compute_rsi(df, period=14):
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_macd(df, fast=12, slow=26, signal=9):
    close = df["close"]
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "macd_signal": signal_line, "macd_hist": histogram})


def compute_all_indicators(df):
    if df is None or len(df) < 60:
        return None
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    bb = compute_bollinger_bands(df)
    mas = compute_moving_averages(df)
    macd = compute_macd(df)

    df["atr"] = compute_atr(df)
    df["rsi"] = compute_rsi(df)
    for col in bb.columns:
        df[col] = bb[col]
    for col in mas.columns:
        df[col] = mas[col]
    for col in macd.columns:
        df[col] = macd[col]

    return df


def calculate_position_size(account_equity, atr, risk_pct=0.02, atr_multiplier=1.5):
    if atr <= 0:
        return 0
    risk_dollars = account_equity * risk_pct
    stop_distance = atr * atr_multiplier
    shares = int(risk_dollars / stop_distance)
    return max(1, shares)


def detect_signal(df):
    if df is None or len(df) < 2:
        return None, None, {}

    last = df.iloc[-1]
    prev = df.iloc[-2]

    signals = []
    score = 0

    ema_bullish = last["ema_fast"] > last["ema_mid"] > last["ema_slow"]
    ema_bearish = last["ema_fast"] < last["ema_mid"] < last["ema_slow"]
    ema_cross_up = prev["ema_fast"] <= prev["ema_mid"] and last["ema_fast"] > last["ema_mid"]
    ema_cross_down = prev["ema_fast"] >= prev["ema_mid"] and last["ema_fast"] < last["ema_mid"]

    if ema_bullish:
        score += 1
        signals.append("Triple MA bullish stack")
    if ema_bearish:
        score -= 1
        signals.append("Triple MA bearish stack")
    if ema_cross_up:
        score += 2
        signals.append("Fast/Mid EMA bullish crossover")
    if ema_cross_down:
        score -= 2
        signals.append("Fast/Mid EMA bearish crossover")

    rsi = last["rsi"]
    if rsi < 30:
        score += 1
        signals.append(f"RSI oversold ({rsi:.1f})")
    elif rsi > 70:
        score -= 1
        signals.append(f"RSI overbought ({rsi:.1f})")

    price = last["close"]
    bb_lower = last["bb_lower"]
    bb_upper = last["bb_upper"]
    bb_mid = last["bb_middle"]
    if price < bb_lower:
        score += 1
        signals.append("Price below Bollinger lower band")
    elif price > bb_upper:
        score -= 1
        signals.append("Price above Bollinger upper band")

    macd_cross_up = prev["macd"] <= prev["macd_signal"] and last["macd"] > last["macd_signal"]
    macd_cross_down = prev["macd"] >= prev["macd_signal"] and last["macd"] < last["macd_signal"]
    if macd_cross_up:
        score += 1
        signals.append("MACD bullish crossover")
    if macd_cross_down:
        score -= 1
        signals.append("MACD bearish crossover")

    indicators = {
        "price": float(price),
        "atr": float(last["atr"]),
        "rsi": float(rsi),
        "ema_fast": float(last["ema_fast"]),
        "ema_mid": float(last["ema_mid"]),
        "ema_slow": float(last["ema_slow"]),
        "bb_upper": float(bb_upper),
        "bb_middle": float(bb_mid),
        "bb_lower": float(bb_lower),
        "bb_pct_b": float(last["bb_pct_b"]),
        "macd": float(last["macd"]),
        "macd_signal": float(last["macd_signal"]),
        "signals": signals,
        "score": score,
    }

    if score >= 2:
        return "buy", score, indicators
    elif score <= -2:
        return "sell", score, indicators
    else:
        return "hold", score, indicators
