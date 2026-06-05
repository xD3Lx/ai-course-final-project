"""Lazily-initialised singletons for the API process (deps + compiled graph)."""
from __future__ import annotations

from functools import lru_cache

from app.agents.deps import Deps
from app.graph.build_graph import build_graph


@lru_cache
def get_deps() -> Deps:
    return Deps.create()


@lru_cache
def get_graph():
    return build_graph(get_deps())
