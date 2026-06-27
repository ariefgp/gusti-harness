"""Git helpers that keep the workdir filesystem consistent with the checkpoint.

The problem this solves: LangGraph checkpoints `RunState`, NOT the workdir
filesystem. So we mirror state progress into git:

  - `init_baseline()` tags the pristine repo as `harness-baseline`.
  - After a file passes verification, the verifier `commit_progress()`s the
    working tree — so each durable RunState checkpoint has a matching git commit.
  - On entering the executor (fresh attempt, retry, or *resume after a crash*),
    `reset_to_head()` discards any partial/failed edits, so the agent always
    starts from the last known-good filesystem state. This closes the
    "crash mid-executor leaves a dirty workdir" gap and makes `search_replace`
    deterministic on retry.
  - On abort, `reset_to_baseline()` throws away every edit back to pristine.
"""

from __future__ import annotations

import subprocess

BASELINE_TAG = "harness-baseline"
_IDENT = ["-c", "user.email=harness@local", "-c", "user.name=harness"]


def _git(workdir: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", workdir, *args],
        check=check,
        capture_output=True,
        text=True,
        timeout=30,
    )


def is_git_repo(workdir: str) -> bool:
    return _git(workdir, "rev-parse", "--git-dir", check=False).returncode == 0


def init_baseline(workdir: str) -> None:
    """Ensure the workdir is a git repo with a clean baseline commit + tag.

    Idempotent: a cloned source already has history, so we just (re)tag HEAD.
    A plain-copy source is initialised and committed first.
    """
    if not is_git_repo(workdir):
        _git(workdir, "init", "--quiet")
        _git(workdir, *_IDENT, "add", "-A")
        _git(workdir, *_IDENT, "commit", "--quiet", "-m", "baseline")
    # (Re)point the baseline tag at the current HEAD.
    _git(workdir, "tag", "-f", BASELINE_TAG, check=False)


def commit_progress(workdir: str, message: str) -> None:
    """Commit the working tree so a passed task has a durable filesystem snapshot."""
    _git(workdir, *_IDENT, "add", "-A", check=False)
    _git(workdir, *_IDENT, "commit", "--quiet", "--allow-empty", "-m", message, check=False)


def reset_to_head(workdir: str) -> None:
    """Discard uncommitted edits (partial/failed attempt) back to the last commit."""
    _git(workdir, "reset", "--hard", "--quiet", check=False)
    _git(workdir, "clean", "-fdq", check=False)


def reset_to_baseline(workdir: str) -> None:
    """Roll the workdir all the way back to the pristine baseline (abort)."""
    _git(workdir, "reset", "--hard", "--quiet", BASELINE_TAG, check=False)
    _git(workdir, "clean", "-fdq", check=False)
