import json
import os
import threading
from datetime import datetime
from functools import wraps
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from trading.services.managed_agent import get_managed_agent
from trading.utils.database import log_event

import secrets as _secrets

_default_key = _secrets.token_urlsafe(32)
TOOL_SERVER_API_KEY = os.environ.get("TOOL_SERVER_API_KEY", "") or _default_key
TOOL_SERVER_PORT = 8098


def _parse_body(handler) -> dict:
    content_length = int(handler.headers.get("Content-Length", 0))
    if content_length > 0:
        body = handler.rfile.read(content_length)
        try:
            return json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
    return {}


def _send_json(handler, status: int, data: dict):
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(json.dumps(data, default=str).encode())


def _validate_auth(handler) -> bool:
    api_key = handler.headers.get("X-API-Key", "")
    if api_key != TOOL_SERVER_API_KEY:
        _send_json(handler, 401, {"error": "Invalid API key"})
        return False
    return True


def _validate_session(handler) -> bool:
    agent = get_managed_agent()
    if not agent or not agent.session_active:
        _send_json(handler, 404, {"error": "No active managed agent session"})
        return False

    session_token = handler.headers.get("X-Session-Token", "")
    if not agent.validate_session_token(session_token):
        _send_json(handler, 403, {"error": "Invalid session token"})
        return False

    return True


class ToolServerHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Key, X-Session-Token")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/tool/health":
            agent = get_managed_agent()
            _send_json(self, 200, {
                "status": "ok",
                "service": "alchemical-tool-server",
                "timestamp": datetime.utcnow().isoformat(),
                "agent_active": agent is not None and agent.session_active,
            })
            return

        if path == "/tool/session/info":
            if not _validate_auth(self):
                return
            if not _validate_session(self):
                return
            agent = get_managed_agent()
            _send_json(self, 200, agent.get_session_info())
            return

        if path == "/tool/heartbeat":
            if not _validate_auth(self):
                return
            if not _validate_session(self):
                return
            agent = get_managed_agent()
            _send_json(self, 200, agent.heartbeat())
            return

        _send_json(self, 404, {"error": "Not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/tool/session/start":
            if not _validate_auth(self):
                return
            agent = get_managed_agent()
            if not agent:
                _send_json(self, 404, {"error": "No managed agent instance configured"})
                return
            body = _parse_body(self)
            result = agent.start_session(api_key=TOOL_SERVER_API_KEY)
            _send_json(self, 200, result)
            return

        if path == "/tool/broker_trade":
            if not _validate_auth(self):
                return
            if not _validate_session(self):
                return
            body = _parse_body(self)
            symbol = body.get("symbol", "")
            side = body.get("side", "")
            qty = body.get("qty", 0)
            if not symbol or not side or qty <= 0:
                _send_json(self, 400, {"error": "Missing required fields: symbol, side, qty"})
                return
            agent = get_managed_agent()
            result = agent.broker_trade(symbol, side, int(qty))
            status_code = 200 if result.get("success") else 400
            _send_json(self, status_code, result)
            return

        if path == "/tool/fetch_alchemical_context":
            if not _validate_auth(self):
                return
            if not _validate_session(self):
                return
            agent = get_managed_agent()
            result = agent.fetch_alchemical_context()
            _send_json(self, 200, result)
            return

        if path == "/tool/terminate":
            if not _validate_auth(self):
                return
            agent = get_managed_agent()
            if not agent:
                _send_json(self, 404, {"error": "No managed agent instance"})
                return
            session_token = self.headers.get("X-Session-Token", "")
            if agent.session_active and not agent.validate_session_token(session_token):
                _send_json(self, 403, {"error": "Invalid session token"})
                return
            body = _parse_body(self)
            force = body.get("force", False)
            result = agent.terminate(force=force)
            _send_json(self, 200, result)
            return

        if path == "/tool/heartbeat":
            if not _validate_auth(self):
                return
            if not _validate_session(self):
                return
            agent = get_managed_agent()
            _send_json(self, 200, agent.heartbeat())
            return

        _send_json(self, 404, {"error": "Not found"})

    def log_message(self, format, *args):
        pass


_tool_server = None
_tool_server_thread = None


def start_tool_server(port: int = TOOL_SERVER_PORT):
    global _tool_server, _tool_server_thread
    if _tool_server is not None:
        return _tool_server

    try:
        _tool_server = HTTPServer(("0.0.0.0", port), ToolServerHandler)
        _tool_server_thread = threading.Thread(
            target=_tool_server.serve_forever, daemon=True, name="tool-server"
        )
        _tool_server_thread.start()
        log_event("tool_server", f"Tool server started on port {port}", "info")
        return _tool_server
    except Exception as e:
        log_event("tool_server", f"Tool server start error: {e}", "error")
        _tool_server = None
        return None


def stop_tool_server():
    global _tool_server
    if _tool_server:
        _tool_server.shutdown()
        _tool_server = None
        log_event("tool_server", "Tool server stopped", "info")
