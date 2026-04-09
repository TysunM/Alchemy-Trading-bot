"""
Push Notification Service — NTFY integration for emergency alerts.

Sends push notifications to the operator's phone via ntfy.sh.
Configure with NTFY_TOPIC environment variable.
"""

import threading

import requests

from trading.utils.config import NTFY_TOPIC
from trading.utils.database import log_event


def send_emergency_alert(title: str, message: str, priority: str = "urgent"):
    if not NTFY_TOPIC:
        log_event("notify", "NTFY_TOPIC not configured — notification skipped", "warning")
        return False

    def _send():
        try:
            resp = requests.post(
                f"https://ntfy.sh/{NTFY_TOPIC}",
                data=message.encode("utf-8"),
                headers={
                    "Title": title,
                    "Priority": priority,
                    "Tags": "rotating_light,warning",
                },
                timeout=10,
            )
            if resp.status_code == 200:
                log_event("notify", f"NTFY alert sent: {title}", "info")
            else:
                log_event("notify", f"NTFY failed ({resp.status_code}): {resp.text[:100]}", "error")
        except Exception as e:
            log_event("notify", f"NTFY error: {e}", "error")

    threading.Thread(target=_send, daemon=True).start()
    return True


def send_notification(title: str, message: str, priority: str = "default"):
    return send_emergency_alert(title, message, priority)
