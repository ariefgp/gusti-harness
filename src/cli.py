"""CLI entrypoint:  python -m src.cli run <repo_url>

Phase 3 runs the graph unpersisted. Phase 4 adds the checkpointer + resume.
"""

from __future__ import annotations

import uuid

import typer

from src.harness.graph import compile_app
from src.harness.workspace import prepare_workdir

app = typer.Typer(add_completion=False, help="gusti-harness — multi-file refactor agent")


@app.callback()
def _main():
    """Keep `run` as an explicit subcommand even though it's the only one."""


def _initial_state(repo_url: str, workdir: str) -> dict:
    return {
        "repo_url": repo_url,
        "workdir": workdir,
        "plan": None,
        "current_task_index": 0,
        "iteration": 0,
        "feedback": [],
        "status": "planning",
    }


@app.command()
def run(
    repo_url: str = typer.Argument(..., help="file:// path, local path, or git URL"),
    run_id: str = typer.Option(None, help="Stable id (resume key). Random if omitted."),
):
    """Run the Planner -> Executor -> Verifier graph against a repo."""
    run_id = run_id or uuid.uuid4().hex[:12]
    workdir = prepare_workdir(repo_url, run_id)
    typer.echo(f"run_id={run_id}")
    typer.echo(f"workdir={workdir}")

    graph = compile_app()  # unpersisted for the vertical slice
    final = graph.invoke(
        _initial_state(repo_url, workdir),
        config={"recursion_limit": 50},
    )

    typer.echo(f"\nstatus={final['status']}")
    plan = final.get("plan") or {}
    typer.echo(f"tasks={len(plan.get('tasks', []))} "
               f"completed_index={final['current_task_index']}")
    for fb in final.get("feedback", []):
        flag = "PASS" if fb["passed"] else "fail"
        typer.echo(f"  [{flag}] iter={fb['iteration']}")


if __name__ == "__main__":
    app()
