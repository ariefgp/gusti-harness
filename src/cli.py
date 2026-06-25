"""CLI entrypoint:  python -m src.cli run <repo_url>

With a checkpointer compiled in, every run is keyed by `thread_id == run_id`.
Re-invoking the same run_id resumes from the last checkpoint: the Planner never
re-runs (plan is persisted) and completed files are skipped.
"""

from __future__ import annotations

import os
import sys
import uuid

import typer

from src.harness.checkpoint import make_checkpointer
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


def _report(final: dict):
    typer.echo(f"\nstatus={final['status']}")
    plan = final.get("plan") or {}
    typer.echo(
        f"tasks={len(plan.get('tasks', []))} completed_index={final['current_task_index']}"
    )
    for fb in final.get("feedback", []):
        flag = "PASS" if fb["passed"] else "fail"
        typer.echo(f"  [{flag}] iter={fb['iteration']}")


@app.command()
def run(
    repo_url: str = typer.Argument(..., help="file:// path, local path, or git URL"),
    run_id: str = typer.Option(None, help="Stable id (resume key). Random if omitted."),
    no_checkpoint: bool = typer.Option(False, help="Run unpersisted (no resume)."),
):
    """Run the Planner -> Executor -> Verifier graph against a repo (resumable)."""
    run_id = run_id or uuid.uuid4().hex[:12]
    workdir = prepare_workdir(repo_url, run_id)
    typer.echo(f"run_id={run_id}")
    typer.echo(f"workdir={workdir}")

    checkpointer = None if no_checkpoint else make_checkpointer()
    graph = compile_app(checkpointer=checkpointer)
    config = {"recursion_limit": 50, "configurable": {"thread_id": run_id}}

    # Resume if a checkpoint already exists for this thread_id.
    resume = False
    if checkpointer is not None:
        snapshot = graph.get_state(config)
        resume = bool(snapshot.values)

    inp = None if resume else _initial_state(repo_url, workdir)
    if resume:
        typer.echo("resuming from last checkpoint (planner skipped)")

    # HARNESS_CRASH_AFTER_TASK=N simulates kill -9 right after N files have fully
    # passed verification. stream() yields only after a node's checkpoint is
    # durably committed, so exiting here loses no completed work — resume then
    # cleanly SKIPS the N done files and never re-plans (the clean resume proof).
    crash_after_task = os.getenv("HARNESS_CRASH_AFTER_TASK")
    if crash_after_task:
        target = int(crash_after_task)
        armed = False
        for chunk in graph.stream(inp, config=config, stream_mode="updates"):
            node, update = next(iter(chunk.items()))
            typer.echo(f"  node done: {node} -> index={update.get('current_task_index')}")
            # stream yields a step's update *before* its checkpoint commits, so we
            # arm on the advancing verifier and crash on the *next* step boundary,
            # by which point the 'N files done' checkpoint is durably written.
            if armed:
                typer.echo(f">>> simulating crash (kill -9); {target} file(s) durably committed")
                sys.stdout.flush()
                os._exit(137)
            if node == "verifier" and update.get("current_task_index") == target:
                armed = True
        final = graph.get_state(config).values
    else:
        final = graph.invoke(inp, config=config)

    _report(final)


if __name__ == "__main__":
    app()
