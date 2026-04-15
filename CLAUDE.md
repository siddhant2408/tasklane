# tasklane — Project Context

## What this is

A kanban board that auto-spawns AI agents when tickets move between lanes.
Moving a ticket to an agent lane triggers `run_lane_agent(spec)` in a background
thread. The agent runs a standard `while True` agentic loop (same pattern as
`my-agents/`) and auto-advances the ticket to the next lane when done.

## Running the project

```bash
# Backend
pip install -r requirements.txt
ANTHROPIC_API_KEY=sk-... python server.py

# Frontend (dev)
cd frontend && npm install && npm run dev
```

Server runs on http://localhost:8000. Frontend dev server on http://localhost:5173
and proxies API calls to the backend.

## Lane flow

Todo → Plan → In Progress → In Review → In Testing → Done (+ Error sink)

Only Plan, In Progress, In Review, In Testing have agent spawns.
Todo and Done are human-only. Error is a sink for any failed run.

## Key design rules (do not change without good reason)

1. **description = system prompt.** The ticket's description field is sent verbatim
   as the system prompt to the agent. Personas just pre-fill the description field.

2. **Agentic loop mirrors my-agents exactly.** `agents/base.py:run_lane_agent()`
   follows the same 3 rules: append full response.content, batch all tool results
   in one user message, match tool_use_id exactly.

3. **Tools return strings, never raise.** All tool implementations in
   `agents/tools.py` catch exceptions and return `"Error: ..."` strings.

4. **No sandboxing in MVP.** Tools execute in-process against the user's real
   workspace path. The only guardrail is the workspace path scope check.

5. **One active run per ticket.** `locked=1` on the ticket while a run is in
   flight — disables drag and edit. Kill button available to cancel.

6. **Sonnet default everywhere.** Model is Sonnet unless user overrides at drag
   time via the model picker modal.

## Directory layout

```
tasklane/
├── server.py                   # FastAPI entrypoint
├── requirements.txt
├── tasklane/
│   ├── core/
│   │   ├── db.py               # SQLite + WAL + schema
│   │   ├── enums.py            # Status, Urgency, RunStatus, LogLevel
│   │   ├── models.py           # Pydantic models
│   │   ├── logger.py           # RunLogger: file + DB + pubsub tee
│   │   └── pubsub.py           # in-process pub/sub for SSE fan-out
│   ├── api/
│   │   ├── tickets.py          # /tickets routes
│   │   ├── runs.py             # /runs routes + SSE
│   │   ├── tools.py            # /tools catalog
│   │   └── personas.py         # /personas catalog
│   ├── orchestration/
│   │   ├── runner.py           # thread per run, lifecycle, auto-advance
│   │   ├── scheduler.py        # lane-change → dispatch, concurrency cap
│   │   └── lane_config.py      # lane → default agent_type
│   └── agents/
│       ├── base.py             # run_lane_agent(spec) — the shared loop
│       ├── tools.py            # catalog + workspace-scoped impls
│       ├── personas.py         # persona catalog (templates)
│       ├── registry.py         # AGENT_REGISTRY
│       ├── planner.py
│       ├── coder.py
│       ├── reviewer.py
│       ├── tester.py
│       ├── researcher.py
│       ├── analyst.py
│       └── architect.py
├── frontend/                   # React + Vite + Tailwind
├── runs/                       # per-run .log files (gitignored)
└── tasklane.db                 # SQLite file (gitignored)
```
