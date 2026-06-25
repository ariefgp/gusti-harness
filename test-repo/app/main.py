"""Planted debt: endpoints WITHOUT input validation.

Both handlers read raw JSON and index into it directly, so a malformed payload
raises a KeyError / TypeError instead of returning a clean 422. The harness's job
is to introduce Pydantic models (a new `schemas.py`) and type the handlers so bad
payloads are rejected at the boundary.
"""

from fastapi import FastAPI, Request

app = FastAPI()


@app.post("/users")
async def create_user(request: Request):
    body = await request.json()
    # No validation: missing "email"/"age" → KeyError, wrong type → unhandled.
    return {"created": body["email"], "age": body["age"]}


@app.post("/orders")
async def create_order(request: Request):
    body = await request.json()
    # No validation: quantity should be a positive int; nothing enforces it.
    return {"item": body["item"], "quantity": body["quantity"]}
