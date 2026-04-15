from __future__ import annotations
"""
RunLogger — tees log entries to three sinks:
  1. tasklane/runs/{run_id}.log  (plain text file, survives restart)
  2. logs table (via db write queue)
  3. in-process pubsub (for SSE fan-out)
"""

import os
import threading
from datetime import datetime, timezone

from tasklane.core.db import execute_write
from tasklane.core.enums import LogLevel
from tasklane.core.pubsub import publish

_RUNS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "runs")


class RunLogger:
    def __init__(self, run_id: int):
        self.run_id = run_id
        self._seq = 0
        self._lock = threading.Lock()
        os.makedirs(_RUNS_DIR, exist_ok=True)
        self._log_path = os.path.join(_RUNS_DIR, f"{run_id}.log")

    def _next_seq(self) -> int:
        with self._lock:
            self._seq += 1
            return self._seq

    def log(self, level: LogLevel, message: str) -> None:
        seq = self._next_seq()
        ts = datetime.now(timezone.utc).isoformat()

        # 1. File sink
        try:
            with open(self._log_path, "a") as f:
                f.write(f"[{ts}] [{level.value.upper():12s}] {message}\n")
        except Exception:
            pass

        # 2. DB sink (via write queue)
        try:
            execute_write(
                "INSERT INTO logs (run_id, seq, ts, level, message) VALUES (?, ?, ?, ?, ?)",
                (self.run_id, seq, ts, level.value, message),
            )
        except Exception:
            pass

        # 3. Pubsub sink
        entry = {"seq": seq, "ts": ts, "level": level.value, "message": message}
        publish(self.run_id, entry)

    # Convenience methods
    def info(self, msg: str) -> None:
        self.log(LogLevel.INFO, msg)

    def warn(self, msg: str) -> None:
        self.log(LogLevel.WARN, msg)

    def error(self, msg: str) -> None:
        self.log(LogLevel.ERROR, msg)

    def tool_use(self, name: str, input_preview: str) -> None:
        self.log(LogLevel.TOOL_USE, f"{name}({input_preview})")

    def tool_result(self, name: str, result_preview: str) -> None:
        self.log(LogLevel.TOOL_RESULT, f"{name} → {result_preview}")

    def assistant_text(self, text: str) -> None:
        self.log(LogLevel.ASSISTANT_TEXT, text[:500])
