"""Shared dependencies injected into agent nodes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import Settings, get_settings
from app.llm.provider import LLMProvider
from app.tools.databricks import DatabricksClient


@dataclass
class Deps:
    settings: Settings
    llm: LLMProvider
    db: DatabricksClient

    @classmethod
    def create(cls) -> "Deps":
        settings = get_settings()
        return cls(
            settings=settings,
            llm=LLMProvider(settings),
            db=DatabricksClient(settings),
        )


def with_cost(update: dict, usage: Any) -> dict:
    """Attach an LLM call's cost/tokens to a node update for the tracer."""
    update["_cost"] = float(getattr(usage, "cost_usd", 0.0) or 0.0)
    update["_tokens"] = int(getattr(usage, "total_tokens", 0) or 0)
    return update
