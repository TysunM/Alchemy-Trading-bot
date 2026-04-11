import yfinance as yf
import pandas as pd

def get_macro_regime_analysis():
    """Analyzes the 10Y-2Y Yield Curve, VIX, and Inflation to determine the market regime."""
    try:
        # Fetch Treasury Yields and VIX
        tickers = {"^TNX": "10Y", "^IRX": "3M", "^VIX": "VIX", "GLD": "Gold"}
        data = yf.download(list(tickers.keys()), period="5d", interval="1d")['Close']
        
        vix = data['^VIX'].iloc[-1]
        ten_year = data['^TNX'].iloc[-1]
        three_month = data['^IRX'].iloc[-1]
        yield_spread = ten_year - three_month
        
        regime = "Standard"
        if yield_spread < 0: regime = "Recession Warning (Inverted)"
        if vix > 25: regime = "High Volatility / Fear"
        if vix < 15 and yield_spread > 1: regime = "Expansionary Bull"

        return {
            "regime": regime,
            "vix_level": round(float(vix), 2),
            "yield_spread_10y_3m": round(float(yield_spread), 2),
            "bias": "Defensive" if vix > 25 or yield_spread < 0 else "Aggressive"
        }
    except Exception as e:
        return {"error": str(e)}
