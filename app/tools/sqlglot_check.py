"""Deterministic, offline SQL checks using sqlglot.

Covers: single-statement parse in the Databricks dialect, read-only enforcement,
and column/table existence against the retrieved schema.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

from app.tools.databricks import TableInfo

DIALECT = "databricks"
_WRITE_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Merge,
)


@dataclass
class StaticCheck:
    ok: bool
    errors: list[str] = field(default_factory=list)


def _known_columns(tables: list[TableInfo]) -> set[str]:
    cols: set[str] = set()
    for t in tables:
        for c in t.columns:
            cols.add(c.name.lower())
    return cols


def _known_table_names(tables: list[TableInfo]) -> set[str]:
    names: set[str] = set()
    for t in tables:
        names.add(t.table.lower())
        names.add(t.fqn.lower())
        names.add(f"{t.schema}.{t.table}".lower())
    return names


def static_check(
    query: str, tables: list[TableInfo], read_only: bool = True
) -> StaticCheck:
    errors: list[str] = []

    # 1. parse
    try:
        statements = sqlglot.parse(query, read=DIALECT)
    except Exception as exc:  # noqa: BLE001
        return StaticCheck(ok=False, errors=[f"Syntax error: {exc}"])

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        errors.append(f"Expected exactly one statement, found {len(statements)}.")
        return StaticCheck(ok=False, errors=errors)

    tree = statements[0]

    # 2. read-only enforcement
    if read_only and isinstance(tree, _WRITE_NODES):
        errors.append("Write/DDL statements are not allowed in read-only mode.")

    if not tables:
        # Cannot validate identifiers without a schema; parse success is enough.
        return StaticCheck(ok=not errors, errors=errors)

    known_cols = _known_columns(tables)
    known_tables = _known_table_names(tables)

    # 3. referenced tables exist
    for tbl in tree.find_all(exp.Table):
        name = tbl.name.lower()
        full = ".".join(
            p.name for p in (tbl.args.get("catalog"), tbl.args.get("db"), tbl.this) if p
        ).lower()
        if name not in known_tables and full not in known_tables:
            errors.append(f"Unknown table referenced: {tbl.sql(dialect=DIALECT)}")

    # 4. referenced columns exist (skip aliases & '*')
    aliases = {a.alias_or_name.lower() for a in tree.find_all(exp.Alias)}
    for col in tree.find_all(exp.Column):
        cname = col.name.lower()
        if not cname or cname == "*":
            continue
        if cname in known_cols or cname in aliases:
            continue
        errors.append(f"Unknown column referenced: {col.sql(dialect=DIALECT)}")

    # de-duplicate while keeping order
    seen: set[str] = set()
    deduped = [e for e in errors if not (e in seen or seen.add(e))]
    return StaticCheck(ok=not deduped, errors=deduped)


def ensure_limit(query: str, limit: int) -> str:
    """Add a LIMIT to a bare SELECT if it has none (best-effort, dialect-aware)."""
    try:
        tree = sqlglot.parse_one(query, read=DIALECT)
    except Exception:  # noqa: BLE001
        return query
    if isinstance(tree, exp.Select) and not tree.args.get("limit"):
        tree = tree.limit(limit)
        return tree.sql(dialect=DIALECT)
    return query
