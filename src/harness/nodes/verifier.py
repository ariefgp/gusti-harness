"""Stage 3 — Verifier. Runs tests + lint in the sandbox and decides loop vs advance.

On pass: advance `current_task_index`, reset `iteration`, go back to executing.
On fail: append feedback, bump `iteration`. Routing (graph.py) sends it back to the
executor while iteration < cap, else to abort.
"""

from __future__ import annotations

import os

from ..state import RunState
from ..tools.sandbox import run_in_sandbox

# Deterministic slice defaults to pytest-only; set VERIFY_CMD to add `&& ruff check .`
# once a lenient ruff config is in place (Phase 5).
DEFAULT_VERIFY_CMD = "python -m pytest -q"


def verify_node(state: RunState) -> dict:
    cmd = os.getenv("VERIFY_CMD", DEFAULT_VERIFY_CMD)
    result = run_in_sandbox(state["workdir"], cmd=cmd)
    it = state["iteration"]
    fb = {
        "iteration": it,
        "passed": result.ok,
        "stdout": result.out,
        "stderr": result.err,
    }
    if result.ok:
        return {
            "feedback": state["feedback"] + [fb],
            "current_task_index": state["current_task_index"] + 1,
            "iteration": 0,
            "status": "executing",
        }
    return {
        "feedback": state["feedback"] + [fb],
        "iteration": it + 1,
        "status": "verifying",
    }
