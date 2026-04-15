from __future__ import annotations
"""
GET /tools — returns the tool catalog so the frontend can render checkboxes.
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/tools", tags=["tools"])


class ToolInfo(BaseModel):
    name: str
    description: str
    group: str  # filesystem | execution | web
    dangerous: bool = False  # run_shell


TOOL_CATALOG: list[ToolInfo] = [
    ToolInfo(
        name="list_files",
        description="List all files inside a directory (scoped to workspace).",
        group="filesystem",
    ),
    ToolInfo(
        name="read_file",
        description="Read the full contents of a file (scoped to workspace).",
        group="filesystem",
    ),
    ToolInfo(
        name="write_file",
        description="Write or overwrite a file (scoped to workspace). Reviewers cannot write test files.",
        group="filesystem",
    ),
    ToolInfo(
        name="run_tests",
        description="Run pytest on a target path. Returns 'Error: pytest not available' if missing.",
        group="execution",
    ),
    ToolInfo(
        name="run_linter",
        description="Run flake8 on a target path. Returns 'Error: flake8 not available' if missing.",
        group="execution",
    ),
    ToolInfo(
        name="run_shell",
        description="Execute an arbitrary shell command. Use with caution — no sandbox in MVP.",
        group="execution",
        dangerous=True,
    ),
    ToolInfo(
        name="web_search",
        description="Search the web via DuckDuckGo (no API key required).",
        group="web",
    ),
    ToolInfo(
        name="web_fetch",
        description="Fetch and extract text content from a URL.",
        group="web",
    ),
]

_CATALOG_MAP = {t.name: t for t in TOOL_CATALOG}


@router.get("", response_model=list[ToolInfo])
def list_tools():
    return TOOL_CATALOG


def get_tool_names() -> list[str]:
    return [t.name for t in TOOL_CATALOG]
