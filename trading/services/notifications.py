"""
Push Notification Service — ntfy.sh integration for trade alerts.

Supports authenticated topics (NTFY_USER / NTFY_PASS) for private channels.
Configure via .env:
    NTFY_TOPIC=Alchemy-Trading-Dalio
    NTFY_USER=your_username      (optional — only needed for private topics)
    NTFY_PASS=your_password      (optional — only needed for private topics)
"""

import threading

import requests

from trading.utils.config import NTFY_PASS, NTFY_SERVER, NTFY_TOPIC, NTFY_USER
from trading.utils.database import log_event


def send_emergency_alert(title: str, message: str, priority: str = "urgent"):
    if not NTFY_TOPIC:
        log_event("notify", "NTFY_TOPIC not configured — notification skipped", "warning")
        return False

    def _send():
        try:
            kwargs = dict(
                url=f"{NTFY_SERVER}/{NTFY_TOPIC}",
                data=message.encode("utf-8"),
                headers={
                    "Title":    title,
                    "Priority": priority,
                    "Tags":     "rotating_light,warning",
                },
                timeout=10,
            )
            if NTFY_USER and NTFY_PASS:
                kwargs["auth"] = (NTFY_USER, NTFY_PASS)

            resp = requests.post(**kwargs)
            if resp.status_code in (200, 201):
                log_event("notify", f"NTFY alert sent: {title}", "info")
            else:
                log_event("notify", f"NTFY failed ({resp.status_code}): {resp.text[:100]}", "error")
        except Exception as e:
            log_event("notify", f"NTFY error: {e}", "error")

    threading.Thread(target=_send, daemon=True).start()
    return True


def send_notification(title: str, message: str, priority: str = "default"):
    return send_emergency_alert(title, message, priority)
