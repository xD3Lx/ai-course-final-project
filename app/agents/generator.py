"""SQL Generator agent — produce a Databricks SQL statement from intent + schema."""
from __future__ import annotations

from app.agents.deps import Deps
from app.graph.state import GraphState
from app.llm.models import GeneratedSQL
from app.llm.prompts import GENERATOR
from app.tools.sqlglot_check import ensure_limit


def generate(state: GraphState, deps: Deps) -> dict:
    request = state.refined_request or state.user_request
    schema_text = "\n".join(t.rendered for t in state.schema_context)

    out = deps.llm.complete_json(
        role="generator",
        system=GENERATOR,
        user=f"Request: {request}\n\nAvailable tables and columns:\n{schema_text}",
        schema=GeneratedSQL,
    )

    sql = out.sql.strip().rstrip(";")
    if deps.settings.read_only:
        sql = ensure_limit(sql, deps.settings.result_row_limit)
    return {"sql": sql}
