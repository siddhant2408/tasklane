from __future__ import annotations
"""
Thread-per-run lifecycle manager.

Responsibilities:
- Spawn a threading.Thread for each run
- Track active runs in ACTIVE_RUNS
- On success: auto-advance ticket to next lane
- On any failure: move ticket to Error lane
- Cooperative cancel via threading.Event
- Persist full spec in agent_runs.spec_json for restart recovery
"""

import json
import threading
import traceback
from datetime import datetime, timezone

from tasklane.agents.base import AgentSpec, run_lane_agent
from tasklane.agents.registry import build_system_prompt, get_effective_tools
from tasklane.core.db import execute_write, get_db
from tasklane.core.enums import AGENT_LANES, RunStatus, Status, next_lane
from tasklane.core.logger import RunLogger
from tasklane.core.pubsub import publish_done
from tasklane.orchestration.lane_config import resolve_max_iterations

# run_id → threading.Event (cancel flag)
ACTIVE_RUNS: dict[int, threading.Event] = {}
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def spawn_run(ticket_id: int, lane: str, model: str, agent_type: str) -> int:
    """
    Create an agent_run row, build the spec, start the thread.
    Returns the new run_id.
    """
    with get_db() as conn:
        ticket = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        prior_run = conn.execute(
            "SELECT final_report FROM agent_runs "
            "WHERE ticket_id = ? AND status = 'completed' ORDER BY id DESC LIMIT 1",
            (ticket_id,),
        ).fetchone()

    prior_report = prior_run["final_report"] if prior_run else None

    # Build system prompt: description + lane suffix with prior report injected
    system_prompt = build_system_prompt(ticket["description"], lane, prior_report)

    # Effective tools: ticket allowlist ∩ lane restrictions
    ticket_tools = json.loads(ticket["tools_json"] or "[]")
    effective_tools = get_effective_tools(lane, ticket_tools)

    # Max iterations
    max_iters = resolve_max_iterations(ticket["max_iterations"], ticket["urgency"])

    first_user_msg = (
        "Begin work on this ticket. "
        "When you are done, produce your final report in the format described in the system prompt."
    )

    spec_data = {
        "system_prompt": system_prompt,
        "tools": effective_tools,
        "workspace_root": ticket["workspace_path"],
        "first_user_message": first_user_msg,
        "model": model,
        "max_iterations": max_iters,
        "lane": lane,
        "agent_type": agent_type,
    }

    # Insert agent_run row
    execute_write(
        """INSERT INTO agent_runs
             (ticket_id, lane, agent_type, persona, model, max_iterations, status, spec_json)
           VALUES (?, ?, ?, ?, ?, ?, 'running', ?)""",
        (ticket_id, lane, agent_type, ticket["persona"], model, max_iters, json.dumps(spec_data)),
    )

    with get_db() as conn:
        run_id = conn.execute(
            "SELECT id FROM agent_runs WHERE ticket_id = ? ORDER BY id DESC LIMIT 1",
            (ticket_id,),
        ).fetchone()["id"]

    # Lock the ticket
    execute_write(
        "UPDATE tickets SET locked = 1, updated_at = datetime('now') WHERE id = ?",
        (ticket_id,),
    )

    cancel_flag = threading.Event()
    with _lock:
        ACTIVE_RUNS[run_id] = cancel_flag

    spec = AgentSpec(
        run_id=run_id,
        ticket_id=ticket_id,
        lane=lane,
        system_prompt=system_prompt,
        first_user_message=first_user_msg,
        tools=effective_tools,
        workspace_root=ticket["workspace_path"],
        model=model,
        max_iterations=max_iters,
        cancel_flag=cancel_flag,
    )

    t = threading.Thread(
        target=_run_thread,
        args=(spec,),
        name=f"run-{run_id}",
        daemon=True,
    )
    t.start()

    return run_id


def kill_run(run_id: int) -> None:
    """Signal cooperative cancel. The thread will stop within one iteration."""
    with _lock:
        flag = ACTIVE_RUNS.get(run_id)
    if flag:
        flag.set()


# ---------------------------------------------------------------------------
# Thread target
# ---------------------------------------------------------------------------

def _run_thread(spec: AgentSpec) -> None:
    run_id = spec.run_id
    ticket_id = spec.ticket_id
    logger = RunLogger(run_id)

    try:
        final_report = run_lane_agent(spec)
        _on_success(spec, final_report, logger)

    except RuntimeError as e:
        error_msg = str(e)
        if error_msg == "iteration_exceeded":
            _on_failure(spec, RunStatus.ITERATION_EXCEEDED, "Hit MAX_ITERATIONS limit.", logger)
        elif error_msg == "budget_exceeded":
            _on_failure(spec, RunStatus.BUDGET_EXCEEDED, "Token budget exceeded.", logger)
        elif error_msg.startswith("stopped_"):
            _on_failure(spec, RunStatus.CRASHED, error_msg, logger)
        else:
            _on_failure(spec, RunStatus.CRASHED, error_msg, logger)

    except Exception:
        tb = traceback.format_exc()
        logger.error(f"Unhandled exception:\n{tb}")
        _on_failure(spec, RunStatus.CRASHED, tb[:2000], logger)

    finally:
        with _lock:
            ACTIVE_RUNS.pop(run_id, None)
        publish_done(run_id)
        from tasklane.orchestration.scheduler import on_run_end
        on_run_end(ticket_id)


def _on_success(spec: AgentSpec, final_report: str, logger: RunLogger) -> None:
    now = datetime.now(timezone.utc).isoformat()

    # Determine iteration count from logs
    with get_db() as conn:
        iters = conn.execute(
            "SELECT COUNT(*) as c FROM logs WHERE run_id = ? AND level = 'info' AND message LIKE '--- Iteration%'",
            (spec.run_id,),
        ).fetchone()["c"]

    execute_write(
        "UPDATE agent_runs SET status='completed', ended_at=?, final_report=?, iterations=? WHERE id=?",
        (now, final_report, iters, spec.run_id),
    )

    # Check if cancelled (final_report is the cancelled sentinel)
    if spec.cancel_flag.is_set() or final_report == "(run cancelled)":
        execute_write(
            "UPDATE agent_runs SET status='killed' WHERE id=?",
            (spec.run_id,),
        )
        _move_to_error(spec.ticket_id, "Run was cancelled.", logger)
        return

    logger.info(f"Run completed successfully.")
    _audit(spec.ticket_id, "auto", "status_change", spec.lane, "next")

    # Auto-advance to next lane
    _auto_advance(spec.ticket_id, spec.lane, logger)


def _on_failure(spec: AgentSpec, status: RunStatus, error: str, logger: RunLogger) -> None:
    now = datetime.now(timezone.utc).isoformat()
    execute_write(
        "UPDATE agent_runs SET status=?, ended_at=?, error=? WHERE id=?",
        (status.value, now, error, spec.run_id),
    )
    logger.error(f"Run failed: {status.value} — {error[:200]}")
    _move_to_error(spec.ticket_id, f"{status.value}: {error[:200]}", logger)


def _move_to_error(ticket_id: int, reason: str, logger: RunLogger) -> None:
    execute_write(
        "UPDATE tickets SET status='error', locked=0, updated_at=datetime('now') WHERE id=?",
        (ticket_id,),
    )
    _audit(ticket_id, "system", "status_change", None, "error", reason)
    logger.warn(f"Ticket {ticket_id} → error: {reason[:100]}")


def _auto_advance(ticket_id: int, current_lane: str, logger: RunLogger) -> None:
    """Move ticket to the next lane and trigger the next agent if applicable."""
    from tasklane.orchestration.scheduler import on_status_change

    current_status = Status(current_lane)
    nxt = next_lane(current_status)

    if nxt is None:
        # Already at the end
        execute_write(
            "UPDATE tickets SET locked=0, updated_at=datetime('now') WHERE id=?",
            (ticket_id,),
        )
        return

    execute_write(
        "UPDATE tickets SET status=?, locked=0, updated_at=datetime('now') WHERE id=?",
        (nxt.value, ticket_id),
    )
    _audit(ticket_id, "auto", "status_change", current_lane, nxt.value)
    logger.info(f"Ticket {ticket_id} auto-advanced: {current_lane} → {nxt.value}")

    # Trigger next agent spawn (uses default model from ticket's models_json or Sonnet)
    with get_db() as conn:
        ticket = conn.execute("SELECT models_json FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    models = json.loads(ticket["models_json"] or "{}") if ticket else {}
    model = models.get(nxt.value, "claude-sonnet-4-5")

    on_status_change(ticket_id, nxt, model)


def _audit(ticket_id: int, actor: str, event: str,
           from_status: str | None, to_status: str | None, note: str | None = None) -> None:
    execute_write(
        "INSERT INTO ticket_audit (ticket_id, actor, event, from_status, to_status, note) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ticket_id, actor, event, from_status, to_status, note),
    )
