"""Scoring helpers for the golden-dataset evaluation.

Execution accuracy is the primary signal for NL->SQL: we run both the generated
query and the reference query and compare result sets. To tolerate harmless
differences in column ordering, each row's cell values are sorted before
comparison (a common "set match" relaxation). Numeric values are rounded so
floating-point noise doesn't cause false mismatches.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable

ROUND_DP = 2


def _norm_value(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int,)):
        return float(v)
    if isinstance(v, (float, Decimal)):
        return round(float(v), ROUND_DP)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return str(v)


def _norm_row(row: Iterable[Any]) -> tuple:
    # Sort cell values within the row so column ordering doesn't matter.
    return tuple(sorted((_norm_value(v) for v in row), key=lambda x: (str(type(x)), str(x))))


def normalize_table(rows: list[list[Any]]) -> list[tuple]:
    return [_norm_row(r) for r in rows]


def results_match(
    generated: list[list[Any]], golden: list[list[Any]], ordered: bool
) -> bool:
    """True if the two result sets are equivalent."""
    g = normalize_table(generated)
    gold = normalize_table(golden)
    if ordered:
        return g == gold
    return Counter(g) == Counter(gold)


def tables_match(expected: list[str], used_fqns: list[str]) -> bool:
    """True if every expected table name appears among the used (fully-qualified) tables."""
    used_names = {fqn.split(".")[-1].lower() for fqn in used_fqns}
    return all(t.split(".")[-1].lower() in used_names for t in expected)


def summarize(case_results: list[dict]) -> dict:
    n = len(case_results) or 1
    def rate(key: str) -> float:
        return round(100.0 * sum(1 for c in case_results if c.get(key)) / n, 1)

    return {
        "cases": len(case_results),
        "valid_sql_pct": rate("validation_ok"),
        "tables_match_pct": rate("tables_match"),
        "execution_match_pct": rate("execution_match"),
        "completed_pct": rate("completed"),
        "total_cost_usd": round(sum(c.get("cost_usd", 0.0) for c in case_results), 5),
        "total_tokens": sum(c.get("tokens", 0) for c in case_results),
        "avg_latency_ms": round(
            sum(c.get("latency_ms", 0.0) for c in case_results) / n, 0
        ),
    }
