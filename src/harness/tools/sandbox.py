"""Test-runner sandbox + per-run isolation.

Two execution backends, selected by `HARNESS_SANDBOX`:
  - "local"  (default): run the command in the workdir via subprocess. Fast and
    dependency-free — used for the deterministic vertical-slice demo.
  - "docker": run inside an ephemeral, non-root, no-network container with only
    the workdir mounted. This is the real tenant-isolation story for production.

Path-guarding of FS tools (fs_tools.safe_path) is the always-on first layer;
this module is the second layer for the actually-executed test process.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from dataclasses import dataclass

from ..config import SANDBOX_TIMEOUT_S

RUNNER_IMAGE = os.getenv("HARNESS_RUNNER_IMAGE", "harness-runner:latest")


@dataclass
class Result:
    ok: bool
    out: str
    err: str


def _run_local(workdir: str, cmd: str) -> Result:
    # Ensure bare `python`/`ruff` in the command resolve to the harness venv,
    # which isn't "activated" in a bare subprocess.
    env = dict(os.environ)
    bindir = os.path.dirname(sys.executable)
    env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
    p = subprocess.run(
        cmd,
        shell=True,
        cwd=workdir,
        capture_output=True,
        text=True,
        timeout=SANDBOX_TIMEOUT_S,
        env=env,
    )
    return Result(ok=p.returncode == 0, out=p.stdout, err=p.stderr)


def _run_docker(workdir: str, cmd: str) -> Result:
    # non-root, no network, read-only rootfs, workdir mounted rw at /work.
    docker = (
        f"docker run --rm --network none --user 1000:1000 "
        f"--read-only --tmpfs /tmp "
        f"-v {shlex.quote(workdir)}:/work -w /work "
        f"{shlex.quote(RUNNER_IMAGE)} bash -lc {shlex.quote(cmd)}"
    )
    p = subprocess.run(
        docker, shell=True, capture_output=True, text=True, timeout=SANDBOX_TIMEOUT_S
    )
    return Result(ok=p.returncode == 0, out=p.stdout, err=p.stderr)


def run_in_sandbox(workdir: str, cmd: str) -> Result:
    backend = os.getenv("HARNESS_SANDBOX", "local").lower()
    if backend == "docker":
        return _run_docker(workdir, cmd)
    return _run_local(workdir, cmd)
