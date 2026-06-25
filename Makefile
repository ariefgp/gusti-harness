# Convenience targets for the harness. The cold-start path is: install -> add key
# -> run (or `compose-up`). See README for the under-15-min story.

PY ?= ./.venv/bin/python
REPO ?= file://$(PWD)/test-repo
TMP := $(if $(TMPDIR),$(TMPDIR),/tmp)/gusti-harness

.PHONY: help install test run phoenix \
        demo-run demo-abort demo-crash demo-resume show-checkpoint \
        docker-runner compose-up clean

help:
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  %-16s %s\n", $$1, $$2}'

install: ## Create venv and install the harness (editable) + demo deps
	python3 -m venv .venv
	$(PY) -m pip install -q -e . fastapi httpx pytest ruff
	cp -n .env.example .env || true
	@echo "Now put ANTHROPIC_API_KEY in .env"

test: ## Run the hermetic unit suite (no API key / Docker needed)
	$(PY) -m pytest tests/ -q

phoenix: ## Launch the local Phoenix telemetry UI (http://localhost:6006)
	$(PY) -m phoenix.server.main serve

run: ## Run the harness against REPO (default: test-repo)
	$(PY) -m src.cli run "$(REPO)" --telemetry

# --- demo takes (see DEMO_SCRIPT.md) ----------------------------------------
demo-run: ## Take 1: clean green run
	$(PY) -m src.cli run "$(REPO)" --run-id demo1 --telemetry

demo-abort: ## Take 2: forced 3-iteration abort + rollback
	HARNESS_FORCE_FAIL=1 $(PY) -m src.cli run "$(REPO)" --run-id demo2 --telemetry

demo-crash: ## Take 3a: run that hard-exits after task 0 is checkpointed
	HARNESS_CRASH_AFTER_TASK=1 $(PY) -m src.cli run "$(REPO)" --run-id demo3 --telemetry

demo-resume: ## Take 3b: resume the crashed run (planner + task 0 skipped)
	$(PY) -m src.cli run "$(REPO)" --run-id demo3 --telemetry

show-checkpoint: ## Print the persisted checkpoint for RUN=<run_id>
	@$(PY) -c "from src.harness.checkpoint import make_checkpointer; \
from src.harness.graph import compile_app; \
g=compile_app(checkpointer=make_checkpointer()); \
v=g.get_state({'configurable':{'thread_id':'$(RUN)'}}).values; \
print('current_task_index:', v.get('current_task_index'), '| status:', v.get('status')); \
print('plan persisted:', v.get('plan') is not None); \
print('feedback:', [(f['iteration'], f['passed']) for f in v.get('feedback', [])])"

# --- infra ------------------------------------------------------------------
docker-runner: ## Build the sandboxed test-runner image
	docker build -f infra/Dockerfile.runner -t harness-runner:latest .

compose-up: ## Boot postgres + redis + phoenix + worker
	docker compose -f infra/docker-compose.yml up

clean: ## Wipe local checkpoints and per-run temp workdirs
	rm -f checkpoints.db
	rm -rf "$(TMP)"
	@echo "cleaned checkpoints.db and $(TMP)"
