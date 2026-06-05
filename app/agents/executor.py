"""Executor agent — run the validated, row-limited query against Databricks."""
from __future__ import annotations

from app.agents.deps import Deps
from app.graph.state import GraphState, ResultPreview


def execute(state: GraphState, deps: Deps) -> dict:
    if not state.sql:
        return {"status": "failed", "error": "No SQL to execute."}
    try:
        res = deps.db.run(state.sql, row_limit=deps.settings.result_row_limit)
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "error": f"Execution failed: {exc}"}

    preview = ResultPreview(
        columns=res.columns, rows=res.rows, truncated=res.truncated
    )
    return {"result": preview}
