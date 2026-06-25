"""Durable checkpointing.

LangGraph 1.x exposes `SqliteSaver.from_conn_string` only as a context manager,
which would close the DB when the `with` block exits. For a harness whose process
may be killed and re-launched, we instead bind a SqliteSaver to a long-lived
sqlite3 connection on disk, so checkpoints persist across process invocations and
resume reloads the last committed state.
"""

from __future__ import annotations

import os
import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver

DEFAULT_DB = os.getenv("CHECKPOINT_DB", "checkpoints.db")


def make_checkpointer(db_path: str | None = None) -> SqliteSaver:
    conn = sqlite3.connect(db_path or DEFAULT_DB, check_same_thread=False)
    return SqliteSaver(conn)
