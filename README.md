# gusti-harness

A production agent harness for **multi-file refactoring**. It runs a nearly-linear
state machine — **Planner → Executor → Verifier** with a single self-loop on the
Verifier — to apply a focused refactor across the files of a repo, verify each
change in an isolated sandbox, and self-correct on failure.

**Niche:** add input validation to API endpoints that lack it (router → handler →
schema). Naturally multi-file, trivially testable (bad payload → expect `422`),
and the failure path self-corrects in a way that exercises the verifier loop.

> Status: scaffolding in place (Phase 0–1). Build order tracked in the internal
> guide; see `git log` for progress.

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

**Cost-on-resume controls:**
- The **plan is generated once** and persisted, so the Planner never re-runs.
- `current_task_index` advances only after a file passes verification, so resume
  **skips completed files** — no duplicate edits, no duplicate tokens.
- The **3-iteration hard cap** per file bounds worst-case token spend (→ abort).

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

   The default `HARNESS_SANDBOX=local` runs the command in-process (fast,
   dependency-free) for the deterministic demo.

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

- one span per node (`planner` / `executor` / `verifier` / `abort`),
- token counts per node (`llm.tokens.input/output`, accumulated across the
  executor's tool-use loop), and
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

```bash
uv venv && source .venv/bin/activate
uv pip install -e .
cp .env.example .env   # add ANTHROPIC_API_KEY
```

You need exactly one secret: `ANTHROPIC_API_KEY`.

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

## Layout

```
src/harness/      # graph, state, nodes, tools, prompts, telemetry, config
src/worker.py     # queue consumer (horizontal-scale entrypoint)
src/cli.py        # python -m src.cli run <repo_url>  |  enqueue <repo_url>
infra/            # Dockerfile, docker-compose, k8s/KEDA sketch, architecture brief
test-repo/        # planted-debt dummy repo for the deterministic demo
```
