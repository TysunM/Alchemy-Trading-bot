"""
Notifier — Alerts and Notifications
Currently: console output + optional webhook (Discord/Slack compatible).
To enable webhook: set WEBHOOK_URL in this file or in config.
"""

import json
import requests
from datetime import datetime

# Set to your Discord/Slack webhook URL to get push notifications
WEBHOOK_URL = None   # e.g. "https://discord.com/api/webhooks/..."


def _send_webhook(message: str):
    if not WEBHOOK_URL:
        return
    try:
        payload = {"content": message} if "discord" in WEBHOOK_URL else {"text": message}
        requests.post(WEBHOOK_URL, json=payload, timeout=5)
    except Exception as e:
        print(f"[Notifier] Webhook failed: {e}")


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ──────────────────────────────────────────────────────────────
# Alert types
# ──────────────────────────────────────────────────────────────

def notify_kill_switch(reason: str):
    msg = (f"🚨 [{_ts()}] KILL SWITCH TRIGGERED\n"
           f"Reason: {reason}\n"
           f"All orders cancelled. All positions closed.")
    print(msg)
    _send_webhook(msg)


def notify_trade_opened(trade: dict):
    msg = (f"📈 [{_ts()}] TRADE OPENED\n"
           f"  {trade.get('symbol')} {trade.get('direction')} "
           f"x{trade.get('qty')} @ ${trade.get('entry_price'):.2f}\n"
           f"  Strategy {trade.get('strategy')} | Regime: {trade.get('regime')}\n"
           f"  SL: ${trade.get('sl'):.2f}  TP: ${trade.get('tp'):.2f}\n"
           f"  Confidence: {trade.get('confidence', 0)*100:.0f}%")
    print(msg)
    _send_webhook(msg)


def notify_trade_closed(trade: dict):
    pnl  = trade.get('pnl', 0)
    icon = "✅" if pnl >= 0 else "❌"
    msg = (f"{icon} [{_ts()}] TRADE CLOSED\n"
           f"  {trade.get('symbol')} — {trade.get('exit_reason')}\n"
           f"  Entry: ${trade.get('entry_price'):.2f}  "
           f"Exit: ${trade.get('exit_price'):.2f}\n"
           f"  P&L: ${pnl:+.2f}  ({trade.get('pnl_pct', 0)*100:+.2f}%)")
    print(msg)
    _send_webhook(msg)


def notify_feedback_report(report: dict):
    adj = report.get("adjustments", {})
    insights = report.get("insights", [])
    msg = (f"🔬 [{_ts()}] FEEDBACK LOOP (after {report.get('trade_count',20)} trades)\n"
           f"  Win rate: {report.get('win_rate', 0)*100:.1f}%\n"
           f"  Profit factor: {report.get('profit_factor', 0):.2f}\n"
           f"  Adjustments: {json.dumps(adj, indent=2) if adj else 'None'}\n"
           f"  Insights: {chr(10).join('  • '+i for i in insights)}")
    print(msg)
    _send_webhook(msg)


def notify_info(message: str):
    msg = f"ℹ️  [{_ts()}] {message}"
    print(msg)
    _send_webhook(msg)


def notify_error(message: str):
    msg = f"⛔ [{_ts()}] ERROR: {message}"
    print(msg)
    _send_webhook(msg)
