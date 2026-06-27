"""Abort node — hit when a file fails the verifier cap (or the token ceiling).

Rollback is total: each run operates on its own clone with a tagged baseline, so
`reset_to_baseline` (`git reset --hard harness-baseline` + `git clean -fd`)
discards every edit the agent made — including completed-task commits — leaving no
partial state. Traced so the rollback path is visible in Phoenix.
"""

from __future__ import annotations

from .. import gitutil
from ..state import RunState
from ..telemetry import span


def abort_node(state: RunState) -> dict:
    with span("abort"):
        try:
            gitutil.reset_to_baseline(state["workdir"])
        except Exception:
            pass  # not a git workdir; the ephemeral dir will be discarded
        return {"status": "aborted"}
