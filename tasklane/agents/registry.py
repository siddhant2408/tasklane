from __future__ import annotations
"""
AGENT_REGISTRY maps agent_type strings to their lane-specific tool allowlists
and system prompt modifiers. The base loop (agents/base.py) handles all of
them — no per-agent loop code needed.
"""

# Lane-specific tool restrictions — even if a ticket allowlists a tool,
# these per-lane overrides strip unsafe tools.
LANE_TOOL_RESTRICTIONS: dict[str, set[str]] = {
    "plan":        {"list_files", "read_file", "web_search", "web_fetch"},  # read-only in planning
    "in_progress": set(),   # no additional restrictions — ticket allowlist applies
    "in_review":   {"list_files", "read_file", "write_file", "run_linter", "run_tests"},
    "in_testing":  {"list_files", "read_file", "run_tests"},   # testers don't write source
}


def get_effective_tools(lane: str, ticket_tools: list[str]) -> list[str]:
    """
    Intersect the ticket's tool allowlist with the lane's permitted set.
    If the lane has no restriction (empty set), all ticket tools are allowed.
    """
    restrictions = LANE_TOOL_RESTRICTIONS.get(lane, set())
    if not restrictions:
        return ticket_tools
    return [t for t in ticket_tools if t in restrictions]


# Lane suffix appended to the system prompt so the agent knows its context
LANE_SYSTEM_SUFFIX: dict[str, str] = {
    "plan": (
        "\n\n---\n"
        "**Current phase: PLAN**\n"
        "Do NOT implement anything yet. Your only job is to produce a clear, "
        "step-by-step plan describing what needs to be done, which files are involved, "
        "and what the approach is. End your response with the plan in a '### Plan' section."
    ),
    "in_progress": (
        "\n\n---\n"
        "**Current phase: IN PROGRESS**\n"
        "Implement the task described above. "
        "{prior_report}"
        "When done, produce a final report summarising what you changed."
    ),
    "in_review": (
        "\n\n---\n"
        "**Current phase: IN REVIEW**\n"
        "Review the work done in the previous phase. "
        "{prior_report}"
        "Check for correctness, style issues, and test coverage. "
        "Apply minor fixes if needed. Produce a review verdict."
    ),
    "in_testing": (
        "\n\n---\n"
        "**Current phase: IN TESTING**\n"
        "Verify that the implementation is correct. "
        "{prior_report}"
        "Run the test suite and report results. Do not modify source files."
    ),
}


def build_system_prompt(base_description: str, lane: str, prior_report: str | None) -> str:
    """Combine the ticket description with the lane-specific suffix."""
    suffix_template = LANE_SYSTEM_SUFFIX.get(lane, "")
    if prior_report:
        prior_section = (
            f"The previous phase produced this report:\n\n"
            f"```\n{prior_report[:3000]}\n```\n\n"
        )
    else:
        prior_section = ""

    suffix = suffix_template.format(prior_report=prior_section)
    return base_description + suffix
