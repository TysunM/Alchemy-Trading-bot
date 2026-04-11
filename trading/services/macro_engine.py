"""
Macro Regime Engine — Dalio-inspired economic regime classifier.

Fetches live macro data via yfinance and classifies the current environment
into one of five regimes, each with a position-size modifier so Claude can
calibrate aggression accordingly.

Regimes
-------
  expansionary   — Low vol, positive yield spread, SPY in uptrend.
                   Full risk-on. modifier = 1.0
  neutral        — Mixed signals. Moderate sizing. modifier = 0.75
  contractionary — Elevated vol OR flattening yield curve, SPY weakening.
                   Reduce exposure. modifier = 0.50
  high_volatility— VIX > 28. Widen stops, cut size hard. modifier = 0.25
  recession_risk — Inverted yield curve (spread < 0) AND SPY below 200 EMA.
                   Defensive/cash. modifier = 0.20
"""

import logging
from datetime import datetime
from typing import Dict, Any

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Regime thresholds
VIX_CALM = 18.0
VIX_ELEVATED = 28.0
YIELD_INVERSION_THRESHOLD = 0.0   # 10yr - 3mo spread (percentage points)
YIELD_FLAT_THRESHOLD = 0.50       # starting to flatten


def _fetch_close(ticker: str, period: str = "3mo") -> pd.Series:
    """Return the daily close series for *ticker*, silently returning empty on failure."""
    try:
        df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=True)
        if df is None or df.empty:
            return pd.Series(dtype=float)
        return df["Close"].dropna()
    except Exception as e:
        logger.warning(f"macro_engine: could not fetch {ticker}: {e}")
        return pd.Series(dtype=float)


def _ema(series: pd.Series, span: int) -> float:
    """Return the most recent EMA value, or NaN if insufficient data."""
    if len(series) < span // 2:
        return float("nan")
    return float(series.ewm(span=span, adjust=False).mean().iloc[-1])


def get_macro_regime_analysis() -> Dict[str, Any]:
    """
    Analyse the global macro environment and return a regime dict.

    Returns
    -------
    dict with keys:
        regime           : str  — one of the five regime labels
        vix              : float
        yield_spread_pct : float — 10yr minus 3-month Treasury yield (%)
        spy_trend        : str  — 'bullish' | 'neutral' | 'bearish'
        tlt_trend        : str  — 'bullish' | 'neutral' | 'bearish'
        bias             : str  — 'risk_on' | 'neutral' | 'risk_off'
        position_size_modifier : float — multiply position sizes by this
        summary          : str  — human-readable one-liner for Claude
        timestamp        : str
    """

    # ------------------------------------------------------------------ #
    #  1. VIX — fear gauge
    # ------------------------------------------------------------------ #
    vix_series = _fetch_close("^VIX", period="1mo")
    vix = float(vix_series.iloc[-1]) if len(vix_series) > 0 else 20.0

    # ------------------------------------------------------------------ #
    #  2. Yield curve — 10yr (^TNX) minus 3-month (^IRX)
    #     Both are quoted as %, e.g. 4.5 means 4.50%
    # ------------------------------------------------------------------ #
    tnx = _fetch_close("^TNX", period="1mo")   # 10-year Treasury yield
    irx = _fetch_close("^IRX", period="1mo")   # 3-month Treasury yield

    if len(tnx) > 0 and len(irx) > 0:
        yield_10yr = float(tnx.iloc[-1])
        yield_3mo  = float(irx.iloc[-1])
        yield_spread = yield_10yr - yield_3mo
    else:
        # Fallback: assume a modestly positive spread
        yield_10yr   = 4.5
        yield_3mo    = 4.0
        yield_spread = 0.5
        logger.warning("macro_engine: Treasury yield data unavailable; using defaults")

    # ------------------------------------------------------------------ #
    #  3. SPY trend — EMA 50 vs EMA 200
    # ------------------------------------------------------------------ #
    spy_close = _fetch_close("SPY", period="1y")
    spy_trend = "neutral"
    spy_ema50  = _ema(spy_close, 50)
    spy_ema200 = _ema(spy_close, 200)

    if not (np.isnan(spy_ema50) or np.isnan(spy_ema200)):
        if spy_ema50 > spy_ema200 * 1.005:
            spy_trend = "bullish"
        elif spy_ema50 < spy_ema200 * 0.995:
            spy_trend = "bearish"

    # ------------------------------------------------------------------ #
    #  4. TLT trend — long-bond ETF as flight-to-safety proxy
    # ------------------------------------------------------------------ #
    tlt_close = _fetch_close("TLT", period="3mo")
    tlt_trend = "neutral"
    if len(tlt_close) >= 20:
        tlt_ema20 = float(tlt_close.ewm(span=20, adjust=False).mean().iloc[-1])
        last_tlt  = float(tlt_close.iloc[-1])
        if last_tlt > tlt_ema20 * 1.01:
            tlt_trend = "bullish"   # money flowing into bonds → risk-off signal
        elif last_tlt < tlt_ema20 * 0.99:
            tlt_trend = "bearish"   # bonds selling → risk-on

    # ------------------------------------------------------------------ #
    #  5. Regime classification  (order matters — most severe first)
    # ------------------------------------------------------------------ #
    if vix >= VIX_ELEVATED:
        regime   = "high_volatility"
        modifier = 0.25
        bias     = "risk_off"

    elif yield_spread <= YIELD_INVERSION_THRESHOLD and spy_trend == "bearish":
        regime   = "recession_risk"
        modifier = 0.20
        bias     = "risk_off"

    elif yield_spread <= YIELD_FLAT_THRESHOLD or (vix >= VIX_CALM and spy_trend == "bearish"):
        regime   = "contractionary"
        modifier = 0.50
        bias     = "risk_off"

    elif spy_trend == "bullish" and vix < VIX_CALM and yield_spread > YIELD_FLAT_THRESHOLD:
        regime   = "expansionary"
        modifier = 1.0
        bias     = "risk_on"

    else:
        regime   = "neutral"
        modifier = 0.75
        bias     = "neutral"

    # ------------------------------------------------------------------ #
    #  6. Human-readable summary for Claude's system context
    # ------------------------------------------------------------------ #
    summary = (
        f"Regime: {regime.upper()} | "
        f"VIX={vix:.1f} | "
        f"10yr-3mo spread={yield_spread:+.2f}% | "
        f"SPY trend={spy_trend} | "
        f"TLT={tlt_trend} | "
        f"Bias={bias} | "
        f"Position modifier={modifier:.2f}x"
    )

    result = {
        "regime":                regime,
        "vix":                   round(vix, 2),
        "yield_10yr":            round(yield_10yr, 3),
        "yield_3mo":             round(yield_3mo, 3),
        "yield_spread_pct":      round(yield_spread, 3),
        "spy_trend":             spy_trend,
        "spy_ema50":             round(spy_ema50, 2) if not np.isnan(spy_ema50) else None,
        "spy_ema200":            round(spy_ema200, 2) if not np.isnan(spy_ema200) else None,
        "tlt_trend":             tlt_trend,
        "bias":                  bias,
        "position_size_modifier": modifier,
        "summary":               summary,
        "timestamp":             datetime.utcnow().isoformat() + "Z",
    }

    logger.info(f"Macro regime: {summary}")
    return result
