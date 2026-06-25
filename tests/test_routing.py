"""Deterministic tests for the verifier routing — no API key required."""

from src.harness.config import MAX_VERIFIER_ITERATIONS
from src.harness.graph import route_after_verify


def _state(iteration, index, n_tasks):
    return {
        "plan": {"tasks": [{} for _ in range(n_tasks)]},
        "iteration": iteration,
        "current_task_index": index,
    }


def test_pass_advances_to_next_file():
    assert route_after_verify(_state(iteration=0, index=1, n_tasks=2)) == "next_file"


def test_pass_on_last_file_is_done():
    assert route_after_verify(_state(iteration=0, index=2, n_tasks=2)) == "done"


def test_failure_under_cap_retries():
    assert route_after_verify(_state(iteration=1, index=0, n_tasks=2)) == "retry"


def test_failure_at_cap_aborts():
    s = _state(iteration=MAX_VERIFIER_ITERATIONS, index=0, n_tasks=2)
    assert route_after_verify(s) == "abort"
