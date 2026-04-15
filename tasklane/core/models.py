from __future__ import annotations
"""
Pydantic models for request/response validation and internal DTOs.
"""

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator, model_validator

from tasklane.core.enums import LogLevel, Persona, RunStatus, Status, Urgency


# ---------------------------------------------------------------------------
# Ticket
# ---------------------------------------------------------------------------

class TicketCreate(BaseModel):
    title: str
    description: str
    persona: Persona = Persona.SOFTWARE_ENGINEER
    urgency: Urgency = Urgency.NORMAL
    tools_json: list[str] = []
    agents_json: dict[str, str | None] | None = None
    models_json: dict[str, str] = {}
    workspace_path: str
    max_iterations: int | None = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be empty")
        return v.strip()

    @field_validator("description")
    @classmethod
    def description_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("description must not be empty")
        return v.strip()


class TicketUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    urgency: Urgency | None = None
    tools_json: list[str] | None = None
    agents_json: dict[str, str | None] | None = None
    models_json: dict[str, str] | None = None
    workspace_path: str | None = None
    max_iterations: int | None = None


class TicketStatusChange(BaseModel):
    to: Status
    model: str = "claude-sonnet-4-5"


class TicketOut(BaseModel):
    id: int
    title: str
    description: str
    persona: str
    status: str
    urgency: str
    tools_json: list[str]
    agents_json: dict[str, str | None] | None
    models_json: dict[str, str]
    workspace_path: str
    max_iterations: int | None
    locked: bool
    created_at: str
    updated_at: str
    active_run_id: int | None = None

    @classmethod
    def from_row(cls, row: Any, active_run_id: int | None = None) -> "TicketOut":
        return cls(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            persona=row["persona"],
            status=row["status"],
            urgency=row["urgency"],
            tools_json=json.loads(row["tools_json"] or "[]"),
            agents_json=json.loads(row["agents_json"]) if row["agents_json"] else None,
            models_json=json.loads(row["models_json"] or "{}"),
            workspace_path=row["workspace_path"],
            max_iterations=row["max_iterations"],
            locked=bool(row["locked"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            active_run_id=active_run_id,
        )


# ---------------------------------------------------------------------------
# AgentRun
# ---------------------------------------------------------------------------

class RunOut(BaseModel):
    id: int
    ticket_id: int
    lane: str
    agent_type: str
    persona: str
    model: str
    max_iterations: int
    status: str
    started_at: str
    ended_at: str | None
    final_report: str | None
    error: str | None
    iterations: int
    input_tokens: int
    output_tokens: int

    @classmethod
    def from_row(cls, row: Any) -> "RunOut":
        return cls(
            id=row["id"],
            ticket_id=row["ticket_id"],
            lane=row["lane"],
            agent_type=row["agent_type"],
            persona=row["persona"],
            model=row["model"],
            max_iterations=row["max_iterations"],
            status=row["status"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            final_report=row["final_report"],
            error=row["error"],
            iterations=row["iterations"],
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
        )


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------

class LogEntryOut(BaseModel):
    id: int
    run_id: int
    seq: int
    ts: str
    level: str
    message: str

    @classmethod
    def from_row(cls, row: Any) -> "LogEntryOut":
        return cls(
            id=row["id"],
            run_id=row["run_id"],
            seq=row["seq"],
            ts=row["ts"],
            level=row["level"],
            message=row["message"],
        )


# ---------------------------------------------------------------------------
# Board (full state for initial load)
# ---------------------------------------------------------------------------

class BoardOut(BaseModel):
    lanes: dict[str, list[TicketOut]]
