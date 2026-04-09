"""
Launcher script — initializes database and launches Streamlit.
Healthcheck starts inside Streamlit process to share memory with agent heartbeat.
"""

import subprocess
import sys

from trading.utils.database import init_db

init_db()

proc = subprocess.Popen(
    [sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", "5000"],
    stdout=sys.stdout,
    stderr=sys.stderr,
)

try:
    proc.wait()
except KeyboardInterrupt:
    proc.terminate()
    proc.wait()

sys.exit(proc.returncode)
