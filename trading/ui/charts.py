"""
Phase 2: Professional-grade interactive charting module.

Data Sources:
  - Primary: yfinance (broad symbol support, no auth required)
  - Fallback: Alpaca broker bars

Indicators:
  - Bollinger Bands (20-period, 2 std dev) with shaded channel
  - Moving Averages: 9 EMA (short), 50 EMA (medium), 200 EMA (long)
  - Fibonacci Retracement: auto-calculated from visible high/low
  - Volume bars
  - RSI (14)
  - MACD (12/26/9)
  - ATR (14)

Interactivity:
  - Plotly drawing tools (line, open/closed path, eraser)
  - Zoom, pan, crosshair
  - Hover with full OHLCV + indicator values
  - Indicator on/off toggles via caller
"""

from __future__ import annotations

import warnings
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from plotly.subplots import make_subplots

warnings.filterwarnings("ignore")

COLORS = {
    "bg": "#0a0e1a",
    "panel": "#0f1729",
    "grid": "#1a2540",
    "text": "#94a3b8",
    "text_bright": "#e2e8f0",
    "bull": "#10b981",
    "bear": "#ef4444",
    "bull_fill": "rgba(16,185,129,0.15)",
    "bear_fill": "rgba(239,68,68,0.15)",
    "ema9": "#22d3ee",
    "ema50": "#fbbf24",
    "ema200": "#a78bfa",
    "bb": "#6366f1",
    "bb_fill": "rgba(99,102,241,0.07)",
    "fib_0": "#64748b",
    "fib_236": "#94a3b8",
    "fib_382": "#64748b",
    "fib_500": "#fbbf24",
    "fib_618": "#f59e0b",
    "fib_786": "#ef4444",
    "fib_100": "#64748b",
    "support": "#10b981",
    "ceiling": "#ef4444",
    "volume": "rgba(99,102,241,0.4)",
    "volume_bull": "rgba(16,185,129,0.5)",
    "volume_bear": "rgba(239,68,68,0.5)",
    "rsi": "#22d3ee",
    "macd_line": "#22d3ee",
    "macd_signal": "#fbbf24",
    "macd_hist_bull": "rgba(16,185,129,0.7)",
    "macd_hist_bear": "rgba(239,68,68,0.7)",
}

YFINANCE_TF_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "1h": "1h", "2h": "2h", "4h": "4h",
    "1d": "1d", "1wk": "1wk",
    "1Day": "1d", "1Hour": "1h", "15Min": "15m",
}

YFINANCE_PERIOD_MAP = {
    "1m": "7d", "5m": "60d", "15m": "60d", "30m": "60d",
    "1h": "730d", "2h": "730d", "4h": "730d",
    "1d": "5y", "1wk": "10y",
}


def fetch_yfinance(symbol: str, timeframe: str = "1d", bars: int = 300) -> Optional[pd.DataFrame]:
    tf = YFINANCE_TF_MAP.get(timeframe, "1d")
    period = YFINANCE_PERIOD_MAP.get(tf, "5y")
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=tf, auto_adjust=True)
        if df is None or df.empty:
            return None
        df.columns = [c.lower() for c in df.columns]
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        df = df.tail(bars)
        df.index = pd.DatetimeIndex(df.index).tz_localize(None)
        return df
    except Exception:
        return None


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(span=period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(span=period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = _ema(series, fast)
    ema_slow = _ema(series, slow)
    line = ema_fast - ema_slow
    sig = _ema(line, signal)
    return line, sig, line - sig


def _bollinger(series: pd.Series, period: int = 20, std: float = 2.0):
    mid = _sma(series, period)
    s = series.rolling(period).std()
    return mid + std * s, mid, mid - std * s


def _fibonacci(df: pd.DataFrame, lookback: int = None):
    sub = df if lookback is None else df.tail(lookback)
    high = float(sub["high"].max())
    low = float(sub["low"].min())
    diff = high - low
    levels = {
        "0%": low,
        "23.6%": low + 0.236 * diff,
        "38.2%": low + 0.382 * diff,
        "50%": low + 0.500 * diff,
        "61.8%": low + 0.618 * diff,
        "78.6%": low + 0.786 * diff,
        "100%": high,
    }
    return levels, high, low


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    df = df.copy()
    df["ema9"] = _ema(c, 9)
    df["ema50"] = _ema(c, 50)
    df["ema200"] = _ema(c, 200)
    df["bb_upper"], df["bb_mid"], df["bb_lower"] = _bollinger(c, 20, 2.0)
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]
    df["bb_pct_b"] = (c - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])
    df["atr"] = _atr(df, 14)
    df["rsi"] = _rsi(c, 14)
    df["macd"], df["macd_signal"], df["macd_hist"] = _macd(c)
    df["vwap"] = (df["close"] * df["volume"]).cumsum() / df["volume"].cumsum()
    return df


def build_chart(
    df: pd.DataFrame,
    symbol: str,
    show_bb: bool = True,
    show_ema9: bool = True,
    show_ema50: bool = True,
    show_ema200: bool = True,
    show_fib: bool = True,
    show_volume: bool = True,
    show_rsi: bool = True,
    show_macd: bool = True,
    support_line: Optional[float] = None,
    ceiling_line: Optional[float] = None,
    drawn_shapes: Optional[list] = None,
    saved_annotations: Optional[list] = None,
) -> go.Figure:
    df = compute_indicators(df)

    show_rsi_panel = show_rsi
    show_macd_panel = show_macd

    row_count = 2 + int(show_rsi_panel) + int(show_macd_panel)
    row_heights = [0.55, 0.10]
    subplot_titles = [f"{symbol} — Price", "Volume"]
    if show_rsi_panel:
        row_heights.append(0.175)
        subplot_titles.append("RSI (14)")
    if show_macd_panel:
        row_heights.append(0.175)
        subplot_titles.append("MACD (12/26/9)")

    fig = make_subplots(
        rows=row_count, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.025,
        row_heights=row_heights,
        subplot_titles=subplot_titles,
    )

    candle = go.Candlestick(
        x=df.index,
        open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name="Price",
        increasing=dict(line=dict(color=COLORS["bull"], width=1), fillcolor=COLORS["bull"]),
        decreasing=dict(line=dict(color=COLORS["bear"], width=1), fillcolor=COLORS["bear"]),
        whiskerwidth=0.5,
    )
    fig.add_trace(candle, row=1, col=1)

    if show_bb:
        fig.add_trace(go.Scattergl(
            x=df.index, y=df["bb_upper"],
            name="BB Upper", line=dict(color=COLORS["bb"], width=1, dash="dot"),
            legendgroup="bb", showlegend=True,
        ), row=1, col=1)
        fig.add_trace(go.Scattergl(
            x=df.index, y=df["bb_mid"],
            name="BB Mid", line=dict(color=COLORS["bb"], width=1),
            legendgroup="bb", showlegend=False,
        ), row=1, col=1)
        fig.add_trace(go.Scattergl(
            x=df.index, y=df["bb_lower"],
            name="BB Lower", line=dict(color=COLORS["bb"], width=1, dash="dot"),
            fill="tonexty", fillcolor=COLORS["bb_fill"],
            legendgroup="bb", showlegend=False,
        ), row=1, col=1)

    if show_ema9:
        fig.add_trace(go.Scattergl(
            x=df.index, y=df["ema9"],
            name="EMA 9", line=dict(color=COLORS["ema9"], width=1.5),
        ), row=1, col=1)

    if show_ema50:
        fig.add_trace(go.Scattergl(
            x=df.index, y=df["ema50"],
            name="EMA 50", line=dict(color=COLORS["ema50"], width=1.5),
        ), row=1, col=1)

    if show_ema200:
        fig.add_trace(go.Scattergl(
            x=df.index, y=df["ema200"],
            name="EMA 200", line=dict(color=COLORS["ema200"], width=2),
        ), row=1, col=1)

    if show_fib:
        fib_levels, fib_high, fib_low = _fibonacci(df)
        fib_color_map = {
            "0%": COLORS["fib_0"],
            "23.6%": COLORS["fib_236"],
            "38.2%": COLORS["fib_382"],
            "50%": COLORS["fib_500"],
            "61.8%": COLORS["fib_618"],
            "78.6%": COLORS["fib_786"],
            "100%": COLORS["fib_100"],
        }
        for label, price in fib_levels.items():
            color = fib_color_map.get(label, "#64748b")
            fig.add_shape(
                type="line",
                x0=df.index[0], x1=df.index[-1],
                y0=price, y1=price,
                line=dict(color=color, width=0.8, dash="dot"),
                row=1, col=1,
            )
            fig.add_annotation(
                x=df.index[-1], y=price,
                text=f" Fib {label}  ${price:.2f}",
                showarrow=False,
                xanchor="left",
                font=dict(size=9, color=color),
                row=1, col=1,
            )

    if support_line and support_line > 0:
        fig.add_shape(
            type="line",
            x0=df.index[0], x1=df.index[-1],
            y0=support_line, y1=support_line,
            line=dict(color=COLORS["support"], width=2),
            row=1, col=1,
        )
        fig.add_annotation(
            x=df.index[-1], y=support_line,
            text=f" Support  ${support_line:.2f}",
            showarrow=False, xanchor="left",
            font=dict(size=10, color=COLORS["support"], family="monospace"),
            row=1, col=1,
        )

    if ceiling_line and ceiling_line > 0:
        fig.add_shape(
            type="line",
            x0=df.index[0], x1=df.index[-1],
            y0=ceiling_line, y1=ceiling_line,
            line=dict(color=COLORS["ceiling"], width=2),
            row=1, col=1,
        )
        fig.add_annotation(
            x=df.index[-1], y=ceiling_line,
            text=f" Ceiling  ${ceiling_line:.2f}",
            showarrow=False, xanchor="left",
            font=dict(size=10, color=COLORS["ceiling"], family="monospace"),
            row=1, col=1,
        )

    if drawn_shapes:
        for shape in drawn_shapes:
            fig.add_shape(**shape)

    if saved_annotations:
        ann_color_map = {
            "support": COLORS["support"],
            "ceiling": COLORS["ceiling"],
            "trendline": "#fbbf24",
            "custom": "#a78bfa",
        }
        for ann in saved_annotations:
            a_type = ann.get("annotation_type", "support")
            a_price = ann.get("price_level", 0)
            a_color = ann_color_map.get(a_type, "#94a3b8")
            a_label = ann.get("notes") or a_type.capitalize()
            fig.add_shape(
                type="line",
                x0=df.index[0], x1=df.index[-1],
                y0=a_price, y1=a_price,
                line=dict(color=a_color, width=2, dash="dash"),
                row=1, col=1,
            )
            fig.add_annotation(
                x=df.index[-1], y=a_price,
                text=f" {a_label}  ${a_price:.2f}",
                showarrow=False, xanchor="left",
                font=dict(size=10, color=a_color, family="monospace"),
                row=1, col=1,
            )

    if show_volume:
        vol_colors = [
            COLORS["volume_bull"] if df["close"].iloc[i] >= df["open"].iloc[i] else COLORS["volume_bear"]
            for i in range(len(df))
        ]
        fig.add_trace(go.Bar(
            x=df.index, y=df["volume"],
            name="Volume", marker_color=vol_colors,
            showlegend=False,
        ), row=2, col=1)

    rsi_row = 3 if show_rsi_panel else None
    macd_row = (3 + int(show_rsi_panel)) if show_macd_panel else None

    if show_rsi_panel and rsi_row:
        fig.add_trace(go.Scattergl(
            x=df.index, y=df["rsi"],
            name="RSI", line=dict(color=COLORS["rsi"], width=1.5),
            showlegend=False,
        ), row=rsi_row, col=1)
        for lvl, color in [(70, COLORS["bear"]), (50, COLORS["grid"]), (30, COLORS["bull"])]:
            fig.add_hline(y=lvl, line_color=color, line_width=0.8, line_dash="dot", row=rsi_row, col=1)
        fig.add_hrect(y0=30, y1=70, fillcolor="rgba(99,102,241,0.04)", line_width=0, row=rsi_row, col=1)

    if show_macd_panel and macd_row:
        hist_colors = [COLORS["macd_hist_bull"] if v >= 0 else COLORS["macd_hist_bear"] for v in df["macd_hist"]]
        fig.add_trace(go.Bar(
            x=df.index, y=df["macd_hist"],
            name="MACD Hist", marker_color=hist_colors, showlegend=False,
        ), row=macd_row, col=1)
        fig.add_trace(go.Scattergl(
            x=df.index, y=df["macd"],
            name="MACD", line=dict(color=COLORS["macd_line"], width=1.5), showlegend=False,
        ), row=macd_row, col=1)
        fig.add_trace(go.Scattergl(
            x=df.index, y=df["macd_signal"],
            name="Signal", line=dict(color=COLORS["macd_signal"], width=1.5), showlegend=False,
        ), row=macd_row, col=1)
        fig.add_hline(y=0, line_color=COLORS["grid"], line_width=0.8, row=macd_row, col=1)

    fig.update_layout(
        height=740,
        paper_bgcolor=COLORS["bg"],
        plot_bgcolor=COLORS["bg"],
        font=dict(color=COLORS["text"], size=11, family="monospace"),
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.01,
            xanchor="left", x=0,
            font=dict(size=10),
            bgcolor="rgba(15,23,41,0.8)",
            bordercolor=COLORS["grid"],
            borderwidth=1,
        ),
        margin=dict(l=0, r=80, t=40, b=0),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=COLORS["panel"],
            bordercolor=COLORS["grid"],
            font=dict(color=COLORS["text_bright"], size=11, family="monospace"),
        ),
        dragmode="pan",
        newshape=dict(
            line=dict(color="#22d3ee", width=2),
            fillcolor="rgba(34,211,238,0.1)",
        ),
        xaxis_rangeslider_visible=False,
    )

    axis_style = dict(
        gridcolor=COLORS["grid"],
        gridwidth=0.5,
        zerolinecolor=COLORS["grid"],
        showgrid=True,
        tickfont=dict(color=COLORS["text"], size=10),
        linecolor=COLORS["grid"],
    )

    for i in range(1, row_count + 1):
        fig.update_xaxes(**axis_style, row=i, col=1, showspikes=True, spikecolor=COLORS["text"], spikethickness=0.8)
        fig.update_yaxes(**axis_style, row=i, col=1, showspikes=True, spikecolor=COLORS["text"], spikethickness=0.8, tickformat="$.2f" if i == 1 else "")

    fig.update_xaxes(row=1, col=1, showticklabels=False)

    fig.update_layout(
        title=dict(
            text=f"<b>{symbol}</b>",
            font=dict(size=16, color=COLORS["text_bright"]),
            x=0.01,
        ),
    )

    return fig, df


PLOTLY_CONFIG = {
    "scrollZoom": True,
    "displaylogo": False,
    "toImageButtonOptions": {"format": "png", "filename": "chart", "scale": 2},
    "modeBarButtonsToAdd": [
        "drawline",
        "drawopenpath",
        "drawclosedpath",
        "drawrect",
        "eraseshape",
    ],
    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
}


def get_indicator_summary(df: pd.DataFrame) -> dict:
    last = df.iloc[-1]
    prev = df.iloc[-2]

    ema_bull = last["ema9"] > last["ema50"] > last["ema200"]
    ema_bear = last["ema9"] < last["ema50"] < last["ema200"]
    bb_squeeze = last["bb_width"] < df["bb_width"].quantile(0.20)
    above_200 = last["close"] > last["ema200"]

    return {
        "price": float(last["close"]),
        "change": float(last["close"] - prev["close"]),
        "change_pct": float((last["close"] - prev["close"]) / prev["close"] * 100),
        "atr": float(last["atr"]),
        "rsi": float(last["rsi"]),
        "ema9": float(last["ema9"]),
        "ema50": float(last["ema50"]),
        "ema200": float(last["ema200"]),
        "bb_upper": float(last["bb_upper"]),
        "bb_mid": float(last["bb_mid"]),
        "bb_lower": float(last["bb_lower"]),
        "bb_pct_b": float(last["bb_pct_b"]),
        "bb_width": float(last["bb_width"]),
        "bb_squeeze": bb_squeeze,
        "macd": float(last["macd"]),
        "macd_signal": float(last["macd_signal"]),
        "macd_hist": float(last["macd_hist"]),
        "volume": float(last["volume"]),
        "ema_bullish_stack": ema_bull,
        "ema_bearish_stack": ema_bear,
        "above_200": above_200,
        "vwap": float(last["vwap"]),
    }
