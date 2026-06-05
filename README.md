# nl2databricks

Multi-agent system that translates **human-readable requests into validated Databricks SQL**, with automatic checking and self-correction.

Built with **Python 3.11+ · FastAPI · Pydantic · LangGraph · OpenRouter (Haiku + Sonnet) · Streamlit · Databricks SQL connector · sqlglot**.

## How it works

A LangGraph state machine routes the request through specialized agents:

| Agent | Role | Model |
|-------|------|-------|
| Clarifier | Detect ambiguity, ask follow-ups, refine intent | Haiku |
| Schema Retriever | Pull `information_schema`, rank tables, narrow with LLM | Haiku |
| SQL Generator | Write Databricks SQL from intent + schema | Sonnet |
| Validator | sqlglot parse + read-only + identifier checks, then Databricks `EXPLAIN` | Haiku/tools |
| Repair | Fix SQL from validator feedback (loops back to Validate) | Sonnet |
| Executor | Row-limited execution on the SQL Warehouse | tool |
| Explainer | Plain-language summary | Haiku |

```
clarify ─needs info▶ END (return questions)
   │
   ▼
retrieve_schema ─▶ generate ─▶ validate ─errors,retries─▶ repair ─▶ validate
                                   │
                              valid │
                                    ▼
                         execute (if auto) ─▶ explain ─▶ END
```

Cheap roles run on Haiku, reasoning-heavy roles (generation, repair) on Sonnet — all via OpenRouter, swappable through env vars.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then fill in your keys
```

Required in `.env`:
- `OPENROUTER_API_KEY` — from https://openrouter.ai/keys
- `DATABRICKS_SERVER_HOSTNAME`, `DATABRICKS_HTTP_PATH`, `DATABRICKS_TOKEN` — from your SQL Warehouse connection details
- `DATABRICKS_CATALOG`, `DATABRICKS_SCHEMA` — the namespace to query

## Run

Two processes — backend, then UI:

```bash
# 1. API
uvicorn app.api.main:app --reload --port 8000

# 2. UI (new terminal)
streamlit run app/ui/streamlit_app.py
```

Open the Streamlit URL, type a request like *"Top 10 customers by total revenue in 2024"*, and review the generated SQL, validation status, and (optionally) results.

API docs: http://localhost:8000/docs

## API

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/translate` | Start a run from a NL request |
| POST | `/clarify` | Resume with answers to clarification questions |
| POST | `/execute` | Run an approved SQL statement |
| GET | `/health` | Liveness check |

## Configuration knobs (`.env`)

- `MODEL_CHEAP` / `MODEL_SMART` — OpenRouter model ids per tier.
- `MAX_REPAIR_ATTEMPTS` — validator↔repair loop cap (default 3).
- `READ_ONLY` — block DDL/DML and auto-append `LIMIT` (default true).
- `RESULT_ROW_LIMIT` — max rows fetched/returned (default 100).
- `SCHEMA_TOP_TABLES` — candidate tables sent to the schema selector (default 8).

## Project layout

```
app/
  config.py              Pydantic settings
  runtime.py             cached deps + compiled graph singletons
  llm/                   provider (OpenRouter), models, prompts
  tools/                 databricks.py, sqlglot_check.py
  graph/                 state.py, build_graph.py
  agents/                clarifier, schema, generator, validator, repair, executor, explainer
  api/                   FastAPI app, routes, schemas
  ui/                    streamlit_app.py
```

## Notes

- **Safety:** read-only mode rejects write/DDL statements and enforces a `LIMIT` before any query reaches Databricks.
- **Validation is layered:** offline sqlglot checks run first (fast, free), then a Databricks `EXPLAIN` dry-run catches plan-time errors without materializing data.
- The repair loop feeds structured validator errors back to a Sonnet agent until the query passes or `MAX_REPAIR_ATTEMPTS` is reached.
