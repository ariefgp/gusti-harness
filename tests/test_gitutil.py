"""gitutil — the filesystem/checkpoint consistency layer. No API key / Docker.

Proves the two invariants the resume fix relies on:
  - reset_to_head discards a partial/failed attempt but KEEPS committed progress
    (so completed tasks survive a mid-executor crash + resume), and
  - reset_to_baseline throws away everything, including committed progress (abort).
"""

import pathlib
import uuid

from src.harness import gitutil
from src.harness.tools.fs_tools import write_file
from src.harness.workspace import prepare_workdir

REPO = "file://" + str(pathlib.Path(__file__).resolve().parent.parent / "test-repo")


def _fresh() -> str:
    return prepare_workdir(REPO, "test-" + uuid.uuid4().hex[:8])


def test_reset_to_head_keeps_committed_progress_drops_partial():
    wd = _fresh()
    # Task 0 "passes": create a file and commit it as progress.
    write_file(wd, "app/schemas.py", "MODELS = 1\n")
    gitutil.commit_progress(wd, "task 0")
    # Task 1 starts and crashes mid-edit (uncommitted partial work).
    write_file(wd, "app/schemas.py", "MODELS = 1\nPARTIAL = 2\n")
    write_file(wd, "app/half_written.py", "oops\n")

    gitutil.reset_to_head(wd)  # what the executor does on (re-)entry

    # Committed task-0 progress survives; partial task-1 edits are gone.
    assert (pathlib.Path(wd) / "app" / "schemas.py").read_text() == "MODELS = 1\n"
    assert not (pathlib.Path(wd) / "app" / "half_written.py").exists()


def test_reset_to_baseline_discards_even_committed_progress():
    wd = _fresh()
    write_file(wd, "app/schemas.py", "MODELS = 1\n")
    gitutil.commit_progress(wd, "task 0")

    gitutil.reset_to_baseline(wd)  # what abort does

    assert not (pathlib.Path(wd) / "app" / "schemas.py").exists()
