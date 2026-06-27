"""LangGraph wiring — the state machine.

[planner] -> [executor] -> [verifier] --pass--> next file / END
                  ^               |
                  +---retry(<3)---+
                                  |
                            cap(=3) --> [abort] -> END
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from .config import MAX_VERIFIER_ITERATIONS, RUN_TOKEN_CEILING
from .nodes.abort import abort_node
from .nodes.executor import execute_node
from .nodes.planner import plan_node
from .nodes.verifier import verify_node
from .state import RunState


def route_after_verify(state: RunState) -> str:
    # Hard token guardrail: abort at the next boundary if the run overspends.
    if state.get("tokens_spent", 0) >= RUN_TOKEN_CEILING:
        return "abort"
    tasks = state["plan"]["tasks"]
    if state["iteration"] == 0:
        # current file passed and advanced; done if no more tasks
        if state["current_task_index"] >= len(tasks):
            return "done"
        return "next_file"
    if state["iteration"] >= MAX_VERIFIER_ITERATIONS:
        return "abort"
    return "retry"


def build_graph() -> StateGraph:
    g = StateGraph(RunState)
    g.add_node("planner", plan_node)
    g.add_node("executor", execute_node)
    g.add_node("verifier", verify_node)
    g.add_node("abort", abort_node)

    g.set_entry_point("planner")
    g.add_edge("planner", "executor")
    g.add_edge("executor", "verifier")
    g.add_conditional_edges(
        "verifier",
        route_after_verify,
        {
            "retry": "executor",
            "next_file": "executor",
            "abort": "abort",
            "done": END,
        },
    )
    g.add_edge("abort", END)
    return g


def compile_app(checkpointer=None):
    """Compile the graph. Pass a checkpointer for durability (Phase 4)."""
    g = build_graph()
    if checkpointer is not None:
        return g.compile(checkpointer=checkpointer)
    return g.compile()
