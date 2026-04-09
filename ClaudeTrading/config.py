"""
Quant-Automata — Political Trade Mirror Configuration
"""

# ──────────────────────────────────────────────────────────────
# ALPACA PAPER TRADING
# ──────────────────────────────────────────────────────────────
ALPACA_API_KEY    = "PK35BQZD4PM5WX4VIABTWLAJ4T"
ALPACA_SECRET_KEY = "GauD4DpcHs3GRta4KpeGJjzF6vjjR2w1n3wQspLLDYk7"
ALPACA_BASE_URL   = "https://paper-api.alpaca.markets"
ALPACA_DATA_URL   = "https://data.alpaca.markets"

# ──────────────────────────────────────────────────────────────
# CAPITOL TRADES  (no key required — uses public RSC endpoint)
# ──────────────────────────────────────────────────────────────
CT_BASE_URL       = "https://www.capitoltrades.com"
CT_PAGE_SIZE      = 96       # Max per page on their RSC endpoint
CT_HISTORY_PAGES  = 15       # Pages to fetch when building politician history (~1440 trades)

# ──────────────────────────────────────────────────────────────
# POLITICIAN RANKING
# ──────────────────────────────────────────────────────────────
MIN_TRADES_FOR_RANKING   = 10    # Minimum disclosed trades to qualify for ranking
TOP_N_POLITICIANS        = 5     # Number of top politicians to follow
PERFORMANCE_LOOKBACK_DAYS= 30    # Days after disclosure to measure trade performance
SCORE_WIN_RATE_WEIGHT    = 0.6   # 60% weight on win rate
SCORE_AVG_RETURN_WEIGHT  = 0.4   # 40% weight on average return

# ──────────────────────────────────────────────────────────────
# TRADE MIRRORING
# ──────────────────────────────────────────────────────────────
MAX_POSITION_SIZE_PCT    = 0.05  # Max 5% of equity per mirrored trade
MIRROR_STOP_LOSS_PCT     = 0.05  # 5% stop-loss on every mirrored trade
MIRROR_TAKE_PROFIT_PCT   = 0.12  # 12% take-profit target
MAX_OPEN_POSITIONS       = 10    # Don't open more than 10 concurrent positions
SKIP_IF_DISCLOSED_DAYS   = 7     # Skip if trade was disclosed more than 7 days ago

# ──────────────────────────────────────────────────────────────
# FILES
# ──────────────────────────────────────────────────────────────
TRADE_LOG_PATH       = "trades/trade_log.json"
POLITICIAN_SCORES_PATH = "trades/politician_scores.json"
SEEN_TRADES_PATH     = "trades/seen_trade_ids.json"
DAILY_REPORT_PATH    = "trades/daily_report.txt"
