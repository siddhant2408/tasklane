from __future__ import annotations
"""
/tickets routes — CRUD + status PATCH.

The status PATCH is the trigger point: after updating the DB, it calls
scheduler.on_status_change() which decides whether to spawn an agent.
"""

import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from tasklane.core.db import execute_write, execute_write_many, get_db
from tasklane.core.enums import AGENT_LANES, LANE_ORDER, Status
from tasklane.core.models import (
    BoardOut,
    TicketCreate,
    TicketOut,
    TicketStatusChange,
    TicketUpdate,
)

router = APIRouter(prefix="/tickets", tags=["tickets"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_ticket_or_404(ticket_id: int) -> dict:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")
    return row


def _active_run_id(ticket_id: int) -> int | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM agent_runs WHERE ticket_id = ? AND status = 'running' LIMIT 1",
            (ticket_id,),
        ).fetchone()
    return row["id"] if row else None


def _audit(ticket_id: int, actor: str, event: str, from_status: str | None = None,
           to_status: str | None = None, note: str | None = None) -> None:
    execute_write(
        "INSERT INTO ticket_audit (ticket_id, actor, event, from_status, to_status, note) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ticket_id, actor, event, from_status, to_status, note),
    )


# ---------------------------------------------------------------------------
# GET /tickets
# ---------------------------------------------------------------------------

@router.get("", response_model=list[TicketOut])
def list_tickets():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM tickets ORDER BY id DESC").fetchall()
    result = []
    for row in rows:
        result.append(TicketOut.from_row(row, _active_run_id(row["id"])))
    return result


# ---------------------------------------------------------------------------
# POST /tickets
# ---------------------------------------------------------------------------

@router.post("", response_model=TicketOut, status_code=201)
def create_ticket(body: TicketCreate):
    # Validate workspace path exists
    if not os.path.exists(body.workspace_path):
        raise HTTPException(
            status_code=422,
            detail=f"workspace_path '{body.workspace_path}' does not exist",
        )

    execute_write(
        """INSERT INTO tickets
             (title, description, persona, urgency, tools_json, agents_json,
              models_json, workspace_path, max_iterations)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            body.title,
            body.description,
            body.persona.value,
            body.urgency.value,
            json.dumps(body.tools_json),
            json.dumps(body.agents_json) if body.agents_json is not None else None,
            json.dumps(body.models_json),
            body.workspace_path,
            body.max_iterations,
        ),
    )

    with get_db() as conn:
        row = conn.execute("SELECT * FROM tickets ORDER BY id DESC LIMIT 1").fetchone()

    _audit(row["id"], "human", "created")
    return TicketOut.from_row(row)


# ---------------------------------------------------------------------------
# GET /tickets/{id}
# ---------------------------------------------------------------------------

@router.get("/{ticket_id}", response_model=TicketOut)
def get_ticket(ticket_id: int):
    row = _get_ticket_or_404(ticket_id)
    return TicketOut.from_row(row, _active_run_id(ticket_id))


# ---------------------------------------------------------------------------
# PATCH /tickets/{id}  — edit fields (not status)
# ---------------------------------------------------------------------------

@router.patch("/{ticket_id}", response_model=TicketOut)
def update_ticket(ticket_id: int, body: TicketUpdate):
    row = _get_ticket_or_404(ticket_id)

    if row["locked"]:
        raise HTTPException(status_code=409, detail="Ticket is locked — a run is active")

    # Validate new workspace path if provided
    if body.workspace_path is not None and not os.path.exists(body.workspace_path):
        raise HTTPException(
            status_code=422,
            detail=f"workspace_path '{body.workspace_path}' does not exist",
        )

    updates: list[tuple[str, tuple]] = []
    fields = {
        "title": body.title,
        "description": body.description,
        "urgency": body.urgency.value if body.urgency else None,
        "tools_json": json.dumps(body.tools_json) if body.tools_json is not None else None,
        "agents_json": json.dumps(body.agents_json) if body.agents_json is not None else None,
        "models_json": json.dumps(body.models_json) if body.models_json is not None else None,
        "workspace_path": body.workspace_path,
        "max_iterations": body.max_iterations,
    }

    set_clauses = []
    params: list = []
    for col, val in fields.items():
        if val is not None:
            set_clauses.append(f"{col} = ?")
            params.append(val)

    if not set_clauses:
        return TicketOut.from_row(row)

    set_clauses.append("updated_at = datetime('now')")
    params.append(ticket_id)

    execute_write(
        f"UPDATE tickets SET {', '.join(set_clauses)} WHERE id = ?",
        tuple(params),
    )

    _audit(ticket_id, "human", "edited")
    with get_db() as conn:
        updated = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    return TicketOut.from_row(updated, _active_run_id(ticket_id))


# ---------------------------------------------------------------------------
# PATCH /tickets/{id}/status  — lane transition (the agent trigger)
# ---------------------------------------------------------------------------

@router.patch("/{ticket_id}/status", response_model=TicketOut)
def change_status(ticket_id: int, body: TicketStatusChange, force: bool = False):
    from tasklane.orchestration.scheduler import on_status_change  # late import avoids circular

    row = _get_ticket_or_404(ticket_id)
    old_status = row["status"]
    new_status = body.to.value

    if old_status == new_status:
        return TicketOut.from_row(row, _active_run_id(ticket_id))

    # If ticket is locked (run active), require force=true
    if row["locked"] and not force:
        raise HTTPException(
            status_code=409,
            detail="A run is active. Pass ?force=true to kill it and move.",
        )

    if row["locked"] and force:
        # Kill the active run
        active_id = _active_run_id(ticket_id)
        if active_id:
            from tasklane.orchestration.runner import kill_run
            kill_run(active_id)

    execute_write_many([
        (
            "UPDATE tickets SET status = ?, locked = 0, updated_at = datetime('now') WHERE id = ?",
            (new_status, ticket_id),
        ),
    ])

    _audit(ticket_id, "human", "status_change", old_status, new_status)

    # Trigger agent spawn if this is an agent lane
    on_status_change(ticket_id, Status(new_status), body.model)

    with get_db() as conn:
        updated = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    return TicketOut.from_row(updated, _active_run_id(ticket_id))


# ---------------------------------------------------------------------------
# DELETE /tickets/{id}
# ---------------------------------------------------------------------------

@router.delete("/{ticket_id}", status_code=204)
def delete_ticket(ticket_id: int):
    row = _get_ticket_or_404(ticket_id)

    if row["locked"]:
        raise HTTPException(status_code=409, detail="Ticket is locked — kill the run first")

    execute_write("DELETE FROM tickets WHERE id = ?", (ticket_id,))


# ---------------------------------------------------------------------------
# GET /tickets/{id}/runs
# ---------------------------------------------------------------------------

@router.get("/{ticket_id}/runs")
def list_runs_for_ticket(ticket_id: int):
    _get_ticket_or_404(ticket_id)
    from tasklane.core.models import RunOut
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_runs WHERE ticket_id = ? ORDER BY id DESC",
            (ticket_id,),
        ).fetchall()
    return [RunOut.from_row(r) for r in rows]


# ---------------------------------------------------------------------------
# GET /board
# ---------------------------------------------------------------------------

@router.get("/../board", response_model=BoardOut, include_in_schema=False)
def get_board():
    # Implemented in server.py to avoid prefix issues
    pass
