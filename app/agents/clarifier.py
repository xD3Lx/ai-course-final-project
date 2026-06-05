"""Clarifier agent — detect ambiguity, optionally ask the user, refine intent."""
from __future__ import annotations

from app.agents.deps import Deps
from app.graph.state import GraphState
from app.llm.models import ClarifyDecision
from app.llm.prompts import CLARIFIER


def clarify(state: GraphState, deps: Deps) -> dict:
    user = f"Request: {state.user_request}"
    if state.clarifications:
        joined = "\n".join(f"- {c}" for c in state.clarifications)
        user += f"\n\nThe user already provided these clarifications:\n{joined}"

    decision = deps.llm.complete_json(
        role="clarifier",
        system=CLARIFIER,
        user=user,
        schema=ClarifyDecision,
    )

    # Only ask once: if we already have answers, proceed regardless.
    if decision.needs_clarification and not state.clarifications:
        return {
            "status": "clarify",
            "pending_questions": decision.questions,
            "refined_request": decision.refined_request or state.user_request,
        }

    return {
        "status": "running",
        "pending_questions": [],
        "refined_request": decision.refined_request or state.user_request,
    }
