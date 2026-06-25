"""Queue consumer — the horizontal-scale entrypoint.

This is the *same harness code* as the CLI, driven by a queue instead of an
argument. One run == one queue message. Workers are stateless and identical;
scale = run more of them (KEDA on queue depth in prod). Because every run is
keyed by `thread_id == run_id` against a durable checkpointer, a re-delivered
message simply resumes from the last checkpoint instead of starting over.

Message shape (JSON on the `runs` list):
    {"run_id": "abc123", "repo_url": "https://github.com/org/repo"}
"""

from __future__ import annotations

import json
import os

import redis

from src.harness.checkpoint import make_checkpointer
from src.harness.graph import compile_app
from src.harness.telemetry import setup_telemetry
from src.harness.workspace import prepare_workdir

QUEUE = os.getenv("RUNS_QUEUE", "runs")


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


def handle_job(graph, job: dict) -> dict:
    """Process one run. Resumes automatically if a checkpoint already exists."""
    run_id = job["run_id"]
    repo_url = job["repo_url"]
    workdir = prepare_workdir(repo_url, run_id)
    config = {"recursion_limit": 50, "configurable": {"thread_id": run_id}}

    snapshot = graph.get_state(config)
    inp = None if snapshot.values else _initial_state(repo_url, workdir)
    return graph.invoke(inp, config=config)


def main() -> None:
    setup_telemetry()  # honors HARNESS_TELEMETRY
    r = redis.Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
    graph = compile_app(checkpointer=make_checkpointer())
    print(f"worker ready; blocking on queue '{QUEUE}'", flush=True)
    while True:
        _, payload = r.blpop(QUEUE)  # one run == one message
        job = json.loads(payload)
        print(f"-> run {job.get('run_id')}", flush=True)
        try:
            final = handle_job(graph, job)
            print(f"<- run {job.get('run_id')} status={final.get('status')}", flush=True)
        except Exception as e:  # noqa: BLE001 — keep the worker alive across runs
            # The message is consumed; re-enqueue with the same run_id to resume.
            print(f"!! run {job.get('run_id')} errored: {e}", flush=True)


if __name__ == "__main__":
    main()
