# gusti-harness

A production agent harness for **multi-file refactoring**. It runs a nearly-linear
state machine — **Planner → Executor → Verifier** with a single self-loop on the
Verifier — to apply a focused refactor across the files of a repo, verify each
change in an isolated sandbox, and self-correct on failure.

**Niche:** add input validation to API endpoints that lack it (router → handler →
schema). Naturally multi-file, trivially testable (bad payload → expect `422`),
and the failure path self-corrects in a way that exercises the verifier loop.

**Stack:** LangGraph + Python, calling the Anthropic SDK directly inside graph
nodes. LangGraph's checkpointer gives resume-from-crash almost for free, and its
graph *is* the state machine.

## Architecture

```
[Planner] --> [Executor] --> [Verifier] --(pass)--> next file / END
                  ^                |
                  |            (fail, <3 tries)
                  +----------------+
                                   |
                              (fail, =3 tries) --> [Abort + Rollback]
```

- **Planner** — read-only; inspects the repo tree and emits a dependency-ordered
  JSON plan. Generated once and persisted.
- **Executor** — edits exactly one file per step via path-guarded tool-use.
- **Verifier** — runs tests + lint in a sandboxed container; loops back to the
  Executor on failure (max 3 iterations), then aborts with rollback.

Durability comes from a LangGraph checkpointer keyed by `thread_id`: kill the
process mid-run and re-invoke with the same id to resume from the last checkpoint.

## Crash + resume

Every run is keyed by `thread_id == run_id` and checkpointed to SQLite after each
committed super-step. Re-invoking the same `run_id` resumes from the last durable
checkpoint:

```bash
# Run, simulating a kill -9 right after the first file is durably committed:
HARNESS_CRASH_AFTER_TASK=1 python -m src.cli run "file://$PWD/test-repo" --run-id demo
# -> crashes (exit 137) with task 0 done and checkpointed

# Resume with the SAME run_id — planner is skipped, task 0 is skipped:
python -m src.cli run "file://$PWD/test-repo" --run-id demo
# -> "resuming from last checkpoint (planner skipped)" -> status=done
```

**Cost controls:**
- The **plan is generated once** and persisted, so the Planner never re-runs.
- `current_task_index` advances only after a file passes verification, so resume
  **skips completed files** — no duplicate edits, no duplicate tokens.
- A **cumulative token ceiling** (`RUN_TOKEN_CEILING`) is tracked in `RunState` and
  trips an abort at the next boundary; the **3-iteration hard cap** per file bounds
  worst-case spend independently.
- **Prompt caching** is wired (`cache_control` on the executor's static prefix) and
  cache tokens are recorded per node in Phoenix. Note: it only engages once the
  cached prefix crosses the model's ~1024-token minimum, so it's a no-op on the
  tiny demo repo and active on real targets — not claimed as a demo headline.

**Filesystem ↔ checkpoint consistency.** Only `RunState` is checkpointed, not the
workdir. To keep them aligned, state progress is mirrored into git: the verifier
**commits** the working tree after each passed task, and the executor **resets to
that last commit on entry**. So a crash *mid-executor* (after a partial
`write_file`/`search_replace`) leaves no dirty edits to corrupt the retry — resume
discards the partial attempt and keeps completed-task files intact. See
`src/harness/gitutil.py`.

> Note (LangGraph 1.x): `stream()` yields a step's update *before* its checkpoint
> commits, so the durable checkpoint lags one super-step. The crash demo arms on
> the advancing verifier and exits on the *next* boundary to land on a clean,
> fully-committed state. See `src/cli.py`.

## Sandbox, isolation & rollback

Two layers of containment:

1. **Path-guarding (always on).** The Executor's FS tools resolve every path under
   the run's workdir and reject traversal (`fs_tools.safe_path`). The agent cannot
   read or write outside its own directory.
2. **Container isolation (the test runner).** With `HARNESS_SANDBOX=docker`, the
   verifier runs `pytest`/`ruff` inside an ephemeral container:
   `--network none --user 1000:1000 --read-only --tmpfs /tmp`, only the run's
   workdir mounted at `/work`. Build the image once:

   ```bash
   docker build -f infra/Dockerfile.runner -t harness-runner:latest .
   ```

**Backend selection & security posture.** If `HARNESS_SANDBOX` is unset, the
harness **auto-selects `docker` when the daemon is reachable and the runner image
is built**, else falls back to `local` with a loud warning. Set it explicitly to
force a backend.

| Backend | Test process isolation | When |
|---|---|---|
| `docker` | network-off, non-root, read-only rootfs, only workdir mounted | default when available; required for the real security story |
| `local` | **none** — runs on the host; only the FS *tools* are path-guarded, not the test process | fast, dependency-free fallback for the deterministic demo |

**Per-run isolation** = a fresh clone in a unique dir per `run_id`, one container
per run, nothing shared. That same scoping is the production tenant-isolation
answer: Agent A cannot reach Agent B's filesystem or the network.

**Rollback on abort.** Each workdir is a git repo with a clean baseline commit, so
after the 3-iteration cap trips, the abort node does `git reset --hard` +
`git clean -fd` — every edit (including new files) is discarded, leaving no
partial state. Drive it with the cap-trip switch:

```bash
HARNESS_FORCE_FAIL=1 python -m src.cli run "file://$PWD/test-repo" --run-id demo
# -> 3x fail -> status=aborted -> workdir restored to baseline
```

## Telemetry (Phoenix)

Tracing is opt-in (`--telemetry` flag or `HARNESS_TELEMETRY=1`) and off by default,
so tests stay hermetic. When on, it registers a Phoenix-backed OTel tracer and
auto-instruments the Anthropic SDK. Each run emits:

- one span per node (`planner` / `executor` / `verifier` / `abort` — the abort
  rollback path is now traced too),
- token counts per node (`llm.tokens.input/output` + `cache_read`/`cache_write`,
  accumulated across the executor's tool-use loop), plus the chosen `model` and the
  verifier's one-line `diagnosis` as span attributes, and
- **one span per verification iteration** — so the retry loop stacks visibly.

Run Phoenix locally (no signup), then run with telemetry:

```bash
python -m phoenix.server.main serve         # UI: http://localhost:6006
python -m src.cli run "file://$PWD/test-repo" --run-id demo --telemetry
```

Verified: a forced-abort run produced 20 spans in Phoenix — `planner`×1,
`executor`×3, `verifier`×3 (iteration 0/1/2), plus 13 auto-traced `messages.create`
LLM spans with token usage nested underneath. Query them programmatically with
`phoenix.client.Client(base_url=...).spans.get_spans_dataframe(project_identifier="gusti-harness")`.

## Quick start

**Prerequisites:** Python 3.11+, Git. Docker only if you want the containerized
sandbox (`HARNESS_SANDBOX=docker`) or the `docker compose` boot. You need exactly
**one secret**: `ANTHROPIC_API_KEY`.

```bash
make install                       # venv + editable install + demo deps
# put ANTHROPIC_API_KEY in .env
make run                           # run the harness against test-repo
make test                          # hermetic unit suite (no key/Docker needed)
```

`make help` lists every target. The graded demos map to targets:

| Target | Shows |
|---|---|
| `make demo-run` | clean green run (planner → execute → verify) |
| `make demo-abort` | forced 3-iteration abort + git rollback |
| `make demo-crash` then `make demo-resume` | kill -9 mid-run, then resume (no re-plan, completed file skipped) |
| `make show-checkpoint RUN=demo3` | the persisted checkpoint between crash and resume |

Or run directly:

```bash
uv venv && source .venv/bin/activate && uv pip install -e .
cp .env.example .env               # add ANTHROPIC_API_KEY
python -m src.cli run "file://$PWD/test-repo" --telemetry
```

## Scale path

The *same* harness code runs behind a queue — only the entrypoint changes
(`src/cli.py` → `src/worker.py`). One run = one Redis message = one `thread_id`;
stateless workers pull and execute, and KEDA scales them on queue depth. See
[`infra/architecture.md`](infra/architecture.md) for the diagram and the three
production answers (state/resilience, telemetry, scaling/tenant-isolation).

```bash
docker compose -f infra/docker-compose.yml up          # postgres + redis + phoenix + worker
python -m src.cli enqueue "https://github.com/org/repo" # push a run; a worker drains it
```

## Hosted demo (Railway)

A tiny HTTP trigger (`src/server.py`) lets a grader run the harness from a browser:
`POST /run` (token-gated) refactors the bundled `test-repo` live and returns JSON;
a companion Phoenix service shows the traces. Deploy steps in
[`infra/railway.md`](infra/railway.md).

```bash
curl -X POST "$URL/run?token=$DEMO_TOKEN"                 # clean run  -> status: done
curl -X POST "$URL/run?token=$DEMO_TOKEN&force_fail=true" # abort demo -> status: aborted
```

> Hosted runs use the `local` sandbox (no Docker-in-Docker on Railway); the
> container-isolated path stays available for local / `docker compose`.

## Layout

```
src/harness/      # graph, state, nodes, tools, prompts, telemetry, config
src/worker.py     # queue consumer (horizontal-scale entrypoint)
src/cli.py        # python -m src.cli run <repo_url>  |  enqueue <repo_url>
src/server.py     # FastAPI HTTP trigger for the hosted demo
infra/            # Dockerfile(s), docker-compose, k8s/KEDA, architecture + railway docs
test-repo/        # planted-debt dummy repo for the deterministic demo
```

## Design decisions

- **State recovery:** the run is a typed `RunState` checkpointed by LangGraph after
  each committed super-step, keyed by `thread_id == run_id`. Plan persisted once
  (no re-plan); `current_task_index` advances only on a verified file (completed
  files skipped). SQLite locally, Postgres in prod — same interface.
- **Cost control:** prompt generated once, idempotent per-file advance, and a
  3-iteration hard cap per file that also bounds worst-case token spend.
- **Isolation:** per-run clone in a unique dir + per-run non-root, no-network,
  read-only container; path-guarded FS tools as the always-on first layer.
- **No over-engineering:** one linear graph with a single verifier loop (no
  multi-agent debate); the thousand-run story is shipped as architecture
  (`infra/`), not a running cluster.

## Verified vs. needs-a-box

| Check | Status |
|---|---|
| Vertical slice green, plan→edit→verify | ✅ live |
| Crash + resume (no re-plan, file skipped, workdir re-baselined) | ✅ live |
| Forced 3-iteration abort + git rollback to baseline | ✅ live |
| Per-task git commits + Opus escalation on final retry | ✅ live |
| Verifier Haiku diagnosis feeding retries | ✅ live |
| Telemetry in Phoenix (per-node, per-iteration, tokens, model, cache attrs) | ✅ live |
| Token-ceiling guardrail (`RUN_TOKEN_CEILING` → abort) | ✅ unit-tested |
| Hermetic unit suite (routing, path-guard, rollback, isolation, gitutil) | ✅ 13 passing |
| Containerized sandbox (`HARNESS_SANDBOX=docker`, auto-selected) | ⚙️ wired + command validated; needs Docker daemon |
| `docker compose up` cold-start timing | ⚙️ needs a clean box to time the <15-min claim |
