"""Env, the Anthropic client, model routing, prompt loading, and guardrails.

Model routing (per the build plan):
  - Planner:  Sonnet — structure, not depth.
  - Executor: Sonnet by default; Opus only for genuinely hard files.
  - Verifier diagnosis: Haiku is plenty.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

# --- Model routing -----------------------------------------------------------
# Latest Claude model IDs (knowledge cutoff Jan 2026).
MODEL_PLANNER = os.getenv("MODEL_PLANNER", "claude-sonnet-4-6")
MODEL_EXECUTOR = os.getenv("MODEL_EXECUTOR", "claude-sonnet-4-6")
MODEL_EXECUTOR_HARD = os.getenv("MODEL_EXECUTOR_HARD", "claude-opus-4-8")
MODEL_VERIFIER = os.getenv("MODEL_VERIFIER", "claude-haiku-4-5-20251001")

# --- Guardrails --------------------------------------------------------------
MAX_VERIFIER_ITERATIONS = int(os.getenv("MAX_VERIFIER_ITERATIONS", "3"))
RUN_TOKEN_CEILING = int(os.getenv("RUN_TOKEN_CEILING", "500000"))
SANDBOX_TIMEOUT_S = int(os.getenv("SANDBOX_TIMEOUT_S", "120"))


@lru_cache(maxsize=1)
def get_client() -> anthropic.Anthropic:
    """Lazily construct a shared Anthropic client.

    Lazy so importing this module never requires the key (tests, planning, etc.).
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add it."
        )
    return anthropic.Anthropic(api_key=key)


_PROMPT_DIR = Path(__file__).parent / "prompts"


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Load a system prompt by stem (e.g. 'planner' -> prompts/planner.md)."""
    path = _PROMPT_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")
