# test-repo — planted-debt demo target

A minimal FastAPI service with **two endpoints that lack input validation**
(`POST /users`, `POST /orders`). The accompanying pytest suite expects malformed
payloads to return `422`, so it **fails out of the box**. This is the deterministic
target the harness refactors on camera.

The intended fix is multi-file: add a `app/schemas.py` with Pydantic models and
type the handlers in `app/main.py` to use them — giving the planner a real
dependency graph (schema → handler) and the executor a chance to self-correct
(e.g. forgetting the import on the first pass).

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest            # expect FAILURES until validation is added
```
