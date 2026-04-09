"""
Politician Ranker
Scores every politician by how well their trade disclosures predicted price movement.

Scoring method
──────────────
For each historical trade (>30 days old):
  • BUY:  win if close_price(pubDate + 30d) > close_price(pubDate)
  • SELL: win if close_price(pubDate + 30d) < close_price(pubDate)

Politician score = (WIN_RATE_WEIGHT × win_rate) + (AVG_RETURN_WEIGHT × normalized_avg_return)
Only politicians with ≥ MIN_TRADES_FOR_RANKING evaluated trades are ranked.

Price data is fetched from Alpaca's historical data API.
"""

import json
import os
import time
import requests
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from config import (
    ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_DATA_URL,
    MIN_TRADES_FOR_RANKING, PERFORMANCE_LOOKBACK_DAYS,
    SCORE_WIN_RATE_WEIGHT, SCORE_AVG_RETURN_WEIGHT,
    POLITICIAN_SCORES_PATH,
)


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

def rank_politicians(trades: list) -> list:
    """
    Given a list of trade records, score and rank politicians.

    Parameters
    ----------
    trades : All historical trades from Capitol Fetcher

    Returns
    -------
    List of politician score dicts, sorted best → worst.
    Saved to POLITICIAN_SCORES_PATH for persistence.
    """
    print("[Ranker] Building politician performance scores...")

    # ── Group trades by politician ────────────────────────────
    by_politician = defaultdict(list)
    for t in trades:
        by_politician[t["politicianId"]].append(t)

    # ── Score each politician ─────────────────────────────────
    cutoff = datetime.now(timezone.utc) - timedelta(days=PERFORMANCE_LOOKBACK_DAYS + 5)
    scores = []

    for pol_id, pol_trades in by_politician.items():
        # Only evaluate trades old enough to measure outcome
        evaluable = [
            t for t in pol_trades
            if _parse_date(t["pubDate"]) < cutoff
        ]
        if len(evaluable) < MIN_TRADES_FOR_RANKING:
            continue

        wins, total, returns = _evaluate_trades(evaluable)
        win_rate   = wins / total if total > 0 else 0
        avg_return = sum(returns) / len(returns) if returns else 0

        # Normalize avg_return to 0-1 scale for scoring (cap at ±30%)
        norm_return = min(max((avg_return + 0.30) / 0.60, 0), 1)
        score = (SCORE_WIN_RATE_WEIGHT * win_rate +
                 SCORE_AVG_RETURN_WEIGHT * norm_return)

        sample = pol_trades[0]
        scores.append({
            "politicianId":  pol_id,
            "politician":    sample["politician"],
            "party":         sample["party"],
            "chamber":       sample["chamber"],
            "evaluated":     total,
            "total_trades":  len(pol_trades),
            "wins":          wins,
            "win_rate":      round(win_rate, 4),
            "avg_return":    round(avg_return, 4),
            "score":         round(score, 4),
        })

    scores.sort(key=lambda x: x["score"], reverse=True)
    _save_scores(scores)

    print(f"[Ranker] Ranked {len(scores)} politicians.")
    for s in scores[:10]:
        print(f"  {s['politician']:30s}  score={s['score']:.3f}  "
              f"win={s['win_rate']*100:.0f}%  trades={s['evaluated']}")

    return scores


def load_scores() -> list:
    """Load persisted politician scores."""
    if not os.path.exists(POLITICIAN_SCORES_PATH):
        return []
    with open(POLITICIAN_SCORES_PATH) as f:
        return json.load(f)


def get_top_politicians(n: int = 5) -> list:
    """Return the top N politicians by score."""
    scores = load_scores()
    return scores[:n]


# ──────────────────────────────────────────────────────────────
# Trade evaluation
# ──────────────────────────────────────────────────────────────

# Price cache to avoid hammering Alpaca: {(ticker, date): price}
_price_cache: dict = {}


def _evaluate_trades(trades: list) -> tuple:
    """
    Returns (wins, total_evaluated, list_of_returns).
    Skips trades where price data is unavailable.
    """
    wins, total, returns = 0, 0, []

    for t in trades:
        ticker   = t["ticker"]
        pub_date = _parse_date(t["pubDate"])
        end_date = pub_date + timedelta(days=PERFORMANCE_LOOKBACK_DAYS)

        entry_price = _get_close_price(ticker, pub_date)
        exit_price  = _get_close_price(ticker, end_date)

        if entry_price is None or exit_price is None:
            continue

        ret = (exit_price - entry_price) / entry_price

        tx_type = t.get("txType", "buy").lower()
        if tx_type == "sell":
            ret = -ret    # For sells, falling price is a win

        if ret > 0:
            wins += 1

        returns.append(ret)
        total += 1

        time.sleep(0.15)   # Polite rate limiting on Alpaca

    return wins, total, returns


def _get_close_price(ticker: str, target_date: datetime) -> float | None:
    """
    Get the closing price for a ticker on or just after target_date.
    Uses Alpaca historical data API. Returns None on failure.
    """
    cache_key = (ticker, target_date.strftime("%Y-%m-%d"))
    if cache_key in _price_cache:
        return _price_cache[cache_key]

    # Search a 5-day window in case target_date is a weekend/holiday
    end_date   = target_date + timedelta(days=5)
    url        = f"{ALPACA_DATA_URL}/v2/stocks/{ticker}/bars"
    headers    = {
        "APCA-API-KEY-ID":     ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }
    params = {
        "timeframe":  "1Day",
        "start":      target_date.strftime("%Y-%m-%dT00:00:00Z"),
        "end":        end_date.strftime("%Y-%m-%dT23:59:59Z"),
        "limit":      5,
        "adjustment": "split",
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        bars = resp.json().get("bars", [])
        if bars:
            price = float(bars[0]["c"])
            _price_cache[cache_key] = price
            return price
    except Exception:
        pass

    return None


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _parse_date(date_str: str) -> datetime:
    """Parse ISO date string to timezone-aware datetime."""
    if "T" in date_str:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    else:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _save_scores(scores: list):
    os.makedirs(os.path.dirname(POLITICIAN_SCORES_PATH), exist_ok=True)
    with open(POLITICIAN_SCORES_PATH, "w") as f:
        json.dump(scores, f, indent=2)
