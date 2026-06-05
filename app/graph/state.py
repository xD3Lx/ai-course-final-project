"""Shared LangGraph state passed between agent nodes."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Status = Literal["clarify", "running", "done", "failed"]


class ValidationResult(BaseModel):
    ok: bool = False
    errors: list[str] = Field(default_factory=list)
    explain_plan: str = ""


class TableContext(BaseModel):
    fqn: str
    rendered: str  # "catalog.schema.table (col type, ...)"


class ResultPreview(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    truncated: bool = False


class GraphState(BaseModel):
    # input
    user_request: str
    clarifications: list[str] = Field(default_factory=list)  # answers from user
    auto_execute: bool = False

    # working memory
    refined_request: str = ""
    pending_questions: list[str] = Field(default_factory=list)
    schema_context: list[TableContext] = Field(default_factory=list)
    sql: Optional[str] = None
    validation: Optional[ValidationResult] = None
    attempts: int = 0

    # output
    result: Optional[ResultPreview] = None
    explanation: str = ""
    status: Status = "running"
    error: str = ""
