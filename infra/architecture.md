# Architecture & deployment brief

## The harness (one run)

A nearly-linear state machine with a single self-loop on the Verifier. The graph
*is* the state machine; LangGraph's checkpointer *is* the durability layer.

```
                         ┌───────────────────────────────┐
                         │            one run            │
                         │                               │
  repo_url ─▶ [Planner] ─▶ [Executor] ─▶ [Verifier] ─┬─ pass ─▶ next file / END
                  │            ▲              │       │
             read-only         └─── retry ◀──┘  (fail, iter<3)
             JSON plan                          │
                                          (fail, iter=3) ─▶ [Abort + git rollback] ─▶ END
```

- **Planner** (Sonnet, read-only): repo tree → dependency-ordered JSON plan,
  hard-validated, persisted once.
- **Executor** (Sonnet): edits one file via path-guarded tool-use.
- **Verifier** (sandbox): `pytest`(+`ruff`) in an isolated container; loops back to
  the Executor with feedback, max 3 iterations, then aborts.

## Production topology (the scale path)

The *same* harness code runs behind a queue. Nothing about the graph changes; only
the entrypoint does (`src/cli.py` → `src/worker.py`).

```
   client / API
        │  enqueue {run_id, repo_url}
        ▼
   ┌─────────┐     blpop      ┌──────────────────────────────┐
   │  Redis  │ ─────────────▶ │  Worker (N replicas, stateless)│
   │  list   │                │   compile_app(checkpointer)    │
   └─────────┘                │   per run: clone + container   │
        ▲                     └───────────────┬───────────────┘
        │ KEDA scales N                        │ checkpoints
        │ on list length                       ▼
   ┌─────────┐                          ┌─────────────┐     OTLP    ┌──────────┐
   │  KEDA   │                          │  Postgres   │   spans ──▶ │ Phoenix  │
   └─────────┘                          │ checkpoints │             └──────────┘
                                        └─────────────┘
```

One run = one queue message = one `thread_id`. Workers are identical and hold no
run state, so horizontal scale is "run more workers"; KEDA does that automatically
on queue depth (0 → maxReplicas).

---

## Part 2 — the three questions, answered

### 1. State & resilience (crash on step 4 of 10)

- Run state is a typed `RunState` (`src/harness/state.py`) checkpointed by LangGraph
  after every committed super-step, keyed by `thread_id == run_id`.
- The **plan is generated once and persisted** → the Planner never re-runs on
  resume. `current_task_index` advances only after a file passes verification →
  resume **skips completed files**. No duplicate LLM cost, no duplicate edits.
- A re-delivered queue message (worker died, pod evicted) calls `invoke(None, config)`
  and **resumes from the last checkpoint**. Locally this is SQLite; in prod it's the
  Postgres checkpointer — same interface, swap the saver.
- Worst-case cost is bounded by the 3-iteration hard cap per file (→ abort).

### 2. Telemetry (what happened, what did it cost)

- OpenTelemetry spans via Phoenix (`src/harness/telemetry.py`): one span per node,
  token counts per node (accumulated across the executor's tool loop), and **one
  span per verification iteration** so the retry loop is visible as back-pressure.
- The Anthropic SDK is auto-instrumented, so every LLM call is a child span with
  input/output tokens — per-run and per-node cost falls straight out.
- Local: Phoenix UI (no signup). Prod: point `PHOENIX_ENDPOINT` at an OTLP
  collector; nothing else changes.

### 3. Scaling & tenant isolation (thousands of concurrent runs)

- **Scale:** stateless workers + Redis queue + KEDA `ScaledObject` on list length
  (`infra/k8s/`). The unit of scale is one Job/worker per run; the cluster, not the
  code, absorbs concurrency. We ship the architecture, not a running thousand-agent
  cluster (over-engineering is explicitly penalized).
- **Isolation:** each run gets its own clone in a unique dir and its own runner
  container — `--network none`, `--user 1000:1000`, `--read-only`, only its workdir
  mounted. Agent A cannot reach Agent B's filesystem or the network. Path-guarding
  (`fs_tools.safe_path`) is the always-on first layer; the container is the second.

---

## What is intentionally NOT built

- No real thousand-worker cluster — the K8s/KEDA manifests are a credible sketch.
- No multi-agent debate — a linear graph with one verifier loop is the whole point.
- Postgres checkpointer + OTLP collector are wired by config, demoed on SQLite +
  local Phoenix to keep cold-start setup under 15 minutes.
