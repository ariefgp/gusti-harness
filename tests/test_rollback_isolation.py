"""Rollback + per-run isolation — the cheap, always-on half of the security story.

No API key and no Docker required: exercises the git baseline, abort rollback, and
separate-dir-per-run guarantee directly.
"""

import pathlib
import uuid

from src.harness.nodes.abort import abort_node
from src.harness.tools.fs_tools import write_file
from src.harness.workspace import prepare_workdir

REPO = "file://" + str(pathlib.Path(__file__).resolve().parent.parent / "test-repo")


def _fresh_run() -> tuple[str, str]:
    run_id = "test-" + uuid.uuid4().hex[:8]
    return run_id, prepare_workdir(REPO, run_id)


def test_workdir_has_git_baseline():
    _, wd = _fresh_run()
    assert (pathlib.Path(wd) / ".git").exists()


def test_abort_rolls_back_new_and_edited_files():
    _, wd = _fresh_run()
    # Agent-style mutations: a brand-new file and an edit to an existing one.
    write_file(wd, "app/schemas.py", "JUNK = 1\n")
    write_file(wd, "app/main.py", "# clobbered\n")

    abort_node({"workdir": wd})

    assert not (pathlib.Path(wd) / "app" / "schemas.py").exists()  # new file removed
    assert "# clobbered" not in (pathlib.Path(wd) / "app" / "main.py").read_text()


def test_runs_are_isolated_from_each_other():
    _, wd_a = _fresh_run()
    _, wd_b = _fresh_run()
    assert wd_a != wd_b
    write_file(wd_a, "secret.txt", "agent A only\n")
    assert not (pathlib.Path(wd_b) / "secret.txt").exists()  # B can't see A's FS
