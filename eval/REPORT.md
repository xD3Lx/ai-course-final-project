# Evaluation

A golden-dataset evaluation for the NL → Databricks SQL pipeline.

## Golden dataset

`golden_dataset.json` holds 10 complex cases against Databricks' built-in
`samples` catalog (available in every workspace): nine over `samples.tpch`
(joins, aggregations, date filtering, anti-joins, derived measures) and one over
`samples.nyctaxi`. Each case has:

- `question` — the natural-language request fed to the pipeline.
- `expected_tables` — tables a correct answer must use.
- `golden_sql` — a reference query used for execution-accuracy comparison.
- `ordered` — whether row order is part of correctness (e.g. "top N").

## Metrics

For each case the harness runs the full multi-agent graph and records:

- **Valid SQL** — the Validator passed (sqlglot parse + schema check + Databricks `EXPLAIN`).
- **Tables match** — every expected table appears in the tables the schema agent selected.
- **Execution accuracy** — the generated query and the golden query return the
  same result set. Rows are compared with cell values sorted within each row (so
  column ordering doesn't matter) and numbers rounded to 2 dp (so float noise
  doesn't matter); for `ordered` cases row order must also match.
- **Completed / attempts / cost / tokens / latency** — pulled from the run's agent trace.

The clarifier is seeded with a "proceed" answer so runs are deterministic and
don't pause for input (we're scoring SQL generation, not the dialog).

## Run

Needs the same environment as the app (OpenRouter + Databricks credentials).

```bash
python -m eval.run_eval                 # all 10 cases, with execution accuracy
python -m eval.run_eval --no-exec       # skip running queries (validation + tables only)
python -m eval.run_eval --ids tpch_revenue_by_nation,nyctaxi_top_pickup_zips_by_fare
```

Reports are written to `eval/results/eval-<timestamp>.json` and `.md`, and the
Markdown summary is printed to the console.

## Notes & limitations

- Execution accuracy compares result sets, not SQL text — many correct queries
  phrase the same answer differently, so this is the fair signal.
- The within-row value-sort relaxation tolerates column reordering but will still
  flag a result that selects genuinely extra/missing columns. If you want a
  stricter or looser comparison, adjust `eval/evaluate.py`.
- `samples.nyctaxi.trips` is a small sample table, so its aggregates are modest.
