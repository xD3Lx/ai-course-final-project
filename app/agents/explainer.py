"""Explainer agent — plain-language summary of the final SQL and result."""
from __future__ import annotations

from app.agents.deps import Deps
from app.graph.state import GraphState


def explain(state: GraphState, deps: Deps) -> dict:
    valid = state.validation and state.validation.ok

    preview = ""
    if state.result and state.result.rows:
        head = state.result.rows[:3]
        preview = f"\nColumns: {state.result.columns}\nSample rows: {head}"

    user = (
        f"Request: {state.refined_request or state.user_request}\n\n"
        f"Final SQL:\n{state.sql}{preview}"
    )
    try:
        text = deps.llm.complete(
            role="explainer",
            system=(
                "Explain what THIS specific query does and what its result shows, "
                "in 2-4 short sentences. Do NOT explain what SQL is in general, do "
                "not define SQL or databases, and do not add any preamble or "
                "analogies (e.g. 'SQL is a special language...'). Start directly "
                "with what the query returns."
            ),
            user=user,
        )
    except Exception:  # noqa: BLE001 - explanation is non-critical
        text = "Generated a Databricks SQL query for your request."

    status = "done" if valid else "failed"
    error = state.error
    if not valid and not error:
        errs = state.validation.errors if state.validation else []
        error = "Could not produce a valid query: " + "; ".join(errs)

    return {"explanation": text, "status": status, "error": error}
