"""Stage 3 — Verifier. Runs tests + lint in the sandbox and decides loop vs advance.

On pass: commit the working tree (a durable filesystem snapshot aligned with the
RunState checkpoint), advance `current_task_index`, reset `iteration`, go back to
executing. On fail: run a cheap Haiku diagnosis over the test output to produce a
one-line, actionable hint for the executor, append feedback, bump `iteration`.
Routing (graph.py) sends it back to the executor while iteration < cap, else aborts.
"""

from __future__ import annotations

import os

from .. import gitutil
from ..config import MODEL_VERIFIER, get_client, load_prompt
from ..state import RunState
from ..telemetry import record_tokens, set_attr, span
from ..tools.sandbox import run_in_sandbox

# Deterministic slice defaults to pytest-only; set VERIFY_CMD to add `&& ruff check .`
# once a lenient ruff config is in place.
DEFAULT_VERIFY_CMD = "python -m pytest -q"


def _diagnose(stdout: str, stderr: str) -> tuple[str, int]:
    """One Haiku call -> a single-line, actionable diagnosis (+ tokens spent)."""
    try:
        msg = get_client().messages.create(
            model=MODEL_VERIFIER,
            max_tokens=200,
            system=load_prompt("verifier"),
            messages=[
                {
                    "role": "user",
                    "content": f"stdout:\n{stdout[-3000:]}\n\nstderr:\n{stderr[-3000:]}",
                }
            ],
        )
        record_tokens(msg.usage)
        text = msg.content[0].text.strip() if msg.content else ""
        spent = (msg.usage.input_tokens or 0) + (msg.usage.output_tokens or 0)
        return text, spent
    except Exception:
        return "", 0  # diagnosis is best-effort; raw output still flows through


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
        # Durable filesystem snapshot for this completed task.
        task = state["plan"]["tasks"][state["current_task_index"]]
        gitutil.commit_progress(
            state["workdir"], f"task {state['current_task_index']}: {task['action']}"
        )
        next_index = state["current_task_index"] + 1
        all_done = next_index >= len(state["plan"]["tasks"])
        return {
            "feedback": state["feedback"] + [fb],
            "current_task_index": next_index,
            "iteration": 0,
            "status": "done" if all_done else "executing",
        }

    diagnosis, spent = _diagnose(result.out, result.err)
    fb["diagnosis"] = diagnosis
    set_attr("diagnosis", diagnosis)
    return {
        "feedback": state["feedback"] + [fb],
        "iteration": it + 1,
        "tokens_spent": state.get("tokens_spent", 0) + spent,
        "status": "verifying",
    }
