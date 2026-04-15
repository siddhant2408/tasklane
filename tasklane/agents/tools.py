from __future__ import annotations
"""
Tool implementations — all workspace-scoped, all return strings (never raise).

Rule: if a tool fails for any reason, return "Error: <message>".
This lets the agent read the error and adapt rather than crashing the loop.
"""

import html.parser
import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
# Tool definitions (sent to Claude on every API call)
# ---------------------------------------------------------------------------

def build_tool_definitions(allowed_tools: list[str]) -> list[dict]:
    """Return only the tool definitions for the given allowed tool names."""
    return [t for t in _ALL_TOOL_DEFINITIONS if t["name"] in allowed_tools]


_ALL_TOOL_DEFINITIONS = [
    {
        "name": "list_files",
        "description": (
            "List all files inside a directory, scoped to the ticket workspace. "
            "Use this first to discover what files exist before reading or modifying them."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Relative path inside the workspace, e.g. 'src' or '.'. Use '.' for workspace root.",
                }
            },
            "required": ["directory"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read the full contents of a file, scoped to the ticket workspace. "
            "Use this to inspect source code, tests, or documentation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path inside the workspace, e.g. 'src/math_utils.py'.",
                }
            },
            "required": ["filepath"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write or overwrite a file, scoped to the ticket workspace. "
            "Replaces the entire file content. "
            "Do NOT use this to write test files — test files are off-limits."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Relative path inside the workspace.",
                },
                "content": {
                    "type": "string",
                    "description": "Full new content of the file.",
                },
            },
            "required": ["filepath", "content"],
        },
    },
    {
        "name": "run_tests",
        "description": (
            "Run pytest on a target path inside the workspace. "
            "Returns the full pytest output. "
            "Use this after making changes to verify nothing regressed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Relative path to run — a file or directory, e.g. 'tests/' or 'tests/test_math.py'.",
                }
            },
            "required": ["target"],
        },
    },
    {
        "name": "run_linter",
        "description": (
            "Run flake8 on a target path inside the workspace. "
            "Returns lint warnings and errors. "
            "Use this to check code style before finalising changes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Relative path to lint — a file or directory.",
                }
            },
            "required": ["target"],
        },
    },
    {
        "name": "run_shell",
        "description": (
            "Execute an arbitrary shell command inside the workspace directory. "
            "Use sparingly. No sandbox — runs against the real filesystem."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cmd": {
                    "type": "string",
                    "description": "Shell command to run, e.g. 'python script.py' or 'ls -la'.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 60).",
                },
            },
            "required": ["cmd"],
        },
    },
    {
        "name": "web_search",
        "description": (
            "Search the web using DuckDuckGo. Returns a list of result titles, URLs, and snippets. "
            "Use this for research tasks or when you need external information."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query string.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 8).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_fetch",
        "description": (
            "Fetch a URL and return its text content. "
            "Use this after web_search to read the full content of a promising result."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch.",
                },
                "focus": {
                    "type": "string",
                    "description": "Optional keyword to focus the extracted text around.",
                },
            },
            "required": ["url"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

def execute_tool(name: str, tool_input: dict, workspace_root: str, allowed_tools: list[str]) -> str:
    """Route a tool call to its implementation. Always returns a string."""
    if name not in allowed_tools:
        return f"Error: tool '{name}' is not in this ticket's allowlist."

    if name == "list_files":
        return list_files(tool_input["directory"], workspace_root)
    elif name == "read_file":
        return read_file(tool_input["filepath"], workspace_root)
    elif name == "write_file":
        return write_file(tool_input["filepath"], tool_input["content"], workspace_root)
    elif name == "run_tests":
        return run_tests(tool_input["target"], workspace_root)
    elif name == "run_linter":
        return run_linter(tool_input["target"], workspace_root)
    elif name == "run_shell":
        return run_shell(tool_input["cmd"], workspace_root, tool_input.get("timeout", 60))
    elif name == "web_search":
        return web_search(tool_input["query"], tool_input.get("max_results", 8))
    elif name == "web_fetch":
        return web_fetch(tool_input["url"], tool_input.get("focus"))
    else:
        return f"Error: unknown tool '{name}'."


# ---------------------------------------------------------------------------
# Workspace helpers
# ---------------------------------------------------------------------------

def _resolve(relative: str, workspace_root: str) -> str | None:
    """Resolve a relative path inside workspace_root. Returns None if escaping."""
    abs_path = os.path.realpath(os.path.join(workspace_root, relative))
    ws_real = os.path.realpath(workspace_root)
    if not abs_path.startswith(ws_real + os.sep) and abs_path != ws_real:
        return None
    return abs_path


def _is_test_file(filepath: str) -> bool:
    base = os.path.basename(filepath)
    return base.startswith("test_") or base.endswith("_test.py")


# ---------------------------------------------------------------------------
# Filesystem tools
# ---------------------------------------------------------------------------

def list_files(directory: str, workspace_root: str) -> str:
    abs_dir = _resolve(directory, workspace_root)
    if abs_dir is None:
        return f"Error: '{directory}' escapes the workspace."
    if not os.path.isdir(abs_dir):
        return f"Error: '{directory}' is not a directory."
    try:
        results = []
        for root, dirs, files in os.walk(abs_dir):
            # Skip hidden dirs and common noise
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "node_modules", ".git")]
            for f in sorted(files):
                full = os.path.join(root, f)
                rel = os.path.relpath(full, workspace_root)
                results.append(rel)
        if not results:
            return f"No files found in '{directory}'."
        return "\n".join(results)
    except Exception as e:
        return f"Error: {e}"


def read_file(filepath: str, workspace_root: str) -> str:
    abs_path = _resolve(filepath, workspace_root)
    if abs_path is None:
        return f"Error: '{filepath}' escapes the workspace."
    if not os.path.isfile(abs_path):
        return f"Error: file '{filepath}' not found."
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as e:
        return f"Error: {e}"


def write_file(filepath: str, content: str, workspace_root: str) -> str:
    abs_path = _resolve(filepath, workspace_root)
    if abs_path is None:
        return f"Error: '{filepath}' escapes the workspace."
    if _is_test_file(filepath):
        return f"Error: writing test files is not allowed. '{filepath}' looks like a test file."
    try:
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Written {len(content)} chars to '{filepath}'."
    except Exception as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Execution tools
# ---------------------------------------------------------------------------

def run_tests(target: str, workspace_root: str) -> str:
    abs_target = _resolve(target, workspace_root)
    if abs_target is None:
        return f"Error: '{target}' escapes the workspace."
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", abs_target, "-v", "--tb=short"],
            capture_output=True, text=True, cwd=workspace_root, timeout=120,
        )
        output = result.stdout + result.stderr
        return output[:8000] if output else "(no output)"
    except FileNotFoundError:
        return "Error: pytest not available. Install with: pip install pytest"
    except subprocess.TimeoutExpired:
        return "Error: test run timed out after 120 seconds."
    except Exception as e:
        return f"Error: {e}"


def run_linter(target: str, workspace_root: str) -> str:
    abs_target = _resolve(target, workspace_root)
    if abs_target is None:
        return f"Error: '{target}' escapes the workspace."
    try:
        result = subprocess.run(
            ["python", "-m", "flake8", abs_target, "--max-line-length=120"],
            capture_output=True, text=True, cwd=workspace_root, timeout=30,
        )
        output = result.stdout + result.stderr
        if not output.strip():
            return "No lint issues found."
        return output[:4000]
    except FileNotFoundError:
        return "Error: flake8 not available. Install with: pip install flake8"
    except subprocess.TimeoutExpired:
        return "Error: linter timed out."
    except Exception as e:
        return f"Error: {e}"


def run_shell(cmd: str, workspace_root: str, timeout: int = 60) -> str:
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            cwd=workspace_root, timeout=timeout,
        )
        output = result.stdout + result.stderr
        return (output[:8000] if output else "(no output)") + (f"\n[exit code: {result.returncode}]")
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout} seconds."
    except Exception as e:
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Web tools (lifted from my-agents/web_search_agent)
# ---------------------------------------------------------------------------

_USER_AGENT = "Mozilla/5.0 (compatible; tasklane-agent/1.0)"
_HTTP_TIMEOUT = 15
_MAX_FETCH_CHARS = 8_000
_MAX_SEARCH_RESULTS = 8
_DDG_URL = os.environ.get("WEB_SEARCH_BASE_URL", "https://html.duckduckgo.com/html/")


class _TextExtractor(html.parser.HTMLParser):
    _SKIP_TAGS = {"script", "style", "nav", "header", "footer", "noscript", "svg"}
    _BLOCK_TAGS = {"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li", "section", "main", "article"}

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        if self._skip_depth:
            return
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            self._parts.append(data)

    def get_text(self) -> str:
        import re
        text = "".join(self._parts)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _http_get(url: str) -> tuple[int, str, str]:
    if url.startswith("http://") and not url.startswith("http://localhost"):
        url = "https://" + url[7:]
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            raw = resp.read(2 * 1024 * 1024)
            charset = resp.headers.get_content_charset("utf-8") or "utf-8"
            return resp.status, resp.headers.get_content_type() or "", raw.decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, "", f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return 0, "", f"URL error: {e.reason}"
    except Exception as e:
        return 0, "", f"Error: {e}"


def _decode_ddg_url(href: str) -> str:
    if href.startswith("/l/?"):
        qs = urllib.parse.parse_qs(href[4:])
        uddg = qs.get("uddg", [None])[0]
        if uddg:
            return urllib.parse.unquote(uddg)
    return href


def web_search(query: str, max_results: int = _MAX_SEARCH_RESULTS) -> str:
    params = urllib.parse.urlencode({"q": query})
    url = f"{_DDG_URL}?{params}"
    status, _, body = _http_get(url)
    if status not in (200, 0) and status >= 400:
        return f"Error: search request failed with status {status}."

    # Parse result links from DuckDuckGo HTML
    import re
    results = []
    # Match result anchors
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', body, re.DOTALL):
        href = _decode_ddg_url(m.group(1))
        title_raw = m.group(2)
        title = re.sub(r"<[^>]+>", "", title_raw).strip()
        if href.startswith("http") and title:
            results.append({"title": title, "url": href})
        if len(results) >= max_results:
            break

    if not results:
        return f'No results found for "{query}". Try rephrasing.'

    lines = [f'Search results for "{query}":\n']
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}\n   {r['url']}")
    return "\n".join(lines)


def web_fetch(url: str, focus: str | None = None) -> str:
    status, content_type, body = _http_get(url)
    if status >= 400:
        return f"Error: {body}"

    if "html" in content_type:
        extractor = _TextExtractor()
        extractor.feed(body)
        text = extractor.get_text()
    else:
        text = body

    if focus and len(text) > _MAX_FETCH_CHARS:
        idx = text.lower().find(focus.lower())
        if idx != -1:
            start = max(0, idx - 200)
            text = f"[…content trimmed, showing section near '{focus}'…]\n\n" + text[start:start + _MAX_FETCH_CHARS]
        else:
            text = text[:_MAX_FETCH_CHARS] + f"\n\n[…truncated at {_MAX_FETCH_CHARS} chars…]"
    else:
        text = text[:_MAX_FETCH_CHARS]
        if len(body) > _MAX_FETCH_CHARS:
            text += f"\n\n[…truncated at {_MAX_FETCH_CHARS} chars…]"

    return text or "(page returned no readable text)"
