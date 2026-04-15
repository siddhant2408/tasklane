# Tasklane — Kanban-Driven Agent Orchestration (SOP v2)

## Context

The user is building a new project at `/Users/siddhant/mystuff/ai/agentic-ai/tasklane` (currently empty). Vision: a JIRA/Trello-style kanban board where **moving a ticket between lanes auto-spawns an AI agent** that does the work described on the ticket. Each ticket carries its own prompt, persona, tool allowlist, urgency, and workspace path. When the agent finishes, the ticket auto-advances to the next lane (or waits for human approval).

Why now: the user has `my-agents/` with hand-built agent patterns (testing_agent, review_agent, web_search_agent, pr_pipeline orchestrator). Tasklane is a persistent, UI-driven orchestration layer over that same agent pattern.

**Guiding principle:** Tasklane is a thin orchestration shell over the my-agents pattern. A ticket is a persisted, lane-gated agent invocation. If a design choice would force a change to the my-agents core pattern, reject it.

---

## User-approved decisions

**From v1 review:**
| Decision | Resolution |
|---|---|
| Inter-lane context passing | **Auto-inject** prior agent's `final_report` into next agent's first user message |
| Error retry | Re-run **only the failed lane** |
| Log/event streaming | **SSE** |
| Server restart mid-run | Mark `running` rows as `crashed`; persist full spec for manual re-run |
| Auth | Single-user localhost, no auth |
| Urgency default | Normal |
| Blocked-by behavior | Just become draggable (never auto-start) |
| Log retention | Never prune automatically; user chooses what to delete |
| Edit during active run | Disallow |
| Workspace | User-defined absolute path in the ticket |
| Model choice | User picks model per-phase before advancing the ticket |
| Persona scope | Not just coding — research, architecture, analysis personas |
| Plan lane | Yes — add before In Progress |
| Parallel tickets | Yes |
| Frontend framework | React + Vite + Tailwind |

**From v2 review (final):**
| Decision | Resolution |
|---|---|
| Description → system prompt | **Ticket description IS the system prompt.** Persona selection pre-fills it; custom = user writes from scratch |
| Sandbox for tools | **Dropped from MVP** — stretch only |
| Plan approval | **Manual drag** from Plan → In Progress |
| Workspace path validation | **Reject non-existent paths** at ticket creation |
| Per-phase model default | **Sonnet everywhere** unless user manually overrides |
| SSE reconnect | `?after_seq=N` query param replays from N |
| Dark mode | System preference |
| Drag during active run | **Disabled** (only Kill button available while running) |
| MAX_ITERATIONS override | Behind **Advanced** section in ticket form |
| Sandbox change-promotion | Dropped (sandbox itself is dropped) |

---

## 1. Feature list

### MVP
1. **Ticket CRUD** — title, description (the prompt), urgency, persona, tools allowlist, workspace absolute path, per-lane model override.
2. **Six-lane board** — Todo → Plan → In Progress → In Review → In Testing → Done + Error sink.
3. **Drag-and-drop** between lanes (with pre-drag model selector modal; see §7).
4. **Auto-spawn on lane change** — for "agent lanes" only.
5. **Parallel runs** — multiple tickets may run concurrently; global cap configurable.
6. **Background thread per run**; logs stream via SSE + per-run file + DB.
7. **Auto-advance on success**; **Error lane on failure**.
8. **Per-ticket tool allowlist** from catalog, with optional sandbox mode.
9. **Live log tail** on ticket card.
10. **Manual override** — drag past in-flight agent (409 unless `?force=true` which kills the run).
11. **Kill button** on active runs.
12. **Run history** per ticket.
13. **Ticket audit log** (human / auto / system).
14. **Persona catalog** — Software Engineer, Software Architect, Data Analyst, Research Assistant, QA Engineer, Code Reviewer, plus Custom.
15. **Plan approval gate** — Plan-lane agent produces a plan; ticket waits in Plan until user drags to In Progress.
16. **Rerun from Error lane** — one-click re-spawn with same spec.

### Stretch
17. Pause/resume mid-run.
18. Ticket chaining (`blocked_by`).
19. Comments thread (human-only).
20. Attachments injected into first user message.
21. Multi-user + auth.
22. Inline custom tools.
23. Per-run git worktree isolation.
24. Custom persona creation via UI.

---

## 2. Agent lifecycle

State machine for one run:
```
[lane change] ─► SPAWN ─► RUNNING ─► {SUCCESS | FAILURE | KILLED | TIMEOUT}
                             │
                    logs appended continuously
```

**Spawn trigger.** `PATCH /tickets/{id}/status` with body `{to: "in_progress", model: "claude-sonnet-4-5"}`. Handler looks up `agent_for_lane(ticket, new_lane)`; if configured + not skipped, enqueues a run.

**Agent construction (spec):**
- `system_prompt` — **the ticket's `description` field verbatim**, with a short lane-suffix appended (e.g. "\n\n---\nYou are currently in the **In Review** lane. Your prior-phase colleague produced this report:\n{final_report}"). Lane suffix is empty for Plan lane (the first agent).
- `tools` — intersection of ticket allowlist ∩ lane's permitted set.
- `workspace_root` — absolute path from ticket (user-defined). Scope guard enforced at tool level.
- `first_user_message` — fixed short framing: `"Begin work on this ticket. When done, produce your final report in the format described above."` The meaningful task content lives in the system prompt (the description).
- `max_iterations` — from urgency table (or ticket advanced override).
- `model` — user-selected at drag time; **default Sonnet** unless overridden.

**Execution.** One `threading.Thread` per active run calling `run_lane_agent(ticket_id, lane, spec) -> str`. Mirrors `my-agents/testing_agent/agent.py:run_agent` exactly — same while-True, 3 message-protocol rules, stop-reason handling.

**Log streaming.** Each run has a `RunLogger` that tees to:
1. `tasklane/runs/{run_id}.log` (file, survives restart)
2. `logs` table (queryable)
3. In-process pubsub for SSE fan-out

**Success.** Final string → `agent_runs.final_report`. Run marked `completed`. Post-hook advances ticket status. The **final_report is injected into the next lane's first user message automatically**. Chaining emerges naturally.

**Failure modes:**
| Condition | Run status | Lane action |
|---|---|---|
| Tool raised | `crashed` | → Error |
| MAX_ITERATIONS | `iteration_exceeded` | → Error |
| Unexpected stop_reason | `stopped_<reason>` | → Error |
| API error after 3 backoff retries | `api_error` | → Error |
| Budget overrun | `budget_exceeded` | → Error |

**Cancel/kill.** Cooperative flag checked at top of loop + between tool-result assembly. Hard thread kill unsafe in CPython.

**Server restart.** On boot, any `running` rows → `crashed` with note `server_restart`. **Full spec persisted** (system_prompt, tools, workspace, description, model) so user can click "Re-run" to spawn fresh with identical config.

**Rerun from Error.** Re-runs **only the failed lane**. Previous workspace state is preserved. Stored spec re-used; optionally user edits description/model first via unlock-for-edit.

---

## 3. Data model / schema (SQLite)

```sql
tickets
  id              INTEGER PK
  title           TEXT NOT NULL
  description     TEXT NOT NULL          -- the FULL system prompt sent to the agent
  persona         TEXT NOT NULL          -- software_engineer|architect|data_analyst|researcher|qa_engineer|code_reviewer|custom (just the template source; does not change runtime behavior)
  status          TEXT NOT NULL          -- todo|plan|in_progress|in_review|in_testing|done|error
  urgency         TEXT NOT NULL          -- low|normal|high|critical
  tools_json      TEXT NOT NULL          -- JSON array
  agents_json     TEXT                   -- JSON {lane: agent_type|null}; null = skip lane
  models_json     TEXT                   -- JSON {lane: model_id}; user overrides (Sonnet default)
  workspace_path  TEXT NOT NULL          -- absolute path on user's machine (validated at creation)
  max_iterations  INTEGER                -- NULL = derive from urgency; otherwise advanced override
  blocked_by      INTEGER REFERENCES tickets(id)   -- stretch
  locked          INTEGER NOT NULL DEFAULT 0   -- 1 while run in flight, blocks edits AND drag
  created_at      TEXT NOT NULL
  updated_at      TEXT NOT NULL

agent_runs
  id              INTEGER PK
  ticket_id       INTEGER NOT NULL REFERENCES tickets(id)
  lane            TEXT NOT NULL
  agent_type      TEXT NOT NULL
  persona         TEXT NOT NULL
  model           TEXT NOT NULL
  max_iterations  INTEGER NOT NULL
  status          TEXT NOT NULL          -- running|completed|crashed|iteration_exceeded|killed|budget_exceeded|api_error
  started_at      TEXT NOT NULL
  ended_at        TEXT
  final_report    TEXT
  error           TEXT
  iterations      INTEGER DEFAULT 0
  input_tokens    INTEGER DEFAULT 0
  output_tokens   INTEGER DEFAULT 0
  -- full spec snapshot for re-run:
  spec_json       TEXT NOT NULL          -- {system_prompt, tools, workspace, first_user_message, sandbox}

logs
  id              INTEGER PK
  run_id          INTEGER NOT NULL REFERENCES agent_runs(id)
  seq             INTEGER NOT NULL       -- monotonic within run
  ts              TEXT NOT NULL
  level           TEXT NOT NULL          -- info|tool_use|tool_result|assistant_text|warn|error
  message         TEXT NOT NULL
  INDEX (run_id, seq)

ticket_audit
  id              INTEGER PK
  ticket_id       INTEGER NOT NULL
  ts              TEXT NOT NULL
  actor           TEXT NOT NULL          -- human|auto|system
  event           TEXT NOT NULL          -- status_change|created|edited|killed|retried|plan_approved
  from_status     TEXT
  to_status       TEXT
  note            TEXT
```

Persona catalog lives in **code** (`tasklane/agents/personas.py`) — same rationale as tools catalog. Each entry: `{name, description, system_prompt, default_tools, default_lanes_active, suggested_model}`.

---

## 4. Personas

A **persona** is a **form pre-fill template**, not a runtime behavior. When you pick a persona in the create-ticket drawer, its template populates:
- the description field (Role / Workflow / Hard Rules / Report Format, following the my-agents four-section pattern)
- default tool allowlist
- default active-lanes
- suggested model per lane

You can edit any of these before creating the ticket. Once the ticket exists, `persona` is just a label on the card — the description (system prompt) is what drives the agent.

**Initial persona catalog (templates, stored in `tasklane/agents/personas.py`):**

| Persona | Use case | Default tools | Lanes active | Suggested model |
|---|---|---|---|---|
| `software_engineer` | Writes & modifies code | list_files, read_file, write_file, run_tests, run_linter, run_shell | Plan, In Progress, In Review, In Testing | Sonnet |
| `software_architect` | Produces design docs | list_files, read_file, write_file, web_search | Plan, In Progress, In Review | Sonnet |
| `data_analyst` | Analyzes data, writes reports | list_files, read_file, write_file, run_shell | Plan, In Progress, In Review | Sonnet |
| `research_assistant` | Web research, synthesis | web_search, web_fetch, read_file, write_file | Plan, In Progress, In Review | Sonnet |
| `qa_engineer` | Writes & runs tests | list_files, read_file, write_file, run_tests | Plan, In Progress, In Testing | Sonnet |
| `code_reviewer` | Reviews diffs, patches bugs | list_files, read_file, write_file, run_linter, run_tests | In Review, In Testing | Sonnet |
| `custom` | Write your own prompt | (none pre-selected) | all | Sonnet |

**Custom persona:** description field starts empty; user writes the full system prompt from scratch.

**Lane skipping:** if a persona's active-lanes exclude a lane (e.g., `research_assistant` skips In Testing), drag to that lane auto-advances without spawning an agent. Audit log records `actor=system, note=lane_skipped`.

**Why description = system prompt (final design):** one authoritative field the user can see and edit. No hidden layer between what the user writes and what the agent receives. Personas are scaffolding, not a runtime contract.

---

## 5. Database choice — SQLite + WAL

Same rationale as v1. Single writer via log-writer thread; readers don't block. `PRAGMA busy_timeout=5000`. Migration path to Postgres is local to `core/db.py` if ever needed.

---

## 6. Frontend — React + Vite (**revised from v1**)

**Switching from vanilla HTML to React.** Original reasoning "no build step" loses against these needs surfaced in v2:
- Color themes, rich card states (running / idle / error / queued), model selector modals, log tail panels, audit drawer.
- Real-time updates from SSE across multiple cards simultaneously.
- Form complexity for ticket creation (persona dropdown → dynamic tool/lane checkboxes).

Vanilla JS could do all of this, but fighting DOM manipulation for every SSE update on every card negates the "understand every layer" ethos — you'd end up building a mini-React by hand.

**Stack:**
- React 18 + Vite (fast dev server, one-command build).
- TypeScript (types derived from Pydantic via codegen, or hand-written).
- **Tailwind CSS** for theme consistency.
- **dnd-kit** (`@dnd-kit/core`) for drag-and-drop — accessible, modern, small. Rejected alternatives: react-beautiful-dnd (unmaintained), HTML5 native (accessibility poor).
- **EventSource** (native browser API) for SSE — no library needed.
- **Zustand** for client state — simpler than Redux, enough for a board.
- Served by FastAPI in production (`/static` mount), dev via Vite proxy.

**Why not Next.js:** no SSR needed, no routing beyond single page, overkill.

---

## 6b. UI design specification

### Color theme — "Ink on paper" (dark-on-light, minimal chrome)

```
Background        #FAFAF7     off-white paper
Surface (card)    #FFFFFF     pure white
Surface alt       #F3F2EE     muted for lane headers
Border subtle     #E5E4DF
Text primary      #1F1F1F     near-black ink
Text secondary    #6B6B6B     muted gray
Accent            #2E5CFF     calm blue for primary actions
Accent soft       #E8EEFF     hover/selected bg
Success           #0A7D3E
Warning           #B76E00
Danger            #C0392B     Error lane, kill button
Running           #8A4FFF     violet pulse on active runs
```

Dark mode variant flipped around `#0E0E0E` / `#1A1A1A` with the same semantic tokens. System theme detection via `prefers-color-scheme`; toggle in header.

### Typography
- UI: **Inter** (system fallback: `-apple-system, ui-sans-serif`), 14px base.
- Monospace (log tail, code blocks): **JetBrains Mono** (fallback: `ui-monospace, Menlo`), 13px.
- Headings: Inter Medium; never bold-bold (keep it calm).

### Layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│ ≡  tasklane             [+ New ticket]        [dark ◉]  [settings]       │  header (56px)
├────────┬────────┬──────────────┬───────────┬──────────────┬──────┬───────┤
│ Todo   │ Plan   │ In Progress  │ In Review │ In Testing   │ Done │ Error │  lane row
│   3    │   1 ●  │    2 ●       │    0      │    1 ●       │  7   │  0    │  (counts; ● = has active run)
├────────┼────────┼──────────────┼───────────┼──────────────┼──────┼───────┤
│ ┌────┐ │ ┌────┐ │  ┌─────────┐ │           │  ┌─────────┐ │  ... │       │
│ │card│ │ │card│ │  │card    ⟳│ │           │  │card    ⟳│ │      │       │  card stack
│ └────┘ │ └────┘ │  └─────────┘ │           │  └─────────┘ │      │       │
│ ┌────┐ │        │  ┌─────────┐ │           │              │      │       │
│ │card│ │        │  │card    ⟳│ │           │              │      │       │
│ └────┘ │        │  └─────────┘ │           │              │      │       │
└────────┴────────┴──────────────┴───────────┴──────────────┴──────┴───────┘
```

Lane widths equal on 1440+ viewports; scroll horizontally below 1200px.

### Ticket card (collapsed)

```
┌────────────────────────────────────┐
│ [urgency-dot] TASK-042             │
│ Fix divide-by-zero in math_utils   │   title, 1-2 lines, truncated
│                                    │
│ 🧑‍💻 software_engineer               │   persona chip
│ ⟳ running · 3 iters · 1.2k tok     │   run status (if active)
│                                    │
│ [tools] [workspace ↗] [▼]          │   footer row
└────────────────────────────────────┘
```

- **urgency-dot color:** low = gray, normal = blue, high = amber, critical = red.
- **Running state:** left border animates violet pulse; `⟳` spins.
- **Error state:** card border red, title prefixed ⚠.
- **Hover:** slight lift (1px shadow), cursor-grab.

### Ticket card (expanded)

Clicking a card expands it in-place to ~2x height + shows:
- Full description (markdown rendered)
- Per-lane timeline (dots at each lane w/ last run status + token/iteration count)
- Active log tail (`<pre>` monospace, auto-scroll, cap 500 visible lines)
- Action row: [Kill] [Open workspace] [View full log] [Collapse]

### Drag interactions

- Picking up a card shows ghost at cursor; origin lane dims.
- Valid drop targets highlight with `Accent soft` bg.
- On drop → **Model selector modal** appears (Sonnet pre-selected):
  ```
  Moving TASK-042 to In Progress
  
  Pick model for this phase:
  ( ) claude-haiku-4-5          cheap, fast
  ( ) claude-sonnet-4-5  ◉      default
  ( ) claude-opus-4-6           strongest
  
  Urgency: normal
  
  [Cancel]  [Spawn agent]
  ```
- Dragging to same lane → no-op.
- **Dragging a ticket with an active run is disabled** (card is not draggable). User must kill the run first via the Kill button; only then can the card be dragged.

### Ticket creation form

Modal or side-drawer with:
1. Title (text)
2. Persona (dropdown; selecting pre-fills below — description, tools, lanes)
3. Description (markdown textarea — **this is the system prompt** sent to the agent; pre-filled by persona template)
4. Workspace absolute path (text + "Pick directory" helper; **validated on submit — rejects non-existent paths**)
5. Urgency (4 radio buttons)
6. Tools (checkboxes grouped: Filesystem / Execution / Web; pre-filled from persona)
7. Active lanes (checkboxes; pre-filled from persona; unchecked lanes auto-advance)
8. **Advanced (collapsed by default):**
   - Max iterations override (numeric; default = urgency-derived)
   - Per-lane model override (dropdowns; default = Sonnet)
   - `agents_json` override (raw JSON for power users)

### Empty states & microcopy
- Empty lane: muted italic text "drop here" only when a card is being dragged.
- Empty board: centered "No tickets yet. Create your first →"
- Log tail empty: "Agent idle. Drag to an agent lane to start."

### Accessibility
- Keyboard: `Tab` cycles cards; `Space` grabs/drops; `←/→` moves between lanes when grabbed.
- All color signals also have icon or text counterpart.
- Focus rings visible (2px `Accent`).

---

## 7. Lane semantics (updated with Plan lane)

| Lane         | Has agent? | Default agent | Purpose                                                    |
|--------------|------------|---------------|------------------------------------------------------------|
| Todo         | No         | —             | Parking lot                                                |
| **Plan**     | Yes        | `planner`     | Produces a plan/approach document; user reviews & approves |
| In Progress  | Yes        | persona's main | Executes the plan (code / analysis / research)            |
| In Review    | Yes        | `reviewer`    | Reviews output                                             |
| In Testing   | Yes        | `tester`      | Validates (skipped for non-code personas)                  |
| Done         | No         | —             | Terminal                                                   |
| Error        | No         | —             | Failures                                                   |

**Plan lane flow:**
1. User drags Todo → Plan + selects model.
2. Planner agent spawns with persona's system prompt + "you are in PLAN phase; don't execute, produce a step-by-step approach and critical files list."
3. Plan result stored as `final_report`.
4. Ticket **sits in Plan** until user drags it to In Progress (approval gate).
5. User may edit description to incorporate plan feedback before dragging (unlock-for-edit only allowed in Plan lane post-completion).
6. On drag to In Progress, prior plan's `final_report` auto-injects into In Progress's first user message.

**Lanes skipped per persona** auto-advance without agent spawn (e.g., `research_assistant` skips In Testing).

---

## 8. Agent-to-lane mapping

Hybrid: lane defaults + per-ticket override via `agents_json` + persona's `lanes_active` filter.

Resolution order at spawn time:
1. `ticket.agents_json[lane]` if set (including explicit `null` = skip).
2. Else `persona.agents_per_lane[lane]` from catalog.
3. Else generic default (`planner`, `coder`, `reviewer`, `tester`).

---

## 9. Tools — catalog + allowlist

**No inline custom tools in MVP. No sandboxing in MVP.** Tools execute in-process against the user's real workspace path — same blast radius as running an agent from my-agents directly. The user is the only operator; this matches the localhost/trusted posture.

**Catalog:**
- `list_files(directory)` — read-only, workspace-scoped
- `read_file(filepath)` — workspace-scoped
- `write_file(filepath, content)` — workspace-scoped; reviewer agent refuses test files
- `run_tests(target)` — pytest; returns `"Error: pytest not available"` if missing
- `run_linter(target)` — flake8; same graceful-miss behavior
- `run_shell(cmd)` — ticket must explicitly allowlist; no sandbox in MVP, so use with care
- `web_search(query)` — lifted from web_search_agent
- `web_fetch(url)` — lifted from web_search_agent

**Scope check (all workspace tools):** `os.path.realpath(resolved).startswith(os.path.realpath(workspace_root))` → else return `"Error: path escapes workspace."`. This is the only guardrail in MVP.

**Stretch (deferred from MVP):**
- Subprocess sandbox (workspace copy + env scrub + timeouts)
- Docker sandbox for network egress control
- Change-promotion UI with diff preview
- `run_notebook` for data_analyst persona

---

## 10. Urgency

| Urgency | Suggested model (user can override) | Default MAX_ITERATIONS |
|---|---|---|
| low | haiku-4-5 | 10 |
| normal | sonnet-4-5 | 20 |
| high | opus-4-6 | 20 |
| critical | opus-4-6 | 30 |

Urgency only influences **sort order, suggested model, MAX_ITERATIONS**. Model is ultimately picked by user per-phase at drag time.

---

## 11. Concurrency — parallel tickets

**Yes, parallel tickets run concurrently** — that's the whole point of the kanban metaphor.

Mechanics:
- One `threading.Thread` per active run.
- `ACTIVE_RUNS: dict[ticket_id, RunHandle]` — one active run **per ticket**. Two tickets = two threads.
- **Global cap:** `MAX_CONCURRENT_RUNS = 4` (configurable). Overflow queues in `pending_runs` table; scheduler pulls when slot frees.
- Queued tickets show `⏸ queued` chip + position ("2 ahead of this").
- Workspace contention: **tasklane cannot prevent it.** If two tickets point to overlapping paths, it's the user's responsibility. UI warns on ticket creation if workspace is shared with another active ticket.
- DB writes serialized through log-writer thread. HTTP handlers use `BEGIN IMMEDIATE`.

**Scheduler pseudocode:**
```python
def on_status_change(ticket_id, new_lane):
    if agent_for_lane(ticket_id, new_lane) is None:
        return  # non-agent lane
    with scheduler_lock:
        if len(ACTIVE_RUNS) < MAX_CONCURRENT_RUNS:
            spawn_thread(ticket_id, new_lane)
        else:
            pending_runs.insert(ticket_id, new_lane)

def on_run_end(ticket_id):
    with scheduler_lock:
        next_up = pending_runs.pop_oldest()
        if next_up: spawn_thread(*next_up)
```

---

## 12. Directory structure

```
tasklane/
├── README.md
├── CLAUDE.md
├── server.py                       # FastAPI + uvicorn entrypoint
├── requirements.txt                # anthropic, fastapi, uvicorn, pydantic
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api.ts                  # REST + SSE client
│       ├── store.ts                # Zustand
│       ├── theme.css               # CSS tokens for light/dark
│       ├── components/
│       │   ├── Board.tsx
│       │   ├── Lane.tsx
│       │   ├── TicketCard.tsx
│       │   ├── TicketCardExpanded.tsx
│       │   ├── CreateTicketDrawer.tsx
│       │   ├── ModelPickerModal.tsx
│       │   ├── LogTail.tsx
│       │   └── Header.tsx
│       └── types.ts                # TS types mirroring Pydantic
├── tasklane/
│   ├── __init__.py
│   ├── core/
│   │   ├── db.py
│   │   ├── enums.py
│   │   ├── models.py               # Pydantic
│   │   ├── pubsub.py
│   │   └── logger.py
│   ├── api/
│   │   ├── tickets.py
│   │   ├── runs.py
│   │   ├── tools.py                # tool catalog endpoint
│   │   └── personas.py             # persona catalog endpoint
│   ├── orchestration/
│   │   ├── scheduler.py
│   │   ├── runner.py
│   │   └── lane_config.py
│   └── agents/
│       ├── base.py                 # run_lane_agent(spec) — the shared while-True
│       ├── tools.py                # catalog + impls
│       ├── personas.py             # persona catalog
│       ├── registry.py             # agent_type → function
│       ├── planner.py
│       ├── coder.py
│       ├── reviewer.py
│       ├── tester.py
│       ├── researcher.py
│       ├── analyst.py
│       └── architect.py
├── runs/                           # per-run logs (gitignored)
│   └── {run_id}.log
└── tasklane.db                     # SQLite (gitignored)
```

Note: no `workspaces/` dir — **user specifies absolute workspace path per ticket**.

---

## 13. Remaining open questions

All v2 questions are resolved (see user-approved decisions table at top).

---

## 14. Trade-offs table

| Decision | Chose | Rejected | Why |
|---|---|---|---|
| DB | SQLite + WAL | Postgres | Localhost ethos |
| HTTP | FastAPI | http.server | SSE + Pydantic free |
| Frontend | **React + Vite + Tailwind** | Vanilla HTML/JS | Multi-card real-time UI, themes, forms — vanilla becomes DIY framework |
| DnD lib | @dnd-kit | react-beautiful-dnd, native HTML5 | Maintained, accessible |
| Concurrency | Threads | asyncio / subprocess | SDK sync; parallel runs natural |
| Failure path | Error lane | Auto-revert | No oscillation |
| Tools | Catalog + allowlist | Inline custom | No arbitrary code exec |
| Tool sandbox | **None in MVP** | subprocess / Docker | Keep MVP scope focused; trusted localhost operator |
| Prompt architecture | Description = system prompt | Persona template + description-as-task | One authoritative prompt field the user can see and edit |
| Cancel | Cooperative flag | Thread kill | CPython safety |
| Urgency | Model suggest + iterations | Prompt tone | Prompt cacheability |
| Persona | Catalog in code | Table in DB | No versioning pain |
| Lane count | 6 (add Plan) | 5 | Plan approval gate |
| Model choice | Per-phase at drag time | Fixed at ticket creation | User wants flexibility |
| Workspace | User absolute path | Managed sandbox dir | User drives own codebase |
| Restart policy | Mark crashed + full spec snapshot | Attempt resume | Resume is unreliable |

---

## 15. Implementation sequence (phased)

**Phase 1 — Backend skeleton:**
1. `core/db.py` + schema + WAL + migrations
2. `core/enums.py`, `core/models.py` Pydantic
3. `api/tickets.py` full CRUD + status PATCH (stub hook)
4. `api/tools.py`, `api/personas.py` catalog endpoints
5. Manual curl test: create ticket, list, edit

**Phase 2 — Agent base:**
6. `agents/base.py` — port my-agents loop; parametrize
7. `agents/tools.py` — catalog + workspace-scoped + sandbox flag
8. `agents/personas.py` — 6 personas + system prompt templates
9. `agents/registry.py`
10. Individual agent files (`planner.py`, `coder.py`, etc.) — each = persona-specific system prompt + tool preferences

**Phase 3 — Orchestration:**
11. `core/logger.py` + `core/pubsub.py`
12. `orchestration/runner.py` — threaded runs, status hooks, auto-advance
13. `orchestration/scheduler.py` — concurrency cap, queue, parallel support
14. Wire status PATCH → scheduler

**Phase 4 — Frontend:**
16. Vite project scaffold, Tailwind config, theme tokens
17. API client + Zustand store + types
18. Board / Lane / TicketCard components
19. Create drawer, Model picker modal, Log tail
20. DnD wiring + optimistic/pessimistic updates
21. SSE subscription + reconnect logic

**Phase 5 — Observability & polish:**
22. Error lane UI + rerun flow
23. Audit log drawer
24. Dark mode toggle
25. Kill / cancel UX
26. Token budget display + warnings

Stretch after Phase 5.

---

## 16. Verification

After Phase 4, these scenarios should pass end-to-end:

**A. Coding task, full pipeline:**
1. Create ticket: persona `software_engineer`, workspace `/path/to/my-agents/review_agent`, description auto-filled from persona template + user adds "Fix divide-by-zero in math_utils.py. Tests in tests/.", urgency normal, tools default.
2. Drag Todo → Plan, pick Sonnet. Planner outputs approach.
3. Review plan in expanded card, drag Plan → In Progress, pick Sonnet. Coder writes fix directly in workspace.
4. Ticket advances to In Review. Reviewer checks diff, runs linter.
5. Advances to In Testing. Tester runs pytest → green.
6. Lands in Done.

**B. Research task:**
1. Create ticket: persona `research_assistant`, workspace `/tmp/research-out`, description "What are the tradeoffs between SSE and WebSockets for real-time UIs?".
2. Drag Todo → Plan → In Progress → In Review → Done (In Testing auto-skipped).
3. Each lane's log shows web searches, fetches, synthesis.

**C. Parallel execution:**
1. Create 3 independent tickets, different workspaces.
2. Drag all 3 to In Progress in quick succession.
3. All 3 threads active; 4th queues. Logs stream independently on each card.

**D. Failure + rerun:**
1. Create ambiguous ticket that exhausts MAX_ITERATIONS.
2. Ticket lands in Error with status `iteration_exceeded`.
3. Click "Re-run from failed lane" → spawns new run with same spec.

**E. Restart recovery:**
1. Start a long-running ticket.
2. Kill the server mid-run.
3. Restart server. Ticket status → Error, note `server_restart`.
4. Click "Re-run" → new run with stored spec, fresh context.

**F. Kill:**
1. Start a run; attempt to drag the card → drag is disabled (tooltip: "Kill the active run first").
2. Click Kill button → log emits "cancel requested"; within 1 iteration run ends; `run.status = killed`; ticket returns to Error lane (or previous lane — final call: **Error lane** so the state is always explicit).
3. After kill, card is draggable again.

---

## 17. Non-goals

- Auth / multi-user
- Cloud deployment
- Postgres, Redis, queue brokers
- AI-driven lane definitions
- Inline custom tools (MVP)
- Email / Slack notifications
- Cost dashboards / billing beyond token counts
- **Tool sandboxing of any kind** (MVP)
- Persona CRUD via UI (code-only in MVP)

---

## Critical files to be created

**Backend:**
- `tasklane/server.py`
- `tasklane/tasklane/core/{db,enums,models,logger,pubsub}.py`
- `tasklane/tasklane/api/{tickets,runs,tools,personas}.py`
- `tasklane/tasklane/orchestration/{runner,scheduler,lane_config}.py`
- `tasklane/tasklane/agents/{base,tools,personas,registry,planner,coder,reviewer,tester,researcher,analyst,architect}.py`

**Frontend:**
- `tasklane/frontend/package.json`, `vite.config.ts`, `tailwind.config.js`
- `tasklane/frontend/src/{main,App,api,store,types,theme}.{ts,tsx,css}`
- `tasklane/frontend/src/components/{Board,Lane,TicketCard,TicketCardExpanded,CreateTicketDrawer,ModelPickerModal,LogTail,Header}.tsx`

**Docs:**
- `tasklane/CLAUDE.md`
- `tasklane/README.md`

## Reference files to re-read line-by-line before implementing

- `my-agents/testing_agent/agent.py` — canonical loop
- `my-agents/review_agent/agent.py` — tool scoping + write refusals
- `my-agents/pr_pipeline/orchestrator.py` — multi-agent dispatch
- `my-agents/web_search_agent/agent.py` — stdlib HTTP
- `my-agents/CLAUDE.md`
- `my-agents/structure/*.md`
