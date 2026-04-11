"""
Thread-safe agent state container shared by agent_loop, managed_agent, and the Streamlit UI.
"""

import threading
from typing import Optional


class AgentState:
    """Tracks the lifecycle and metrics of a running agent loop."""

    def __init__(self):
        self.running: bool = False
        self.status: str = "idle"
        self.cycle_count: int = 0
        self.errors: int = 0
        self.total_tool_calls: int = 0
        self.total_trades: int = 0
        self.last_cycle_time: Optional[str] = None
        self.last_cycle_result: Optional[dict] = None
        self.last_run: Optional[str] = None
        self.last_result: Optional[dict] = None
        self.last_error: Optional[str] = None
        self._history: list = []
        self._lock = threading.Lock()

    def update(self, **kwargs):
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self, key):
                    setattr(self, key, value)

    def add_history(self, entry: dict):
        with self._lock:
            self._history.append(entry)
            if len(self._history) > 50:
                self._history = self._history[-50:]

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "status": self.status,
                "cycle_count": self.cycle_count,
                "errors": self.errors,
                "total_tool_calls": self.total_tool_calls,
                "total_trades": self.total_trades,
                "last_cycle_time": self.last_cycle_time,
                "last_run": self.last_run,
                "last_error": self.last_error,
                "history": list(self._history[-10:]),
            }
