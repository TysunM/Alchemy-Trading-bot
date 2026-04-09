"""
Politician Ranker
Scores every politician by how well their trade disclosures predicted price movement.

Scoring method: For each historical trade (>30 days old):
  BUY:  win if close(pubDate + 30d) > close(pubDate)
  SELL: win if close(pubDate + 30d) < close(pubDate)

Score = (0.6 * win_rate) + (0.4 * normalized_avg_return)
Only politicians with >= MIN_TRADES evaluated trades are ranked.
"""

import json
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

from trading.utils.config import ALPACA_API_KEY, ALPACA_SECRET_KEY
from trading.utils.database import SessionLocal, log_event

ALPACA_DATA_URL = "https://data.alpaca.markets"
MIN_TRADES_FOR_RANKING = 10
PERFORMANCE_LOOKBACK_DAYS = 30
SCORE_WIN_RATE_WEIGHT = 0.6
SCORE_AVG_RETURN_WEIGHT = 0.4

_price_cache: dict = {}


def rank_politicians(trades: list) -> list:
    log_event("ranker", f"Building performance scores from {len(trades)} trades...", "info")

    by_politician = defaultdict(list)
    for t in trades:
        by_politician[t["politicianId"]].append(t)

    cutoff = datetime.now(timezone.utc) - timedelta(days=PERFORMANCE_LOOKBACK_DAYS + 5)
    scores = []

    for pol_id, pol_trades in by_politician.items():
        evaluable = [t for t in pol_trades if _parse_date(t["pubDate"]) < cutoff]
        if len(evaluable) < MIN_TRADES_FOR_RANKING:
            continue

        wins, total, returns = _evaluate_trades(evaluable)
        win_rate = wins / total if total > 0 else 0
        avg_return = sum(returns) / len(returns) if returns else 0

        norm_return = min(max((avg_return + 0.30) / 0.60, 0), 1)
        score = SCORE_WIN_RATE_WEIGHT * win_rate + SCORE_AVG_RETURN_WEIGHT * norm_return

        sample = pol_trades[0]
        scores.append({
            "politicianId": pol_id,
            "politician": sample["politician"],
            "party": sample["party"],
            "chamber": sample["chamber"],
            "evaluated": total,
            "total_trades": len(pol_trades),
            "wins": wins,
            "win_rate": round(win_rate, 4),
            "avg_return": round(avg_return, 4),
            "score": round(score, 4),
        })

    scores.sort(key=lambda x: x["score"], reverse=True)
    save_scores(scores)
    log_event("ranker", f"Ranked {len(scores)} politicians.", "info")
    return scores


def save_scores(scores: list):
    db = SessionLocal()
    try:
        from sqlalchemy import text
        db.execute(text("DELETE FROM politician_scores"))
        for s in scores:
            db.execute(
                text("""INSERT INTO politician_scores
                    (politician_id, name, party, chamber, evaluated, total_trades,
                     wins, win_rate, avg_return, score)
                    VALUES (:pid, :name, :party, :chamber, :evaluated, :total_trades,
                            :wins, :win_rate, :avg_return, :score)"""),
                {
                    "pid": s["politicianId"],
                    "name": s["politician"],
                    "party": s["party"],
                    "chamber": s["chamber"],
                    "evaluated": s["evaluated"],
                    "total_trades": s["total_trades"],
                    "wins": s["wins"],
                    "win_rate": s["win_rate"],
                    "avg_return": s["avg_return"],
                    "score": s["score"],
                },
            )
        db.commit()
    except Exception as e:
        log_event("ranker", f"Save scores error: {e}", "error")
    finally:
        db.close()


def load_scores() -> list:
    db = SessionLocal()
    try:
        from sqlalchemy import text
        rows = db.execute(text("SELECT * FROM politician_scores ORDER BY score DESC")).fetchall()
        return [
            {
                "politicianId": r[1],
                "politician": r[2],
                "party": r[3],
                "chamber": r[4],
                "evaluated": r[5],
                "total_trades": r[6],
                "wins": r[7],
                "win_rate": r[8],
                "avg_return": r[9],
                "score": r[10],
            }
            for r in rows
        ]
    except Exception:
        return []
    finally:
        db.close()


def get_top_politicians(n: int = 5) -> list:
    return load_scores()[:n]


def _evaluate_trades(trades: list) -> tuple:
    wins, total, returns = 0, 0, []
    for t in trades:
        ticker = t["ticker"]
        pub_date = _parse_date(t["pubDate"])
        end_date = pub_date + timedelta(days=PERFORMANCE_LOOKBACK_DAYS)

        entry_price = _get_close_price(ticker, pub_date)
        exit_price = _get_close_price(ticker, end_date)

        if entry_price is None or exit_price is None:
            continue

        ret = (exit_price - entry_price) / entry_price
        if t.get("txType", "buy").lower() == "sell":
            ret = -ret

        if ret > 0:
            wins += 1
        returns.append(ret)
        total += 1
        time.sleep(0.15)

    return wins, total, returns


def _get_close_price(ticker: str, target_date: datetime) -> float | None:
    cache_key = (ticker, target_date.strftime("%Y-%m-%d"))
    if cache_key in _price_cache:
        return _price_cache[cache_key]

    end_date = target_date + timedelta(days=5)
    headers = {
        "APCA-API-KEY-ID": ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    }
    params = {
        "timeframe": "1Day",
        "start": target_date.strftime("%Y-%m-%dT00:00:00Z"),
        "end": end_date.strftime("%Y-%m-%dT23:59:59Z"),
        "limit": 5,
        "adjustment": "split",
    }

    try:
        resp = requests.get(
            f"{ALPACA_DATA_URL}/v2/stocks/{ticker}/bars",
            headers=headers,
            params=params,
            timeout=10,
        )
        resp.raise_for_status()
        bars = resp.json().get("bars", [])
        if bars:
            price = float(bars[0]["c"])
            _price_cache[cache_key] = price
            return price
    except Exception:
        pass
    return None


def _parse_date(date_str: str) -> datetime:
    if "T" in date_str:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    else:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
