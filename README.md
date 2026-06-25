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

## Quick start

```bash
uv venv && source .venv/bin/activate
uv pip install -e .
cp .env.example .env   # add ANTHROPIC_API_KEY
```

You need exactly one secret: `ANTHROPIC_API_KEY`.

## Layout

```
src/harness/      # graph, state, nodes, tools, prompts, telemetry, config
src/worker.py     # queue consumer (horizontal-scale entrypoint)
src/cli.py        # python -m src.cli run <repo_url>
infra/            # Dockerfile, docker-compose, k8s/KEDA sketch, architecture brief
test-repo/        # planted-debt dummy repo for the deterministic demo
```
