"""Repair agent — fix SQL using validator feedback, then loop back to validate."""
from __future__ import annotations

from app.agents.deps import Deps
from app.graph.state import GraphState
from app.llm.models import RepairedSQL
from app.llm.prompts import REPAIR
from app.tools.sqlglot_check import ensure_limit


def repair(state: GraphState, deps: Deps) -> dict:
    errors = state.validation.errors if state.validation else ["unknown error"]
    schema_text = "\n".join(t.rendered for t in state.schema_context)
    user = (
        f"Original request: {state.refined_request or state.user_request}\n\n"
        f"Current SQL:\n{state.sql}\n\n"
        f"Validation errors:\n" + "\n".join(f"- {e}" for e in errors) + "\n\n"
        f"Schema:\n{schema_text}"
    )

    out = deps.llm.complete_json(
        role="repair",
        system=REPAIR,
        user=user,
        schema=RepairedSQL,
    )

    sql = out.sql.strip().rstrip(";")
    if deps.settings.read_only:
        sql = ensure_limit(sql, deps.settings.result_row_limit)
    return {"sql": sql, "attempts": state.attempts + 1}
