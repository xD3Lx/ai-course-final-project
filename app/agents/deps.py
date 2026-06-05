"""Shared dependencies injected into agent nodes."""
from __future__ import annotations

from dataclasses import dataclass

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
