"""Path-guarded filesystem tools exposed to the Executor via Anthropic tool-use.

Every path is resolved and checked to be inside the run's `workdir`, so the agent
cannot read or write outside its sandbox dir. This is the cheap, always-on layer;
container isolation (sandbox.py) is the second layer for the test runner.
"""

from __future__ import annotations

import pathlib


def safe_path(workdir: str, rel: str) -> str:
    """Resolve `rel` under `workdir`, blocking path traversal. Returns abs path."""
    root = pathlib.Path(workdir).resolve()
    full = (root / rel).resolve()
    if full != root and root not in full.parents:
        raise PermissionError(f"path traversal blocked: {rel!r}")
    return str(full)


def read_file(workdir: str, path: str) -> str:
    full = safe_path(workdir, path)
    p = pathlib.Path(full)
    if not p.exists():
        return f"<file does not exist: {path}>"
    return p.read_text(encoding="utf-8")


def write_file(workdir: str, path: str, content: str) -> str:
    full = safe_path(workdir, path)
    p = pathlib.Path(full)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} bytes to {path}"


def search_replace(workdir: str, path: str, search: str, replace: str) -> str:
    full = safe_path(workdir, path)
    p = pathlib.Path(full)
    text = p.read_text(encoding="utf-8")
    if search not in text:
        raise ValueError(f"search string not found in {path}")
    p.write_text(text.replace(search, replace, 1), encoding="utf-8")
    return f"replaced 1 occurrence in {path}"


# --- Anthropic tool schemas --------------------------------------------------

READ_FILE_TOOL = {
    "name": "read_file",
    "description": "Read a UTF-8 text file relative to the working directory.",
    "input_schema": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
}

WRITE_FILE_TOOL = {
    "name": "write_file",
    "description": "Create or overwrite a file (relative path) with the given content.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    },
}

SEARCH_REPLACE_TOOL = {
    "name": "search_replace",
    "description": "Replace the first occurrence of an exact substring in a file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "search": {"type": "string"},
            "replace": {"type": "string"},
        },
        "required": ["path", "search", "replace"],
    },
}

EXECUTOR_TOOLS = [READ_FILE_TOOL, WRITE_FILE_TOOL, SEARCH_REPLACE_TOOL]

_DISPATCH = {
    "read_file": read_file,
    "write_file": write_file,
    "search_replace": search_replace,
}


def dispatch_tool(name: str, workdir: str, tool_input: dict) -> str:
    """Run a tool call by name against `workdir`. Returns a string result."""
    fn = _DISPATCH.get(name)
    if fn is None:
        raise ValueError(f"unknown tool: {name}")
    return fn(workdir, **tool_input)
