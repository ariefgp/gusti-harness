"""Stage 1 — Planner. Read-only: it gets no write tools, only a repo tree.

Emits a dependency-ordered JSON plan, hard-validated against the Plan schema, and
persisted ONCE into state. On resume the Planner never re-runs (no duplicate cost).
"""

from __future__ import annotations

import pathlib

from ..config import MODEL_PLANNER, get_client, load_prompt
from ..state import Plan, RunState
from ..telemetry import record_tokens, set_attr, span

_IGNORE_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".pytest_cache"}


def read_repo_tree(workdir: str, max_files: int = 200) -> str:
    """Return a newline-separated list of repo-relative file paths (metadata only)."""
    root = pathlib.Path(workdir).resolve()
    lines: list[str] = []
    for p in sorted(root.rglob("*")):
        if any(part in _IGNORE_DIRS for part in p.relative_to(root).parts):
            continue
        if p.is_file():
            lines.append(str(p.relative_to(root)))
        if len(lines) >= max_files:
            lines.append("... (truncated)")
            break
    return "\n".join(lines)


def _strip_fences(raw: str) -> str:
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s.rsplit("```", 1)[0]
    return s.strip()


def plan_node(state: RunState) -> dict:
    with span("planner"):
        tree = read_repo_tree(state["workdir"])
        msg = get_client().messages.create(
            model=MODEL_PLANNER,
            max_tokens=2000,
            system=load_prompt("planner"),
            messages=[{"role": "user", "content": f"Repository tree:\n{tree}"}],
        )
        record_tokens(msg.usage)
        raw = msg.content[0].text
        plan = Plan.model_validate_json(_strip_fences(raw))  # hard-validate JSON
        set_attr("plan.n_tasks", len(plan.tasks))
        spent = (msg.usage.input_tokens or 0) + (msg.usage.output_tokens or 0)
        return {
            "plan": plan.model_dump(),
            "status": "executing",
            "current_task_index": 0,
            "iteration": 0,
            "tokens_spent": state.get("tokens_spent", 0) + spent,
        }
