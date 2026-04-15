"""
Tasklane — FastAPI entrypoint.

Run with:
    ANTHROPIC_API_KEY=sk-... python server.py
"""

import os

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from tasklane.api.personas import router as personas_router
from tasklane.api.runs import router as runs_router
from tasklane.api.tickets import router as tickets_router
from tasklane.api.tools import router as tools_router
from tasklane.core.db import init_db
from tasklane.core.enums import LANE_ORDER, Status
from tasklane.core.models import BoardOut, TicketOut

app = FastAPI(title="Tasklane", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tickets_router)
app.include_router(runs_router)
app.include_router(tools_router)
app.include_router(personas_router)


@app.on_event("startup")
def startup():
    init_db()

    # Ensure runs/ directory exists
    runs_dir = os.path.join(os.path.dirname(__file__), "runs")
    os.makedirs(runs_dir, exist_ok=True)


# ---------------------------------------------------------------------------
# Board endpoint (full state for initial load)
# ---------------------------------------------------------------------------

@app.get("/board", response_model=BoardOut)
def get_board():
    from tasklane.core.db import get_db

    with get_db() as conn:
        rows = conn.execute("SELECT * FROM tickets ORDER BY id").fetchall()
        active_runs = {
            r["ticket_id"]: r["id"]
            for r in conn.execute(
                "SELECT ticket_id, id FROM agent_runs WHERE status = 'running'"
            ).fetchall()
        }

    lanes: dict[str, list[TicketOut]] = {s.value: [] for s in LANE_ORDER}
    lanes[Status.ERROR.value] = []

    for row in rows:
        status = row["status"]
        if status not in lanes:
            lanes[status] = []
        lanes[status].append(TicketOut.from_row(row, active_runs.get(row["id"])))

    return BoardOut(lanes=lanes)


# ---------------------------------------------------------------------------
# Serve frontend build in production
# ---------------------------------------------------------------------------

_frontend_dist = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.isdir(_frontend_dist):
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="static")


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
