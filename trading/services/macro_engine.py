import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- API KEYS (Fetched from Environment) ---
# DO NOT paste your actual keys here. Paste them into your .env file on the VPS.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")

# --- TRADING CONFIG ---
# Is this a paper trading account? (True/False)
IS_PAPER = os.environ.get("IS_PAPER", "True").lower() == "true"
BASE_URL = "https://paper-api.alpaca.markets" if IS_PAPER else "https://api.alpaca.markets"

# Default watchlist for the Alchemical Agent
DEFAULT_SYMBOLS = ["SPY", "QQQ", "GLD", "TLT", "NVDA", "AAPL", "MSFT", "TSLA"]

# --- DASHBOARD CREDENTIALS ---
DASH_USER = os.environ.get("DASH_USER", "admin")
DASH_PASS = os.environ.get("DASH_PASS", "alchemical_secure_pass")
