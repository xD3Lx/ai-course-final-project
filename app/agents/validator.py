"""Validator agent — deterministic static checks + Databricks EXPLAIN dry-run."""
from __future__ import annotations

from app.agents.deps import Deps
from app.graph.state import GraphState, ValidationResult
from app.tools.databricks import ColumnInfo, TableInfo
from app.tools.sqlglot_check import static_check


def _rebuild_tables(state: GraphState) -> list[TableInfo]:
    """Reconstruct TableInfo objects from the rendered schema context."""
    tables: list[TableInfo] = []
    for tc in state.schema_context:
        catalog, schema, table = (tc.fqn.split(".") + ["", "", ""])[:3]
        cols: list[ColumnInfo] = []
        if "(" in tc.rendered:
            inside = tc.rendered.split("(", 1)[1].rsplit(")", 1)[0]
            for part in inside.split(","):
                part = part.strip()
                if not part:
                    continue
                name, _, dtype = part.partition(" ")
                cols.append(ColumnInfo(name=name, data_type=dtype or "unknown"))
        tables.append(
            TableInfo(catalog=catalog, schema=schema, table=table, columns=cols)
        )
    return tables


def validate(state: GraphState, deps: Deps) -> dict:
    if not state.sql:
        return {
            "validation": ValidationResult(ok=False, errors=["No SQL to validate."])
        }

    tables = _rebuild_tables(state)

    # 1. offline static checks (syntax, read-only, identifiers)
    static = static_check(state.sql, tables, read_only=deps.settings.read_only)
    if not static.ok:
        return {"validation": ValidationResult(ok=False, errors=static.errors)}

    # 2. plan-time validation against Databricks
    ok, message = deps.db.explain(state.sql)
    if not ok:
        return {
            "validation": ValidationResult(
                ok=False, errors=[f"EXPLAIN failed: {message}"]
            )
        }

    return {"validation": ValidationResult(ok=True, explain_plan=message)}
