from __future__ import annotations
"""
Scheduler — receives lane-change events and decides whether to spawn an agent.

Enforces:
- One active run per ticket
- Global MAX_CONCURRENT_RUNS cap (overflow → pending_runs table)
- Persona-based lane skipping
"""

import json
import threading

from tasklane.core.db import execute_write, get_db
from tasklane.core.enums import AGENT_LANES, Status
from tasklane.orchestration.lane_config import get_agent_type

MAX_CONCURRENT_RUNS = 4
_lock = threading.Lock()


def on_status_change(ticket_id: int, new_lane: Status, model: str) -> None:
    """
    Called after a lane change. Decides whether to spawn, queue, or skip.
    This is called from the HTTP handler (for human drags) and from
    runner._auto_advance (for agent-driven advances).
    """
    if new_lane not in AGENT_LANES:
        return  # non-agent lane — nothing to do

    with get_db() as conn:
        ticket = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if not ticket:
        return

    # Check persona's active_lanes
    if not _lane_active_for_ticket(ticket, new_lane.value):
        # Auto-advance through skipped lane
        _skip_lane(ticket_id, new_lane, model)
        return

    # Resolve agent type
    agents_json = json.loads(ticket["agents_json"]) if ticket["agents_json"] else None
    agent_type = get_agent_type(new_lane.value, agents_json)
    if agent_type is None:
        # Explicitly skipped via agents_json
        _skip_lane(ticket_id, new_lane, model)
        return

    with _lock:
        from tasklane.orchestration.runner import ACTIVE_RUNS
        active_count = len(ACTIVE_RUNS)

        if active_count < MAX_CONCURRENT_RUNS:
            _do_spawn(ticket_id, new_lane.value, model, agent_type)
        else:
            # Queue for later
            execute_write(
                "INSERT INTO pending_runs (ticket_id, lane, model) VALUES (?, ?, ?)",
                (ticket_id, new_lane.value, model),
            )
            _log_queued(ticket_id, new_lane.value)


def on_run_end(ticket_id: int) -> None:
    """Called when a run ends — pull next from the pending queue."""
    with _lock:
        with get_db() as conn:
            pending = conn.execute(
                "SELECT * FROM pending_runs ORDER BY id LIMIT 1"
            ).fetchone()

        if pending:
            execute_write("DELETE FROM pending_runs WHERE id = ?", (pending["id"],))
            agents_json_raw = None
            with get_db() as conn:
                t = conn.execute("SELECT agents_json FROM tickets WHERE id = ?", (pending["ticket_id"],)).fetchone()
            if t:
                agents_json_raw = json.loads(t["agents_json"]) if t["agents_json"] else None
            agent_type = get_agent_type(pending["lane"], agents_json_raw) or "coder"
            _do_spawn(pending["ticket_id"], pending["lane"], pending["model"], agent_type)


def _do_spawn(ticket_id: int, lane: str, model: str, agent_type: str) -> None:
    from tasklane.orchestration.runner import spawn_run
    spawn_run(ticket_id, lane, model, agent_type)


def _skip_lane(ticket_id: int, lane: Status, model: str) -> None:
    """Auto-advance through a lane with no agent."""
    from tasklane.core.enums import next_lane
    from tasklane.orchestration.runner import _audit

    nxt = next_lane(lane)
    if nxt is None:
        return

    execute_write(
        "UPDATE tickets SET status=?, updated_at=datetime('now') WHERE id=?",
        (nxt.value, ticket_id),
    )
    _audit(ticket_id, "system", "status_change", lane.value, nxt.value, "lane_skipped")
    # Recurse to check if next lane also needs skipping or agent spawn
    on_status_change(ticket_id, nxt, model)


def _lane_active_for_ticket(ticket, lane: str) -> bool:
    """Check if this lane is active for the ticket's persona."""
    from tasklane.api.personas import get_persona_by_name

    persona = get_persona_by_name(ticket["persona"])
    if persona is None:
        return True  # unknown persona — don't skip
    return lane in persona.active_lanes


def _log_queued(ticket_id: int, lane: str) -> None:
    execute_write(
        "INSERT INTO ticket_audit (ticket_id, actor, event, to_status, note) VALUES (?, ?, ?, ?, ?)",
        (ticket_id, "system", "queued", lane, "Waiting for a free agent slot"),
    )
