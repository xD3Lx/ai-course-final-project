"""Streamlit UI for nl2databricks.

Run:  streamlit run app/ui/streamlit_app.py
Talks to the FastAPI backend (API_BASE_URL).
"""
from __future__ import annotations

import json
import os
from typing import Iterator

import requests
import streamlit as st

API = os.getenv("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="nl2databricks", page_icon="🧱", layout="wide")
st.title("🧱 nl2databricks")
st.caption("Human request → validated Databricks SQL, with multi-agent checking.")


def _post(path: str, payload: dict) -> dict:
    resp = requests.post(f"{API}{path}", json=payload, timeout=180)
    resp.raise_for_status()
    return resp.json()


AGENT_ICONS = {
    "clarify": "🧭",
    "retrieve_schema": "🗂️",
    "generate": "✍️",
    "validate": "✅",
    "repair": "🔧",
    "execute": "▶️",
    "explain": "💬",
}
AGENT_LABELS = {
    "clarify": "Understanding your request",
    "retrieve_schema": "Finding relevant tables",
    "generate": "Writing SQL",
    "validate": "Validating the query",
    "repair": "Fixing the query",
    "execute": "Running the query",
    "explain": "Explaining the result",
}


def _stream(path: str, payload: dict) -> Iterator[dict]:
    """Yield NDJSON events from a streaming backend endpoint."""
    with requests.post(
        f"{API}{path}", json=payload, stream=True, timeout=300
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines(decode_unicode=True):
            if line:
                yield json.loads(line)


def run_with_progress(path: str, payload: dict) -> dict | None:
    """Drive a streaming run, showing each agent live (Claude-Desktop style)."""
    final = None
    with st.status("Starting agents…", expanded=True) as status:
        try:
            for ev in _stream(path, payload):
                kind = ev.get("event")
                if kind == "step":
                    agent = ev["agent"]
                    icon = AGENT_ICONS.get(agent, "•")
                    label = AGENT_LABELS.get(agent, agent)
                    mark = "" if ev.get("ok", True) else " ⚠️"
                    status.update(label=f"{icon} {label}…")
                    st.write(
                        f"{icon} **{label}**{mark} "
                        f"— {ev.get('summary', '')} "
                        f"_({ev.get('duration_ms', 0):.0f} ms)_"
                    )
                elif kind == "done":
                    final = ev["data"]
                    status.update(label="✅ Done", state="complete")
                elif kind == "error":
                    status.update(label="❌ Failed", state="error")
                    st.error(ev.get("detail", "Unknown error"))
        except Exception as exc:  # noqa: BLE001
            status.update(label="❌ Failed", state="error")
            st.error(f"Request failed: {exc}")
    return final


# --- session state ---
st.session_state.setdefault("result", None)
st.session_state.setdefault("awaiting", None)  # holds clarification context

with st.sidebar:
    st.subheader("Settings")
    auto_exec = st.toggle("Auto-execute valid query", value=False)
    st.write(f"API: `{API}`")
    try:
        ok = requests.get(f"{API}/health", timeout=5).json().get("status")
        st.success(f"Backend: {ok}")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Backend unreachable: {exc}")

request = st.text_area(
    "Describe what you want in plain language",
    placeholder="e.g. Top 10 customers by total revenue in 2024",
    height=90,
)

if st.button("Translate", type="primary", disabled=not request.strip()):
    result = run_with_progress(
        "/translate/stream", {"request": request, "auto_execute": auto_exec}
    )
    if result is not None:
        st.session_state.result = result
        st.session_state.awaiting = None

res = st.session_state.result


def render_trace(trace: list[dict]) -> None:
    if not trace:
        return
    total = sum(s.get("duration_ms", 0) for s in trace)
    with st.expander(f"🧩 Agent trace — {len(trace)} steps, {total:.0f} ms", expanded=True):
        for i, step in enumerate(trace, 1):
            icon = AGENT_ICONS.get(step["agent"], "•")
            mark = "✅" if step.get("ok", True) else "⚠️"
            st.markdown(
                f"**{i}. {icon} {step['agent']}** {mark} "
                f"<span style='color:gray'>· {step.get('duration_ms', 0):.0f} ms</span><br>"
                f"<span style='color:#444'>{step['summary']}</span>",
                unsafe_allow_html=True,
            )


def render(res: dict) -> None:
    status = res.get("status")

    render_trace(res.get("trace", []))

    if status == "clarify":
        st.info("The assistant needs a bit more detail:")
        answers = []
        for i, q in enumerate(res.get("pending_questions", [])):
            answers.append(st.text_input(q, key=f"clar_{i}"))
        if st.button("Submit answers"):
            payload = {
                "session_id": res.get("session_id", ""),
                "request": request,
                "answers": [a for a in answers if a.strip()],
                "auto_execute": auto_exec,
            }
            result = run_with_progress("/clarify/stream", payload)
            if result is not None:
                st.session_state.result = result
                st.rerun()
        return

    if res.get("refined_request"):
        st.markdown(f"**Interpreted as:** {res['refined_request']}")

    if res.get("schema_tables"):
        st.markdown("**Tables used:** " + ", ".join(f"`{t}`" for t in res["schema_tables"]))

    if res.get("sql"):
        st.markdown("**Generated SQL**")
        st.code(res["sql"], language="sql")

    if res.get("validation_ok"):
        st.success(f"Validation passed (attempts: {res.get('attempts', 0)})")
    elif res.get("validation_errors"):
        st.error("Validation errors:")
        for e in res["validation_errors"]:
            st.write(f"- {e}")

    if res.get("explanation"):
        st.markdown("**Explanation**")
        st.write(res["explanation"])

    if res.get("error"):
        st.warning(res["error"])

    # results table
    result = res.get("result")
    if result and result.get("columns"):
        st.markdown("**Result preview**")
        st.dataframe(
            [dict(zip(result["columns"], row)) for row in result["rows"]],
            use_container_width=True,
        )
        if result.get("truncated"):
            st.caption("Results truncated to the configured row limit.")

    # manual run for a validated-but-not-executed query
    if res.get("validation_ok") and not result and res.get("sql"):
        if st.button("▶ Run this query"):
            with st.spinner("Executing…"):
                out = _post("/execute", {"sql": res["sql"]})
                st.dataframe(
                    [dict(zip(out["columns"], r)) for r in out["rows"]],
                    use_container_width=True,
                )


if res:
    render(res)
