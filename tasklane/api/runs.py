from __future__ import annotations
"""
/runs routes — run detail, SSE log stream, kill.
"""

import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from tasklane.core.db import execute_write, get_db
from tasklane.core.models import LogEntryOut, RunOut

router = APIRouter(prefix="/runs", tags=["runs"])


def _get_run_or_404(run_id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return row


# ---------------------------------------------------------------------------
# GET /runs/{id}
# ---------------------------------------------------------------------------

@router.get("/{run_id}", response_model=RunOut)
def get_run(run_id: int):
    return RunOut.from_row(_get_run_or_404(run_id))


# ---------------------------------------------------------------------------
# GET /runs/{id}/logs  — paginated log tail
# ---------------------------------------------------------------------------

@router.get("/{run_id}/logs", response_model=list[LogEntryOut])
def get_logs(run_id: int, after_seq: int = 0, limit: int = 500):
    _get_run_or_404(run_id)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM logs WHERE run_id = ? AND seq > ? ORDER BY seq LIMIT ?",
            (run_id, after_seq, limit),
        ).fetchall()
    return [LogEntryOut.from_row(r) for r in rows]


# ---------------------------------------------------------------------------
# GET /runs/{id}/stream  — SSE live log stream
# ---------------------------------------------------------------------------

@router.get("/{run_id}/stream")
async def stream_logs(run_id: int, after_seq: int = 0):
    """
    Server-Sent Events endpoint. Replays logs from after_seq, then streams
    new entries as the agent emits them. Emits 'event: done' when run ends.
    """
    from tasklane.core.pubsub import subscribe, unsubscribe

    _get_run_or_404(run_id)

    async def generate():
        q: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        # Replay existing logs first
        with get_db() as conn:
            existing = conn.execute(
                "SELECT * FROM logs WHERE run_id = ? AND seq > ? ORDER BY seq",
                (run_id, after_seq),
            ).fetchall()

        for row in existing:
            entry = LogEntryOut.from_row(row)
            yield f"data: {entry.model_dump_json()}\n\n"

        # Check if run is already done — if so, send done and exit
        with get_db() as conn:
            run = conn.execute("SELECT status FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        if run and run["status"] != "running":
            yield "event: done\ndata: {}\n\n"
            return

        # Subscribe to live updates
        subscribe(run_id, q, loop)

        try:
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    # Heartbeat to keep connection alive
                    yield ": heartbeat\n\n"
                    continue

                if item is None:  # sentinel: run ended
                    yield "event: done\ndata: {}\n\n"
                    break

                yield f"data: {json.dumps(item)}\n\n"
        finally:
            unsubscribe(run_id, q)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# POST /runs/{id}/kill
# ---------------------------------------------------------------------------

@router.post("/{run_id}/kill", status_code=202)
def kill_run_endpoint(run_id: int):
    from tasklane.orchestration.runner import kill_run

    row = _get_run_or_404(run_id)
    if row["status"] != "running":
        raise HTTPException(status_code=409, detail=f"Run {run_id} is not running (status={row['status']})")

    kill_run(run_id)
    return {"detail": "Kill signal sent. Run will stop within one iteration."}
