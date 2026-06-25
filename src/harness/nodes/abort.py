"""Abort node — hit when a file fails the verifier cap. Rolls back and reports.

Rollback is cheap because each run edits its own dedicated clone: discard the
working-tree changes with git, leaving no partial state. If the workdir is not a
git repo (e.g. a plain copy in the local demo), we just mark the run aborted.
"""

from __future__ import annotations

import subprocess

from ..state import RunState


def abort_node(state: RunState) -> dict:
    workdir = state["workdir"]
    try:
        subprocess.run(
            ["git", "-C", workdir, "checkout", "--", "."],
            capture_output=True,
            text=True,
            timeout=30,
        )
        subprocess.run(
            ["git", "-C", workdir, "clean", "-fd"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        pass  # plain-copy workdir; nothing to roll back
    return {"status": "aborted"}
