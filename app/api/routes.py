"""HTTP routes: translate, clarify, execute, health."""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException

from app.api.schemas import (
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


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/translate", response_model=TranslateResponse)
def translate(req: TranslateRequest) -> TranslateResponse:
    session_id = uuid.uuid4().hex
    state = GraphState(user_request=req.request, auto_execute=req.auto_execute)
    return _run(session_id, state)


@router.post("/clarify", response_model=TranslateResponse)
def clarify(req: ClarifyRequest) -> TranslateResponse:
    state = GraphState(
        user_request=req.request,
        clarifications=req.answers,
        auto_execute=req.auto_execute,
    )
    return _run(req.session_id or uuid.uuid4().hex, state)


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
