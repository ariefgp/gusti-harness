"""Typed run state — this is what gets checkpointed.

Get this right and crash-resume mostly falls out:
- `plan` is generated ONCE and persisted, so resume never re-runs the Planner.
- `current_task_index` advances only after a file passes verification, so
  resume skips completed files (no duplicate edits, no duplicate cost).
"""

from typing import Literal, Optional, TypedDict

from pydantic import BaseModel


class FileTask(BaseModel):
    path: str
    action: str  # e.g. "add_pydantic_validation"
    depends_on: list[str] = []
    status: Literal["pending", "done", "failed"] = "pending"


class Plan(BaseModel):
    tasks: list[FileTask]  # dependency-ordered


class VerifierFeedback(BaseModel):
    iteration: int
    passed: bool
    stdout: str
    stderr: str


class RunState(TypedDict):
    repo_url: str
    workdir: str  # ephemeral clone path for THIS run
    plan: Optional[dict]  # serialized Plan — generated ONCE
    current_task_index: int
    iteration: int  # verifier retries for current file (0..3)
    feedback: list[dict]  # VerifierFeedback history
    status: Literal["planning", "executing", "verifying", "done", "aborted"]
