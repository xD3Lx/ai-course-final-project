"""Structured LLM I/O schemas shared by agents."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ClarifyDecision(BaseModel):
    needs_clarification: bool = Field(
        description="True if the request is too ambiguous to translate safely."
    )
    questions: list[str] = Field(
        default_factory=list,
        description="Concrete questions to resolve ambiguity (empty if none).",
    )
    refined_request: str = Field(
        default="",
        description="A cleaned, unambiguous restatement of the user's intent.",
    )


class TableSelection(BaseModel):
    tables: list[str] = Field(
        default_factory=list,
        description="Fully-qualified table names relevant to the request.",
    )
    reasoning: str = ""


class GeneratedSQL(BaseModel):
    sql: str = Field(description="A single Databricks (Spark) SQL statement.")
    notes: str = ""


class RepairedSQL(BaseModel):
    sql: str
    changes: str = ""
