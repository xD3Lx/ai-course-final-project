"""Run the multi-agent pipeline over the golden dataset and score it.

Usage:
    python -m eval.run_eval                 # all cases, with execution accuracy
    python -m eval.run_eval --no-exec       # skip running queries on Databricks
    python -m eval.run_eval --ids tpch_revenue_by_nation,nyctaxi_top_pickup_zips_by_fare

Requires the same env as the app (OpenRouter + Databricks). Writes a JSON and a
Markdown report to eval/results/.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from app.agents.deps import Deps
from app.graph.build_graph import build_graph
from app.graph.state import GraphState
from eval.evaluate import results_match, summarize, tables_match

logging.basicConfig(level=logging.WARNING)
HERE = Path(__file__).resolve().parent
DATASET = HERE / "golden_dataset.json"
RESULTS_DIR = HERE / "results"

# Seed a clarification so the clarifier proceeds deterministically instead of
# pausing to ask the user (we are testing SQL generation, not the dialog).
PROCEED = "Proceed with the most reasonable interpretation."


def load_dataset() -> dict:
    return json.loads(DATASET.read_text())


def run_case(graph, deps: Deps, case: dict, catalog: str, do_exec: bool) -> dict:
    qid = case["id"]
    out: dict = {"id": qid, "question": case["question"]}
    config = {"configurable": {"thread_id": f"eval-{qid}-{int(time.time())}"}}

    state = GraphState(
        user_request=case["question"],
        catalog=catalog,
        clarifications=[PROCEED],
        auto_execute=False,
    )
    try:
        final = graph.invoke(state, config=config)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    fs = GraphState(**final) if isinstance(final, dict) else final
    out["status"] = fs.status
    out["sql"] = fs.sql
    out["used_tables"] = [t.fqn for t in fs.schema_context]
    out["validation_ok"] = bool(fs.validation and fs.validation.ok)
    out["completed"] = fs.status == "done"
    out["attempts"] = fs.attempts
    out["tables_match"] = tables_match(case["expected_tables"], out["used_tables"])
    out["cost_usd"] = round(sum(s.cost_usd for s in fs.trace), 6)
    out["tokens"] = sum(s.tokens for s in fs.trace)
    out["latency_ms"] = round(sum(s.duration_ms for s in fs.trace), 0)

    out["execution_match"] = False
    if do_exec and out["validation_ok"] and fs.sql:
        try:
            gen_rows = deps.db.run(fs.sql, row_limit=1000).rows
            gold_rows = deps.db.run(case["golden_sql"], row_limit=1000).rows
            out["execution_match"] = results_match(
                gen_rows, gold_rows, case.get("ordered", False)
            )
            out["generated_rowcount"] = len(gen_rows)
            out["golden_rowcount"] = len(gold_rows)
        except Exception as exc:  # noqa: BLE001
            out["exec_error"] = f"{type(exc).__name__}: {exc}"
    return out


def render_markdown(summary: dict, cases: list[dict]) -> str:
    lines = [
        "# Evaluation report",
        "",
        f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}_",
        "",
        "## Summary",
        "",
        f"- Cases: **{summary['cases']}**",
        f"- Valid SQL: **{summary['valid_sql_pct']}%**",
        f"- Correct tables selected: **{summary['tables_match_pct']}%**",
        f"- Execution accuracy: **{summary['execution_match_pct']}%**",
        f"- Completed end-to-end: **{summary['completed_pct']}%**",
        f"- Total cost: **${summary['total_cost_usd']}** · "
        f"{summary['total_tokens']} tokens · avg {summary['avg_latency_ms']:.0f} ms/case",
        "",
        "## Per-case",
        "",
        "| Case | Valid | Tables | Exec | Attempts | Cost $ | Tokens |",
        "|------|:-----:|:------:|:----:|:--------:|-------:|-------:|",
    ]
    tick = lambda b: "✅" if b else "❌"  # noqa: E731
    for c in cases:
        if "error" in c:
            lines.append(f"| {c['id']} | ⚠️ error | | | | | |")
            continue
        lines.append(
            f"| {c['id']} | {tick(c.get('validation_ok'))} | "
            f"{tick(c.get('tables_match'))} | {tick(c.get('execution_match'))} | "
            f"{c.get('attempts', 0)} | {c.get('cost_usd', 0):.5f} | {c.get('tokens', 0)} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-exec", action="store_true", help="Skip execution accuracy.")
    ap.add_argument("--ids", default="", help="Comma-separated case ids to run.")
    args = ap.parse_args()

    data = load_dataset()
    catalog = data.get("catalog", "samples")
    cases = data["cases"]
    if args.ids:
        wanted = {x.strip() for x in args.ids.split(",")}
        cases = [c for c in cases if c["id"] in wanted]

    deps = Deps.create()
    graph = build_graph(deps)

    results = []
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['id']} …", flush=True)
        results.append(run_case(graph, deps, case, catalog, do_exec=not args.no_exec))

    summary = summarize(results)
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    (RESULTS_DIR / f"eval-{stamp}.json").write_text(
        json.dumps({"summary": summary, "cases": results}, indent=2, default=str)
    )
    md = render_markdown(summary, results)
    (RESULTS_DIR / f"eval-{stamp}.md").write_text(md)

    print("\n" + md)
    print(f"Reports written to {RESULTS_DIR}/eval-{stamp}.json|.md")


if __name__ == "__main__":
    main()
