from typing import Any

from langgraph.graph import END, START, StateGraph

from src.agent.nodes.code_generator import generate_code_node
from src.agent.nodes.sandbox_executor import execute_sandbox_node
from src.agent.state import AgentState
from src.agent.utils.ast_checker import (
    AssertionTamperedError,
    assertion_hashes,
    extract_asserts,
    verify_assertions_unchanged,
)


def record_assertions_node(state: AgentState) -> dict[str, Any]:
    """After first code generation, snapshot assertion hashes into state.

    Subsequent regenerations (e.g. self-heal) must not overwrite the baseline.
    """
    if state.get("original_assertions"):
        return {}

    code = state.get("generated_code") or ""
    if not code.strip():
        return {"original_assertions": []}

    return {"original_assertions": assertion_hashes(code)}


def verify_assertions_node(state: AgentState) -> dict[str, Any]:
    """Force assertion integrity check before sandbox (and after any self-heal).

    Raises AssertionTamperedError to stop graph flow when asserts were weakened.
    """
    original = state.get("original_assertions") or []
    code = state.get("generated_code") or ""
    # First-pass with empty baseline is a no-op until record_assertions runs.
    if not original:
        return {}
    verify_assertions_unchanged(original, code)
    return {}


builder = StateGraph(AgentState)
builder.add_node("generate_code", generate_code_node)
builder.add_node("record_assertions", record_assertions_node)
builder.add_node("verify_assertions", verify_assertions_node)
builder.add_node("execute_sandbox", execute_sandbox_node)
builder.add_edge(START, "generate_code")
builder.add_edge("generate_code", "record_assertions")
builder.add_edge("record_assertions", "verify_assertions")
builder.add_edge("verify_assertions", "execute_sandbox")
builder.add_edge("execute_sandbox", END)

app_graph = builder.compile()

__all__ = [
    "app_graph",
    "builder",
    "record_assertions_node",
    "verify_assertions_node",
    "AssertionTamperedError",
]
