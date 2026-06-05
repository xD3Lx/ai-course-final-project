"""Pydantic request/response models for the HTTP API."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class TranslateRequest(BaseModel):
    request: str = Field(..., description="Human-readable data request.")
    auto_execute: bool = Field(
        False, description="Run the query immediately if it validates."
    )


class ClarifyRequest(BaseModel):
    session_id: str
    request: str
    answers: list[str] = Field(default_factory=list)
    auto_execute: bool = False


class ExecuteRequest(BaseModel):
    sql: str
    row_limit: Optional[int] = None


class ResultPreviewOut(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    truncated: bool = False


class TranslateResponse(BaseModel):
    session_id: str
    status: str  # clarify | done | failed
    refined_request: str = ""
    pending_questions: list[str] = Field(default_factory=list)
    schema_tables: list[str] = Field(default_factory=list)
    sql: Optional[str] = None
    validation_ok: bool = False
    validation_errors: list[str] = Field(default_factory=list)
    attempts: int = 0
    result: Optional[ResultPreviewOut] = None
    explanation: str = ""
    error: str = ""


class ExecuteResponse(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    truncated: bool = False
