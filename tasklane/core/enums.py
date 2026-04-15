from __future__ import annotations
from enum import Enum


class Status(str, Enum):
    TODO = "todo"
    PLAN = "plan"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    IN_TESTING = "in_testing"
    DONE = "done"
    ERROR = "error"


# Ordered lane sequence (used for auto-advance)
LANE_ORDER = [
    Status.TODO,
    Status.PLAN,
    Status.IN_PROGRESS,
    Status.IN_REVIEW,
    Status.IN_TESTING,
    Status.DONE,
]

# Lanes that spawn agents
AGENT_LANES = {Status.PLAN, Status.IN_PROGRESS, Status.IN_REVIEW, Status.IN_TESTING}


def next_lane(status: Status) -> Status | None:
    """Return the next lane in order, or None if already at Done/Error."""
    try:
        idx = LANE_ORDER.index(status)
        if idx + 1 < len(LANE_ORDER):
            return LANE_ORDER[idx + 1]
    except ValueError:
        pass
    return None


class Urgency(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    CRASHED = "crashed"
    ITERATION_EXCEEDED = "iteration_exceeded"
    KILLED = "killed"
    BUDGET_EXCEEDED = "budget_exceeded"
    API_ERROR = "api_error"
    SUPERSEDED = "superseded"


class LogLevel(str, Enum):
    INFO = "info"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    ASSISTANT_TEXT = "assistant_text"
    WARN = "warn"
    ERROR = "error"


class Persona(str, Enum):
    SOFTWARE_ENGINEER = "software_engineer"
    SOFTWARE_ARCHITECT = "software_architect"
    DATA_ANALYST = "data_analyst"
    RESEARCH_ASSISTANT = "research_assistant"
    QA_ENGINEER = "qa_engineer"
    CODE_REVIEWER = "code_reviewer"
    CUSTOM = "custom"
