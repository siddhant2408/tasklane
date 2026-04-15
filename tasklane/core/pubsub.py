from __future__ import annotations
"""
In-process pub/sub for SSE log fan-out.

Agent threads call publish(run_id, entry) to broadcast log entries.
SSE handlers subscribe/unsubscribe asyncio Queues per run.
"""

import asyncio
import threading
from typing import Any

_lock = threading.Lock()
# run_id -> list of (asyncio.Queue, event_loop) pairs
_subscribers: dict[int, list[tuple[asyncio.Queue, asyncio.AbstractEventLoop]]] = {}


def subscribe(run_id: int, q: asyncio.Queue, loop: asyncio.AbstractEventLoop) -> None:
    with _lock:
        _subscribers.setdefault(run_id, []).append((q, loop))


def unsubscribe(run_id: int, q: asyncio.Queue) -> None:
    with _lock:
        subs = _subscribers.get(run_id, [])
        _subscribers[run_id] = [(sq, sl) for sq, sl in subs if sq is not q]


def publish(run_id: int, entry: dict[str, Any]) -> None:
    """Called from agent thread — thread-safe, puts entry onto each subscriber queue."""
    with _lock:
        subs = list(_subscribers.get(run_id, []))
    for q, loop in subs:
        try:
            loop.call_soon_threadsafe(q.put_nowait, entry)
        except Exception:
            pass


def publish_done(run_id: int) -> None:
    """Signal all subscribers that the run has ended (sentinel=None)."""
    with _lock:
        subs = list(_subscribers.get(run_id, []))
    for q, loop in subs:
        try:
            loop.call_soon_threadsafe(q.put_nowait, None)
        except Exception:
            pass
    with _lock:
        _subscribers.pop(run_id, None)
