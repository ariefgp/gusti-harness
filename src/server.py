"""HTTP trigger for the hosted demo (Railway).

A tiny FastAPI front door so a grader can run the harness from a browser/curl:

    GET  /            -> demo info page (links to Phoenix, how to trigger)
    GET  /healthz     -> 200 (Railway health check)
    POST /run         -> run the harness against the bundled test-repo, return JSON

`POST /run` is gated by a demo token (`DEMO_TOKEN` env) so the public URL can't
drain the Anthropic key, and serialized by a lock so only one (billable) run
happens at a time. The hosted environment has no Docker-in-Docker, so runs use the
`local` sandbox (FS-path-guarded, not container-isolated) — the container path
stays available for local/`docker compose`. This is stated on the info page.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import uuid

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from src.harness.checkpoint import make_checkpointer
from src.harness.graph import compile_app
from src.harness.telemetry import setup_telemetry
from src.harness.workspace import prepare_workdir

REPO_PATH = os.getenv(
    "DEMO_REPO_PATH", str(pathlib.Path(__file__).resolve().parent.parent / "test-repo")
)
PHOENIX_PUBLIC_URL = os.getenv("PHOENIX_PUBLIC_URL", "")

app = FastAPI(title="gusti-harness demo")
_run_lock = asyncio.Lock()  # one billable run at a time


@app.on_event("startup")
def _startup() -> None:
    setup_telemetry()  # best-effort; no-op if Phoenix unreachable


def _check_token(token: str | None, header_token: str | None) -> None:
    expected = os.getenv("DEMO_TOKEN")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Demo not configured: set DEMO_TOKEN on the server to enable /run.",
        )
    if token != expected and header_token != expected:
        raise HTTPException(status_code=401, detail="Missing or invalid demo token.")


def _initial_state(repo_url: str, workdir: str) -> dict:
    return {
        "repo_url": repo_url,
        "workdir": workdir,
        "plan": None,
        "current_task_index": 0,
        "iteration": 0,
        "feedback": [],
        "tokens_spent": 0,
        "status": "planning",
    }


def _run_harness(force_fail: bool) -> dict:
    run_id = uuid.uuid4().hex[:12]
    repo_url = f"file://{REPO_PATH}"
    workdir = prepare_workdir(repo_url, run_id)
    graph = compile_app(checkpointer=make_checkpointer())
    config = {"recursion_limit": 50, "configurable": {"thread_id": run_id}}

    prev = os.environ.get("HARNESS_FORCE_FAIL")
    if force_fail:
        os.environ["HARNESS_FORCE_FAIL"] = "1"
    try:
        final = graph.invoke(_initial_state(repo_url, workdir), config=config)
    finally:
        if force_fail:
            if prev is None:
                os.environ.pop("HARNESS_FORCE_FAIL", None)
            else:
                os.environ["HARNESS_FORCE_FAIL"] = prev

    plan = final.get("plan") or {}
    return {
        "run_id": run_id,
        "status": final.get("status"),
        "tasks": len(plan.get("tasks", [])),
        "completed_index": final.get("current_task_index"),
        "tokens_spent": final.get("tokens_spent"),
        "iterations": [
            {"iteration": f["iteration"], "passed": f["passed"]}
            for f in final.get("feedback", [])
        ],
        "phoenix_url": PHOENIX_PUBLIC_URL or None,
    }


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/run")
async def run(
    force_fail: bool = Query(False, description="Force the 3-iteration abort demo."),
    token: str | None = Query(None),
    x_demo_token: str | None = Header(None),
) -> dict:
    _check_token(token, x_demo_token)
    if _run_lock.locked():
        raise HTTPException(status_code=429, detail="A run is already in progress.")
    async with _run_lock:
        return await run_in_threadpool(_run_harness, force_fail)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    phoenix_link = (
        f'<p>Traces: <a href="{PHOENIX_PUBLIC_URL}">{PHOENIX_PUBLIC_URL}</a></p>'
        if PHOENIX_PUBLIC_URL
        else "<p>Traces: set PHOENIX_PUBLIC_URL to link the Phoenix UI.</p>"
    )
    return f"""<!doctype html><html><head><title>gusti-harness demo</title></head>
<body style="font-family:system-ui;max-width:42rem;margin:3rem auto;line-height:1.5">
<h1>gusti-harness — live demo</h1>
<p>A Planner/Executor/Verifier agent harness that adds input validation to the
endpoints of a bundled FastAPI test repo, verifying each edit and self-correcting.</p>
<h2>Trigger a run</h2>
<pre>curl -X POST "$URL/run?token=YOUR_TOKEN"            # clean green run
curl -X POST "$URL/run?token=YOUR_TOKEN&amp;force_fail=true"  # forced 3-iteration abort + rollback</pre>
<p>A run takes ~30–90s and returns JSON (status, tasks, per-iteration results,
tokens spent). One run at a time; token-gated.</p>
{phoenix_link}
<p><em>Note:</em> the hosted environment has no Docker-in-Docker, so runs use the
<code>local</code> sandbox (filesystem path-guarded, not container-isolated). The
container-isolated path (<code>--network none</code>, non-root, read-only) is
available for local / docker-compose runs.</p>
</body></html>"""
