"""Stage 3 — Verifier. Runs tests + lint in the sandbox and decides loop vs advance.

On pass: advance `current_task_index`, reset `iteration`, go back to executing.
On fail: append feedback, bump `iteration`. Routing (graph.py) sends it back to the
executor while iteration < cap, else to abort.
"""

from __future__ import annotations

import os

from ..state import RunState
from ..telemetry import set_attr, span
from ..tools.sandbox import run_in_sandbox

# Deterministic slice defaults to pytest-only; set VERIFY_CMD to add `&& ruff check .`
# once a lenient ruff config is in place (Phase 5).
DEFAULT_VERIFY_CMD = "python -m pytest -q"


def verify_node(state: RunState) -> dict:
    # One span per call == one span per verification iteration -> the loop stacks
    # visibly in Phoenix (the back-pressure visual).
    with span("verifier"):
        return _verify(state)


def _verify(state: RunState) -> dict:
    cmd = os.getenv("VERIFY_CMD", DEFAULT_VERIFY_CMD)
    result = run_in_sandbox(state["workdir"], cmd=cmd)
    if os.getenv("HARNESS_FORCE_FAIL"):
        # Cap-trip switch: force the verifier to reject, driving the 3-iteration
        # abort + rollback path (for the forced-failure demo).
        result = result.__class__(ok=False, out=result.out, err="forced failure (HARNESS_FORCE_FAIL)")
    it = state["iteration"]
    set_attr("iteration", it)
    set_attr("passed", result.ok)
    fb = {
        "iteration": it,
        "passed": result.ok,
        "stdout": result.out,
        "stderr": result.err,
    }
    if result.ok:
        next_index = state["current_task_index"] + 1
        all_done = next_index >= len(state["plan"]["tasks"])
        return {
            "feedback": state["feedback"] + [fb],
            "current_task_index": next_index,
            "iteration": 0,
            "status": "done" if all_done else "executing",
        }
    return {
        "feedback": state["feedback"] + [fb],
        "iteration": it + 1,
        "status": "verifying",
    }
