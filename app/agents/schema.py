"""Schema Retriever agent — fetch catalog schema, rank by relevance, narrow with LLM."""
from __future__ import annotations

import re

from app.agents.deps import Deps
from app.graph.state import GraphState, TableContext
from app.llm.models import TableSelection
from app.llm.prompts import SCHEMA_SELECTOR
from app.tools.databricks import TableInfo


def _keyword_rank(request: str, tables: list[TableInfo], top_n: int) -> list[TableInfo]:
    """Cheap lexical pre-filter so we send only candidate tables to the LLM."""
    tokens = {t for t in re.findall(r"[a-zA-Z_]+", request.lower()) if len(t) > 2}

    def score(ti: TableInfo) -> int:
        haystack = (ti.table + " " + " ".join(c.name for c in ti.columns)).lower()
        return sum(1 for tok in tokens if tok in haystack)

    ranked = sorted(tables, key=score, reverse=True)
    # keep any positive-scoring tables, but always return at least top_n
    positive = [t for t in ranked if score(t) > 0]
    return (positive or ranked)[:top_n]


def retrieve_schema(state: GraphState, deps: Deps) -> dict:
    request = state.refined_request or state.user_request
    catalog = state.catalog or deps.settings.databricks_catalog
    all_tables = deps.db.list_tables_with_columns(catalog=catalog)
    if not all_tables:
        return {
            "status": "failed",
            "error": f"No tables found in catalog {catalog}.",
        }

    candidates = _keyword_rank(request, all_tables, deps.settings.schema_top_tables)
    catalog_text = "\n".join(t.render() for t in candidates)

    # Let the LLM pick the minimal set from candidates.
    selection = deps.llm.complete_json(
        role="schema",
        system=SCHEMA_SELECTOR,
        user=f"Request: {request}\n\nAvailable tables:\n{catalog_text}",
        schema=TableSelection,
    )

    chosen_fqns = {s.lower() for s in selection.tables}
    chosen = [t for t in candidates if t.fqn.lower() in chosen_fqns]
    if not chosen:  # fall back to the lexical candidates
        chosen = candidates

    context = [TableContext(fqn=t.fqn, rendered=t.render()) for t in chosen]
    return {"schema_context": context}
