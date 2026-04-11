import os

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")

ALPACA_BASE_URL = "https://paper-api.alpaca.markets"

DB_PATH = "trading/data/trading.db"
DB_URL = f"sqlite:///{DB_PATH}"

MAX_RISK_PCT = 0.02
DEFAULT_ATR_MULTIPLIER = 1.5
DEFAULT_LOOKBACK = 20
MAX_POSITION_SIZE = 0.10
DEFAULT_SYMBOLS = ["SPY", "QQQ", "AAPL", "TSLA", "NVDA"]

DASH_USER = os.environ.get("DASH_USER", "")
DASH_PASS = os.environ.get("DASH_PASS", "")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
NTFY_USER = os.environ.get("NTFY_USER", "")
NTFY_PASS = os.environ.get("NTFY_PASS", "")
