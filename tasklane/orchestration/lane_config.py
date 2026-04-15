from __future__ import annotations
"""
Maps lanes to their default agent types and urgency → model/iterations tables.
"""

from tasklane.core.enums import Status, Urgency

# Default agent type per lane
LANE_DEFAULT_AGENT: dict[str, str] = {
    Status.PLAN.value:        "planner",
    Status.IN_PROGRESS.value: "coder",
    Status.IN_REVIEW.value:   "reviewer",
    Status.IN_TESTING.value:  "tester",
}

# Urgency → (suggested model, default max_iterations)
URGENCY_CONFIG: dict[str, tuple[str, int]] = {
    Urgency.LOW.value:      ("claude-haiku-4-5-20251001", 10),
    Urgency.NORMAL.value:   ("claude-sonnet-4-5", 20),
    Urgency.HIGH.value:     ("claude-opus-4-6", 20),
    Urgency.CRITICAL.value: ("claude-opus-4-6", 30),
}

DEFAULT_MODEL = "claude-sonnet-4-5"
DEFAULT_MAX_ITERATIONS = 20


def resolve_max_iterations(ticket_max_iterations: int | None, urgency: str) -> int:
    if ticket_max_iterations is not None:
        return ticket_max_iterations
    _, iters = URGENCY_CONFIG.get(urgency, (DEFAULT_MODEL, DEFAULT_MAX_ITERATIONS))
    return iters


def get_agent_type(lane: str, ticket_agents_json: dict | None) -> str | None:
    """
    Returns agent type for a lane, or None if the lane should be skipped.
    ticket_agents_json can override or null-out a lane.
    """
    if ticket_agents_json is not None:
        override = ticket_agents_json.get(lane)
        if lane in ticket_agents_json:
            return override  # None means skip this lane
    return LANE_DEFAULT_AGENT.get(lane)
