# The harness app image: serves the HTTP demo trigger (src/server.py) and can also
# run the queue worker (src/worker.py) or the CLI. Distinct from
# infra/Dockerfile.runner, which is the sandboxed test-runner the verifier launches
# per run when HARNESS_SANDBOX=docker.
FROM python:3.11-slim

# git is needed for per-run clone/rollback.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
# Bundle the dummy target repo so the hosted demo has something to refactor.
COPY test-repo ./test-repo
# [deploy] adds FastAPI/uvicorn + the runtime deps the bundled test-repo's pytest
# suite needs, so the local-sandbox verifier can run inside this image.
RUN pip install --no-cache-dir -e ".[deploy]"

# Default to the HTTP demo server; Railway overrides $PORT. Override the command
# to run the worker (`python -m src.worker`) or CLI instead.
ENV PORT=8000
CMD ["sh", "-c", "uvicorn src.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
