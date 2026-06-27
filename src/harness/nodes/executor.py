"""Stage 2 — Executor. Edits exactly one file via path-guarded Anthropic tool-use.

The only place in the harness where file mutations happen. Runs an agentic
tool-use loop until the model stops requesting tools (or a safety cap is hit).

On entry it resets the workdir to the last committed (= last passed task) state,
so a partial/failed prior attempt — or a crash mid-executor — never leaves dirty
edits that would corrupt `search_replace` on retry. On a retry it injects the
verifier's one-line diagnosis so the model fixes precisely the reported error,
and on the final retry it escalates to the stronger model.
"""

from __future__ import annotations

from .. import gitutil
from ..config import (
    MAX_VERIFIER_ITERATIONS,
    MODEL_EXECUTOR,
    MODEL_EXECUTOR_HARD,
    get_client,
    load_prompt,
)
from ..state import RunState
from ..telemetry import record_tokens, set_attr, span
from ..tools.fs_tools import EXECUTOR_TOOLS, dispatch_tool

_MAX_TOOL_TURNS = 8


def _build_initial_message(task: dict, feedback: list[dict]) -> str:
    parts = [
        f"Task: {task['action']}",
        f"Target file: {task['path']}",
    ]
    if task.get("depends_on"):
        parts.append(f"Depends on: {', '.join(task['depends_on'])}")
    if feedback:
        parts.append("\nThe previous attempt failed verification. Recent feedback:")
        for fb in feedback:
            # Prefer the crisp Haiku diagnosis; fall back to raw output if absent.
            if fb.get("diagnosis"):
                parts.append(f"- iteration {fb['iteration']}: {fb['diagnosis']}")
            else:
                parts.append(
                    f"- iteration {fb['iteration']}: "
                    f"stdout={fb['stdout'][-1500:]!r} stderr={fb['stderr'][-1500:]!r}"
                )
        parts.append("Fix precisely the reported error.")
    return "\n".join(parts)


def _system_blocks() -> list[dict]:
    # Cache the (static) system prompt prefix so repeated executor calls within
    # the tool loop and across retries hit cache pricing instead of re-billing.
    return [
        {
            "type": "text",
            "text": load_prompt("executor"),
            "cache_control": {"type": "ephemeral"},
        }
    ]


def execute_node(state: RunState) -> dict:
    with span("executor"):
        task = state["plan"]["tasks"][state["current_task_index"]]
        feedback = state["feedback"][-3:]
        workdir = state["workdir"]

        # Start each attempt from the last known-good filesystem state.
        gitutil.reset_to_head(workdir)

        iteration = state.get("iteration", 0)
        # Escalate to the stronger model on the final allowed retry.
        model = (
            MODEL_EXECUTOR_HARD
            if iteration >= MAX_VERIFIER_ITERATIONS - 1
            else MODEL_EXECUTOR
        )
        set_attr("task.index", state["current_task_index"])
        set_attr("task.path", task["path"])
        set_attr("retry", bool(feedback))
        set_attr("model", model)

        messages = [
            {"role": "user", "content": _build_initial_message(task, feedback)}
        ]

        spent = 0
        for _ in range(_MAX_TOOL_TURNS):
            msg = get_client().messages.create(
                model=model,
                max_tokens=4000,
                system=_system_blocks(),
                tools=EXECUTOR_TOOLS,
                messages=messages,
            )
            record_tokens(msg.usage)  # accumulates across the tool-use loop
            spent += (msg.usage.input_tokens or 0) + (msg.usage.output_tokens or 0)
            messages.append({"role": "assistant", "content": msg.content})

            tool_uses = [b for b in msg.content if b.type == "tool_use"]
            if not tool_uses:
                break

            results = []
            for tu in tool_uses:
                try:
                    out = dispatch_tool(tu.name, workdir, tu.input)
                    results.append(
                        {"type": "tool_result", "tool_use_id": tu.id, "content": out}
                    )
                except Exception as e:  # surface guard/IO errors back to the model
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tu.id,
                            "content": f"ERROR: {e}",
                            "is_error": True,
                        }
                    )
            messages.append({"role": "user", "content": results})

        return {
            "status": "verifying",
            "tokens_spent": state.get("tokens_spent", 0) + spent,
        }
