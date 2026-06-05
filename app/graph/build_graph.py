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

import logging
import time
from functools import partial
from typing import Callable

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
from app.graph.state import AgentStep, GraphState

logger = logging.getLogger("nl2databricks.graph")


def _summarize(name: str, update: dict, state: GraphState) -> tuple[str, bool]:
    """Build a short human-readable summary of what an agent just did."""
    if name == "clarify":
        if update.get("status") == "clarify":
            n = len(update.get("pending_questions", []))
            return f"Needs clarification — asked {n} question(s)", True
        return f"Intent understood: {update.get('refined_request', '')[:80]}", True
    if name == "retrieve_schema":
        if update.get("status") == "failed":
            return update.get("error", "schema retrieval failed"), False
        tables = [t.fqn for t in update.get("schema_context", [])]
        return f"Selected {len(tables)} table(s): {', '.join(tables)}", True
    if name == "generate":
        return "Generated candidate SQL", True
    if name == "validate":
        v = update.get("validation")
        if v and v.ok:
            return "Validation passed (syntax + schema + EXPLAIN)", True
        errs = v.errors if v else []
        return f"Found {len(errs)} issue(s): {'; '.join(errs)[:120]}", False
    if name == "repair":
        return f"Repaired SQL (attempt {update.get('attempts', '?')})", True
    if name == "execute":
        r = update.get("result")
        if update.get("status") == "failed":
            return update.get("error", "execution failed"), False
        n = len(r.rows) if r else 0
        return f"Executed query — {n} row(s) returned", True
    if name == "explain":
        return f"Finished with status: {update.get('status', '?')}", True
    return name, True


def _traced(name: str, fn: Callable[[GraphState], dict]) -> Callable[[GraphState], dict]:
    """Wrap a node so it records a timed AgentStep into the shared trace."""

    def wrapped(state: GraphState) -> dict:
        t0 = time.perf_counter()
        update = dict(fn(state))
        dt = (time.perf_counter() - t0) * 1000.0
        summary, ok = _summarize(name, update, state)
        logger.info("[%s] %s (%.0f ms)", name, summary, dt)
        update["trace"] = [
            AgentStep(agent=name, summary=summary, duration_ms=round(dt, 1), ok=ok)
        ]
        return update

    return wrapped


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
    g.add_node("clarify", _traced("clarify", partial(clarify, deps=deps)))
    g.add_node(
        "retrieve_schema",
        _traced("retrieve_schema", partial(retrieve_schema, deps=deps)),
    )
    g.add_node("generate", _traced("generate", partial(generate, deps=deps)))
    g.add_node("validate", _traced("validate", partial(validate, deps=deps)))
    g.add_node("repair", _traced("repair", partial(repair, deps=deps)))
    g.add_node("execute", _traced("execute", partial(execute, deps=deps)))
    g.add_node("explain", _traced("explain", partial(explain, deps=deps)))

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
