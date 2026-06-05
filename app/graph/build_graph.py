"""LangGraph orchestrator wiring all agents into a state machine.

Flow:
    clarify ──(needs info)──▶ END (return questions)
        │
        ▼
    retrieve_schema ──▶ generate ──▶ validate
                                        │
                 ┌──────────────────────┼───────────────────────┐
            (errors, retries left)   (valid, auto)          (valid, no auto)
                 ▼                      ▼                        ▼
              repair ──▶ validate    execute ──▶ explain       explain ──▶ END
"""
from __future__ import annotations

from functools import partial

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.clarifier import clarify
from app.agents.deps import Deps
from app.agents.executor import execute
from app.agents.explainer import explain
from app.agents.generator import generate
from app.agents.repair import repair
from app.agents.schema import retrieve_schema
from app.agents.validator import validate
from app.graph.state import GraphState


def _route_after_clarify(state: GraphState) -> str:
    return "ask" if state.status == "clarify" else "continue"


def _route_after_schema(state: GraphState) -> str:
    return "fail" if state.status == "failed" else "continue"


def _route_after_validate(state: GraphState, max_attempts: int) -> str:
    v = state.validation
    if v and v.ok:
        return "execute" if state.auto_execute else "explain"
    if state.attempts < max_attempts:
        return "repair"
    return "explain"


def build_graph(deps: Deps | None = None):
    deps = deps or Deps.create()
    max_attempts = deps.settings.max_repair_attempts

    g = StateGraph(GraphState)
    g.add_node("clarify", partial(clarify, deps=deps))
    g.add_node("retrieve_schema", partial(retrieve_schema, deps=deps))
    g.add_node("generate", partial(generate, deps=deps))
    g.add_node("validate", partial(validate, deps=deps))
    g.add_node("repair", partial(repair, deps=deps))
    g.add_node("execute", partial(execute, deps=deps))
    g.add_node("explain", partial(explain, deps=deps))

    g.add_edge(START, "clarify")
    g.add_conditional_edges(
        "clarify", _route_after_clarify, {"ask": END, "continue": "retrieve_schema"}
    )
    g.add_conditional_edges(
        "retrieve_schema",
        _route_after_schema,
        {"fail": END, "continue": "generate"},
    )
    g.add_edge("generate", "validate")
    g.add_conditional_edges(
        "validate",
        partial(_route_after_validate, max_attempts=max_attempts),
        {"repair": "repair", "execute": "execute", "explain": "explain"},
    )
    g.add_edge("repair", "validate")
    g.add_edge("execute", "explain")
    g.add_edge("explain", END)

    return g.compile(checkpointer=MemorySaver())
