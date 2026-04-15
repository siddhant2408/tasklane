from __future__ import annotations
"""
SQLite database layer.

Uses WAL mode for concurrent reads + single writer.
A dedicated DB_WRITER_THREAD drains the write queue so agent threads
never block waiting on each other.
"""

import os
import queue
import sqlite3
import threading
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tasklane.db")

_local = threading.local()
_write_queue: queue.Queue = queue.Queue()
_writer_thread: threading.Thread | None = None


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    """Return a per-thread read connection (WAL allows concurrent readers)."""
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return _local.conn


@contextmanager
def get_db():
    """Context manager yielding a read connection."""
    conn = _get_conn()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise


def execute_write(sql: str, params: tuple = ()) -> None:
    """Queue a write for the serialized writer thread."""
    done = threading.Event()
    error_holder: list[Exception] = []

    def _task(conn: sqlite3.Connection) -> None:
        try:
            conn.execute(sql, params)
            conn.commit()
        except Exception as e:
            error_holder.append(e)
            conn.rollback()
        finally:
            done.set()

    _write_queue.put(_task)
    done.wait()
    if error_holder:
        raise error_holder[0]


def execute_write_many(ops: list[tuple[str, tuple]]) -> None:
    """Queue multiple writes in a single transaction."""
    done = threading.Event()
    error_holder: list[Exception] = []

    def _task(conn: sqlite3.Connection) -> None:
        try:
            for sql, params in ops:
                conn.execute(sql, params)
            conn.commit()
        except Exception as e:
            error_holder.append(e)
            conn.rollback()
        finally:
            done.set()

    _write_queue.put(_task)
    done.wait()
    if error_holder:
        raise error_holder[0]


def execute_write_returning(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    """Queue a write and return the last inserted row via lastrowid."""
    done = threading.Event()
    result_holder: list = []
    error_holder: list[Exception] = []

    def _task(conn: sqlite3.Connection) -> None:
        try:
            cur = conn.execute(sql, params)
            conn.commit()
            if cur.lastrowid:
                row = conn.execute(
                    "SELECT * FROM tickets WHERE id = ? UNION ALL "
                    "SELECT * FROM agent_runs WHERE id = ?",
                    (cur.lastrowid, cur.lastrowid),
                ).fetchone()
                result_holder.append(cur.lastrowid)
            else:
                result_holder.append(None)
        except Exception as e:
            error_holder.append(e)
            conn.rollback()
        finally:
            done.set()

    _write_queue.put(_task)
    done.wait()
    if error_holder:
        raise error_holder[0]
    return result_holder[0] if result_holder else None


def _writer_loop() -> None:
    """Dedicated writer thread — drains the write queue serially."""
    writer_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    writer_conn.row_factory = sqlite3.Row
    writer_conn.execute("PRAGMA journal_mode=WAL")
    writer_conn.execute("PRAGMA busy_timeout=5000")
    writer_conn.execute("PRAGMA foreign_keys=ON")

    while True:
        task = _write_queue.get()
        if task is None:
            break
        task(writer_conn)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT    NOT NULL,
    description     TEXT    NOT NULL,
    persona         TEXT    NOT NULL DEFAULT 'software_engineer',
    status          TEXT    NOT NULL DEFAULT 'todo',
    urgency         TEXT    NOT NULL DEFAULT 'normal',
    tools_json      TEXT    NOT NULL DEFAULT '[]',
    agents_json     TEXT,
    models_json     TEXT    NOT NULL DEFAULT '{}',
    workspace_path  TEXT    NOT NULL,
    max_iterations  INTEGER,
    blocked_by      INTEGER REFERENCES tickets(id),
    locked          INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id       INTEGER NOT NULL REFERENCES tickets(id),
    lane            TEXT    NOT NULL,
    agent_type      TEXT    NOT NULL,
    persona         TEXT    NOT NULL,
    model           TEXT    NOT NULL,
    max_iterations  INTEGER NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'running',
    started_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    ended_at        TEXT,
    final_report    TEXT,
    error           TEXT,
    iterations      INTEGER NOT NULL DEFAULT 0,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    spec_json       TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS logs (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id  INTEGER NOT NULL REFERENCES agent_runs(id),
    seq     INTEGER NOT NULL,
    ts      TEXT    NOT NULL DEFAULT (datetime('now')),
    level   TEXT    NOT NULL,
    message TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_logs_run_seq ON logs(run_id, seq);

CREATE TABLE IF NOT EXISTS ticket_audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id   INTEGER NOT NULL,
    ts          TEXT    NOT NULL DEFAULT (datetime('now')),
    actor       TEXT    NOT NULL,
    event       TEXT    NOT NULL,
    from_status TEXT,
    to_status   TEXT,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS pending_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id   INTEGER NOT NULL,
    lane        TEXT    NOT NULL,
    model       TEXT    NOT NULL,
    queued_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create schema and start the writer thread. Call once at startup."""
    global _writer_thread

    os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else ".", exist_ok=True)

    # Use a direct connection for schema creation (before writer thread starts)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()

    # Mark any lingering 'running' rows as crashed (server restart recovery)
    _mark_crashed_on_restart()

    _writer_thread = threading.Thread(target=_writer_loop, daemon=True, name="db-writer")
    _writer_thread.start()


def _mark_crashed_on_restart() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON")
    now = "datetime('now')"
    conn.execute(
        "UPDATE agent_runs SET status='crashed', ended_at=datetime('now'), "
        "error='server_restart' WHERE status='running'"
    )
    # Unlock any tickets that were locked by those runs
    conn.execute(
        "UPDATE tickets SET locked=0 WHERE locked=1 AND id IN ("
        "  SELECT ticket_id FROM agent_runs WHERE status='crashed' AND error='server_restart'"
        ")"
    )
    conn.commit()
    conn.close()
