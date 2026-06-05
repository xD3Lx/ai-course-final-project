"""HTTP routes: translate, clarify, execute, health."""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.schemas import (
    AgentStepOut,
    ClarifyRequest,
    ExecuteRequest,
    ExecuteResponse,
    ResultPreviewOut,
    TranslateRequest,
    TranslateResponse,
)
from app.graph.state import GraphState
from app.runtime import get_deps, get_graph

logger = logging.getLogger("nl2databricks.api")

router = APIRouter()


def _to_response(session_id: str, final: dict | GraphState) -> TranslateResponse:
    state = final if isinstance(final, GraphState) else GraphState(**final)
    result = None
    if state.result:
        result = ResultPreviewOut(
            columns=state.result.columns,
            rows=state.result.rows,
            truncated=state.result.truncated,
        )
    return TranslateResponse(
        session_id=session_id,
        status=state.status,
        refined_request=state.refined_request,
        pending_questions=state.pending_questions,
        schema_tables=[t.fqn for t in state.schema_context],
        sql=state.sql,
        validation_ok=bool(state.validation and state.validation.ok),
        validation_errors=state.validation.errors if state.validation else [],
        attempts=state.attempts,
        result=result,
        explanation=state.explanation,
        error=state.error,
        trace=[
            AgentStepOut(
                agent=s.agent,
                summary=s.summary,
                duration_ms=s.duration_ms,
                ok=s.ok,
            )
            for s in state.trace
        ],
    )


def _run(session_id: str, state: GraphState) -> TranslateResponse:
    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}
    try:
        final = graph.invoke(state, config=config)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Graph run failed for session %s", session_id)
        raise HTTPException(
            status_code=500, detail=f"{type(exc).__name__}: {exc}"
        ) from exc
    return _to_response(session_id, final)


def _step_payload(node: str, update: Any) -> dict:
    """Turn one streamed node update into a step event."""
    steps = (update or {}).get("trace") if isinstance(update, dict) else None
    if steps:
        s = steps[0]
        agent = getattr(s, "agent", None) or s["agent"]
        summary = getattr(s, "summary", None) or s["summary"]
        duration = getattr(s, "duration_ms", None)
        if duration is None:
            duration = s["duration_ms"]
        ok = getattr(s, "ok", None)
        if ok is None:
            ok = s["ok"]
        return {
            "event": "step",
            "agent": agent,
            "summary": summary,
            "duration_ms": duration,
            "ok": ok,
        }
    return {"event": "step", "agent": node, "summary": node, "duration_ms": 0, "ok": True}


def _stream_run(session_id: str, state: GraphState) -> StreamingResponse:
    """Stream agent steps as newline-delimited JSON, then a final 'done' event."""
    graph = get_graph()
    config = {"configurable": {"thread_id": session_id}}

    def gen() -> Iterator[str]:
        try:
            for chunk in graph.stream(state, config=config, stream_mode="updates"):
                for node, update in chunk.items():
                    yield json.dumps(_step_payload(node, update)) + "\n"
            final = graph.get_state(config).values
            resp = _to_response(session_id, final)
            yield json.dumps({"event": "done", "data": resp.model_dump()}) + "\n"
        except Exception as exc:  # noqa: BLE001
            logger.exception("Streaming run failed for session %s", session_id)
            yield json.dumps(
                {"event": "error", "detail": f"{type(exc).__name__}: {exc}"}
            ) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/translate", response_model=TranslateResponse)
def translate(req: TranslateRequest) -> TranslateResponse:
    session_id = uuid.uuid4().hex
    state = GraphState(user_request=req.request, auto_execute=req.auto_execute)
    return _run(session_id, state)


@router.post("/translate/stream")
def translate_stream(req: TranslateRequest) -> StreamingResponse:
    session_id = uuid.uuid4().hex
    state = GraphState(user_request=req.request, auto_execute=req.auto_execute)
    return _stream_run(session_id, state)


@router.post("/clarify", response_model=TranslateResponse)
def clarify(req: ClarifyRequest) -> TranslateResponse:
    state = GraphState(
        user_request=req.request,
        clarifications=req.answers,
        auto_execute=req.auto_execute,
    )
    return _run(req.session_id or uuid.uuid4().hex, state)


@router.post("/clarify/stream")
def clarify_stream(req: ClarifyRequest) -> StreamingResponse:
    state = GraphState(
        user_request=req.request,
        clarifications=req.answers,
        auto_execute=req.auto_execute,
    )
    return _stream_run(req.session_id or uuid.uuid4().hex, state)


@router.post("/execute", response_model=ExecuteResponse)
def execute(req: ExecuteRequest) -> ExecuteResponse:
    deps = get_deps()
    try:
        res = deps.db.run(req.sql, row_limit=req.row_limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Execute failed")
        raise HTTPException(
            status_code=400, detail=f"{type(exc).__name__}: {exc}"
        ) from exc
    return ExecuteResponse(
        columns=res.columns, rows=res.rows, truncated=res.truncated
    )
