"""Streamlit UI for nl2databricks.

Run:  streamlit run app/ui/streamlit_app.py
Talks to the FastAPI backend (API_BASE_URL).
"""
from __future__ import annotations

import os

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
    with st.spinner("Agents working…"):
        try:
            st.session_state.result = _post(
                "/translate", {"request": request, "auto_execute": auto_exec}
            )
            st.session_state.awaiting = None
        except Exception as exc:  # noqa: BLE001
            st.error(f"Request failed: {exc}")

res = st.session_state.result


AGENT_ICONS = {
    "clarify": "🧭",
    "retrieve_schema": "🗂️",
    "generate": "✍️",
    "validate": "✅",
    "repair": "🔧",
    "execute": "▶️",
    "explain": "💬",
}


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
            with st.spinner("Re-running with your answers…"):
                payload = {
                    "session_id": res.get("session_id", ""),
                    "request": request,
                    "answers": [a for a in answers if a.strip()],
                    "auto_execute": auto_exec,
                }
                st.session_state.result = _post("/clarify", payload)
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
