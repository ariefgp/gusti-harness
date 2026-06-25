# The harness/worker image (distinct from infra/Dockerfile.runner, which is the
# sandboxed test-runner the verifier launches per run).
FROM python:3.11-slim

# git is needed for per-run clone/rollback.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e .

# Default entrypoint is the queue worker; override to run the CLI.
CMD ["python", "-m", "src.worker"]
