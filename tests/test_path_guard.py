"""Path-guard tests — the always-on first isolation layer. No API key required."""

import pathlib
import tempfile

import pytest

from src.harness.tools.fs_tools import read_file, safe_path, write_file


def test_allows_paths_inside_workdir():
    wd = tempfile.mkdtemp()
    root = str(pathlib.Path(wd).resolve())  # macOS: /var -> /private/var
    assert safe_path(wd, "app/main.py").startswith(root)


def test_blocks_parent_traversal():
    wd = tempfile.mkdtemp()
    with pytest.raises(PermissionError):
        safe_path(wd, "../../etc/passwd")


def test_blocks_absolute_escape():
    wd = tempfile.mkdtemp()
    with pytest.raises(PermissionError):
        safe_path(wd, "/etc/passwd")


def test_write_then_read_roundtrip():
    wd = tempfile.mkdtemp()
    write_file(wd, "pkg/x.py", "print('hi')\n")
    assert read_file(wd, "pkg/x.py") == "print('hi')\n"
