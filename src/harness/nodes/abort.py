"""Abort node — hit when a file fails the verifier cap. Rolls back and reports.

Rollback is cheap and total because each run operates on its own dedicated clone
with a clean baseline commit: `git reset --hard` + `git clean -fd` discards every
edit the agent made, leaving no partial state. If the workdir somehow isn't a git
repo, we still mark the run aborted (the ephemeral dir can just be deleted).
"""

from __future__ import annotations

import subprocess

from ..state import RunState


def _git(workdir: str, *args: str) -> None:
    subprocess.run(
        ["git", "-C", workdir, *args], capture_output=True, text=True, timeout=30
    )


def abort_node(state: RunState) -> dict:
    workdir = state["workdir"]
    try:
        _git(workdir, "reset", "--hard")  # discard tracked-file edits
        _git(workdir, "clean", "-fd")  # remove any new files (e.g. schemas.py)
    except Exception:
        pass  # not a git workdir; ephemeral dir will be discarded
    return {"status": "aborted"}
