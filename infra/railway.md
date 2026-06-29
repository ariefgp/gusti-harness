# Deploying the hosted demo to Railway

The hosted demo is an HTTP trigger (`src/server.py`) plus a public Phoenix UI for
traces. A grader opens the URL, `POST /run` (token-gated), and watches the harness
refactor the bundled `test-repo` live; traces show up in Phoenix.

> Hosted caveat: Railway has no Docker-in-Docker, so runs use the `local` sandbox
> (filesystem path-guarded, not container-isolated). The container-isolated path
> stays available for local / `docker compose`. This is stated on the demo's `/` page.

## Services

Two services in one Railway project:

1. **web** — this repo (Dockerfile `infra/Dockerfile`). Serves the trigger on `$PORT`.
2. **phoenix** — the public `arizephoenix/phoenix` image. Trace UI on 6006, OTLP
   gRPC collector on 4317.

(No Redis/Postgres needed: the demo runs synchronously, not via the queue. The
queue/worker + KEDA path is the documented *scale* story in `src/worker.py` and
`infra/k8s/`.)

## Steps

### 1. Create the project + web service
```bash
# In the repo root:
railway login
railway init                     # create a new project
railway up                       # build & deploy using railway.json -> infra/Dockerfile
```
Or via the dashboard: New Project → Deploy from GitHub repo → pick this repo.
Railway reads `railway.json` (Dockerfile build, start command, `/healthz` check).

### 2. Add the Phoenix service
Dashboard → the project → New → Deploy a Docker image → `arizephoenix/phoenix:latest`.
- Networking: give it a public domain (exposes the UI). Set the exposed/target
  port to `6006`.
- It listens on `4317` (OTLP gRPC) for traces over the private network.

### 3. Set environment variables on the **web** service
| Variable | Value | Why |
|---|---|---|
| `ANTHROPIC_API_KEY` | your key | the one required secret |
| `DEMO_TOKEN` | a long random string | gates `POST /run` so the URL can't drain the key |
| `HARNESS_TELEMETRY` | `1` | emit traces |
| `PHOENIX_ENDPOINT` | `http://phoenix.railway.internal:4317` | private-network OTLP target |
| `PHOENIX_PUBLIC_URL` | the phoenix public domain | shown on the info page so graders can click to traces |

`phoenix.railway.internal` is Railway's private DNS for the service named `phoenix`
(rename to match if you named it differently).

### 4. Test it
```bash
URL=https://<your-web-domain>
curl "$URL/healthz"                                   # {"ok":true}
curl -X POST "$URL/run?token=$DEMO_TOKEN"             # clean run -> status: done
curl -X POST "$URL/run?token=$DEMO_TOKEN&force_fail=true"  # abort demo -> status: aborted
```
Open `PHOENIX_PUBLIC_URL` to see the per-node spans and the stacked verifier loop.

## Submission note
Put the web URL **and** the `DEMO_TOKEN` in your submission so the grader can run it.
Each run spends Anthropic tokens (~25k/run on the demo repo); runs are serialized
(one at a time) and token-gated.
