"""
Healthcheck HTTP server for Replit Deployments (Reserved VM).

Runs a lightweight HTTP server on port 8099 that responds to /health
with a JSON status payload. Streamlit itself runs on port 5000.

Reports:
  - Database connectivity
  - Agent loop status (alive, last heartbeat, uptime)
  - Running bot count
"""

import json
import threading
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

from trading.utils.database import init_db, SessionLocal, SystemEvent

_agent_heartbeat = {
    "alive": False,
    "last_heartbeat": None,
    "start_time": None,
    "cycle_count": 0,
    "running_bots": 0,
}
_heartbeat_lock = threading.Lock()


def update_agent_heartbeat(alive: bool = True, cycle_count: int = 0, running_bots: int = 0):
    with _heartbeat_lock:
        _agent_heartbeat["alive"] = alive
        _agent_heartbeat["last_heartbeat"] = time.time()
        _agent_heartbeat["cycle_count"] = cycle_count
        _agent_heartbeat["running_bots"] = running_bots
        if alive and _agent_heartbeat["start_time"] is None:
            _agent_heartbeat["start_time"] = time.time()
        if not alive:
            _agent_heartbeat["start_time"] = None


def get_agent_heartbeat() -> dict:
    with _heartbeat_lock:
        return dict(_agent_heartbeat)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health" or self.path == "/":
            status = {
                "status": "healthy",
                "service": "alchemical-trading-command-center",
                "timestamp": datetime.utcnow().isoformat(),
                "streamlit_port": 5000,
            }

            try:
                db = SessionLocal()
                db.query(SystemEvent).limit(1).all()
                db.close()
                status["database"] = "connected"
            except Exception as e:
                status["database"] = f"error: {str(e)[:80]}"
                status["status"] = "degraded"

            hb = get_agent_heartbeat()
            now = time.time()
            last_hb = hb.get("last_heartbeat")
            heartbeat_age = round(now - last_hb, 1) if last_hb else None
            uptime = round(now - hb["start_time"], 1) if hb.get("start_time") else None

            status["agent"] = {
                "alive": hb["alive"],
                "last_heartbeat": datetime.utcfromtimestamp(last_hb).isoformat() if last_hb else None,
                "heartbeat_age_seconds": heartbeat_age,
                "uptime_seconds": uptime,
                "cycle_count": hb["cycle_count"],
                "running_bots": hb["running_bots"],
            }

            if last_hb and heartbeat_age and heartbeat_age > 600:
                status["status"] = "degraded"
                status["agent"]["warning"] = "No heartbeat in over 10 minutes"

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(status).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def start_healthcheck(port=8099):
    import socket
    class ReusableHTTPServer(HTTPServer):
        allow_reuse_address = True
        def server_bind(self):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            super().server_bind()

    server = ReusableHTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
