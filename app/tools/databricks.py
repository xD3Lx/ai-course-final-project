"""Databricks SQL Warehouse access (real SDK).

Provides: schema introspection via information_schema, an EXPLAIN dry-run for
plan-time validation, and a row-limited query execution.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from databricks import sql as dbsql

from app.config import Settings, get_settings


@dataclass
class ColumnInfo:
    name: str
    data_type: str


@dataclass
class TableInfo:
    catalog: str
    schema: str
    table: str
    columns: list[ColumnInfo] = field(default_factory=list)

    @property
    def fqn(self) -> str:
        return f"{self.catalog}.{self.schema}.{self.table}"

    def render(self) -> str:
        cols = ", ".join(f"{c.name} {c.data_type}" for c in self.columns)
        return f"{self.fqn} ({cols})"


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list]
    truncated: bool = False


class DatabricksClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        missing = [
            k
            for k in (
                "databricks_server_hostname",
                "databricks_http_path",
                "databricks_token",
            )
            if not getattr(self.settings, k)
        ]
        if missing:
            raise RuntimeError(f"Missing Databricks settings: {', '.join(missing)}")

    def _connect(self):
        return dbsql.connect(
            server_hostname=self.settings.databricks_server_hostname,
            http_path=self.settings.databricks_http_path,
            access_token=self.settings.databricks_token,
        )

    # ---- schema introspection ----
    def list_tables_with_columns(
        self, catalog: str | None = None, schema: str | None = None
    ) -> list[TableInfo]:
        catalog = catalog or self.settings.databricks_catalog
        schema = schema or self.settings.databricks_schema
        query = f"""
            SELECT table_name, column_name, data_type, ordinal_position
            FROM {catalog}.information_schema.columns
            WHERE table_schema = '{schema}'
            ORDER BY table_name, ordinal_position
        """
        tables: dict[str, TableInfo] = {}
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query)
            for table_name, column_name, data_type, _pos in cur.fetchall():
                key = table_name
                ti = tables.setdefault(
                    key, TableInfo(catalog=catalog, schema=schema, table=table_name)
                )
                ti.columns.append(ColumnInfo(name=column_name, data_type=str(data_type)))
        return list(tables.values())

    # ---- dry-run validation ----
    def explain(self, query: str) -> tuple[bool, str]:
        """Return (ok, message). Uses EXPLAIN so nothing is materialised."""
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(f"EXPLAIN {query}")
                plan = "\n".join(str(r[0]) for r in cur.fetchall())
            # Databricks reports plan-time errors inside the EXPLAIN output text.
            if "org.apache.spark.sql" in plan and "Error" in plan:
                return False, plan
            if plan.strip().lower().startswith("== error"):
                return False, plan
            return True, plan
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    # ---- execution ----
    def run(self, query: str, row_limit: int | None = None) -> QueryResult:
        row_limit = row_limit or self.settings.result_row_limit
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query)
            columns = [d[0] for d in (cur.description or [])]
            rows = cur.fetchmany(row_limit + 1)
        truncated = len(rows) > row_limit
        rows = [list(r) for r in rows[:row_limit]]
        return QueryResult(columns=columns, rows=rows, truncated=truncated)
