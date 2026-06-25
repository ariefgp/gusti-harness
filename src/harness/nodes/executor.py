"""Stage 2 — Executor. Edits exactly one file via path-guarded Anthropic tool-use.

The only place in the harness where file mutations happen. Runs an agentic
tool-use loop until the model stops requesting tools (or a safety cap is hit).
On a verifier retry, the last feedback entries are injected so the model fixes
precisely the reported error.
"""

from __future__ import annotations

from ..config import MODEL_EXECUTOR, get_client, load_prompt
from ..state import RunState
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
            parts.append(
                f"- iteration {fb['iteration']}: "
                f"stdout={fb['stdout'][-1500:]!r} stderr={fb['stderr'][-1500:]!r}"
            )
        parts.append("Fix precisely the reported error.")
    return "\n".join(parts)


def execute_node(state: RunState) -> dict:
    task = state["plan"]["tasks"][state["current_task_index"]]
    feedback = state["feedback"][-3:]
    workdir = state["workdir"]

    messages = [
        {"role": "user", "content": _build_initial_message(task, feedback)}
    ]

    for _ in range(_MAX_TOOL_TURNS):
        msg = get_client().messages.create(
            model=MODEL_EXECUTOR,
            max_tokens=4000,
            system=load_prompt("executor"),
            tools=EXECUTOR_TOOLS,
            messages=messages,
        )
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

    return {"status": "verifying"}
