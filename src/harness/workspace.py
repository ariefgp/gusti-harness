"""Per-run workspace setup — the unit of isolation.

Each run gets a fresh ephemeral directory containing a clone of the target repo.
A `file://` or local path is `git clone`d if possible (so abort can `git restore`),
falling back to a plain copy for non-git sources. Separate dir per run_id is the
basis of the tenant-isolation story: Agent A cannot see Agent B's filesystem.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import tempfile
from urllib.parse import urlparse


def _local_path(repo_url: str) -> str | None:
    if repo_url.startswith("file://"):
        return urlparse(repo_url).path
    p = pathlib.Path(repo_url)
    if p.exists():
        return str(p)
    return None


def prepare_workdir(repo_url: str, run_id: str) -> str:
    """Create an ephemeral workdir for this run and return its path."""
    base = pathlib.Path(tempfile.gettempdir()) / "gusti-harness" / run_id
    base.mkdir(parents=True, exist_ok=True)
    workdir = base / "repo"
    if workdir.exists():
        return str(workdir)  # idempotent: resume reuses the same workdir

    src = _local_path(repo_url)
    if src and (pathlib.Path(src) / ".git").exists():
        subprocess.run(
            ["git", "clone", "--quiet", src, str(workdir)],
            check=True,
            capture_output=True,
            text=True,
        )
    elif src:
        shutil.copytree(
            src, workdir, ignore=shutil.ignore_patterns(".venv", "__pycache__", ".git")
        )
        _git_baseline(str(workdir))  # so abort can roll back a non-git source
    else:
        # Remote URL — clone over the network.
        subprocess.run(
            ["git", "clone", "--quiet", repo_url, str(workdir)],
            check=True,
            capture_output=True,
            text=True,
        )
    return str(workdir)


def _git(workdir: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", workdir, *args], check=True, capture_output=True, text=True
    )


def _git_baseline(workdir: str) -> None:
    """Init a git repo with one clean commit, so the agent's edits are a working
    tree we can `git reset --hard` back to on abort (the rollback guarantee)."""
    _git(workdir, "init", "--quiet")
    _git(workdir, "-c", "user.email=harness@local", "-c", "user.name=harness",
         "add", "-A")
    _git(workdir, "-c", "user.email=harness@local", "-c", "user.name=harness",
         "commit", "--quiet", "-m", "baseline")
