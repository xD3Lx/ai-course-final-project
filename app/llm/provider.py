"""LLM provider abstraction over OpenRouter (OpenAI-compatible API).

Each agent calls ``complete`` / ``complete_json`` with a *role*; the role is
mapped to a concrete model via Settings.role_model (Haiku for cheap roles,
Sonnet for complex ones).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings

T = TypeVar("T", bound=BaseModel)

# Fallback prices (USD per 1M tokens: input, output) used only if OpenRouter
# does not return an actual cost. Approximate; OpenRouter's reported cost wins.
_FALLBACK_PRICES: dict[str, tuple[float, float]] = {
    "haiku": (0.80, 4.00),
    "sonnet": (3.00, 15.00),
    "opus": (15.00, 75.00),
}


@dataclass
class CallUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


class LLMError(RuntimeError):
    pass


class LLMProvider:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.openrouter_api_key:
            raise LLMError("OPENROUTER_API_KEY is not set.")
        self._client = OpenAI(
            api_key=self.settings.openrouter_api_key,
            base_url=self.settings.openrouter_base_url,
            default_headers={
                "HTTP-Referer": self.settings.openrouter_site_url,
                "X-Title": self.settings.openrouter_app_title,
            },
        )

    def _model_for(self, role: str) -> str:
        try:
            return self.settings.role_model[role]
        except KeyError as exc:
            raise LLMError(f"Unknown role: {role!r}") from exc

    def complete(
        self,
        role: str,
        system: str,
        user: str,
        temperature: float = 0.1,
        json_mode: bool = False,
    ) -> tuple[str, CallUsage]:
        model = self._model_for(role)
        kwargs: dict = {
            "model": model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # Ask OpenRouter to report the actual cost in the usage object.
            "extra_body": {"usage": {"include": True}},
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - surface provider errors uniformly
            raise LLMError(f"OpenRouter call failed for role {role!r}: {exc}") from exc
        content = (resp.choices[0].message.content or "").strip()
        return content, _usage_from_response(resp, model)

    def complete_json(
        self,
        role: str,
        system: str,
        user: str,
        schema: Type[T],
        temperature: float = 0.1,
    ) -> tuple[T, CallUsage]:
        """Return a validated Pydantic model + token/cost usage for the call."""
        instruction = (
            f"{system}\n\nRespond with a single JSON object matching this schema:\n"
            f"{json.dumps(schema.model_json_schema(), indent=2)}"
        )
        raw, usage = self.complete(
            role, instruction, user, temperature=temperature, json_mode=True
        )
        cleaned = _extract_json(raw)
        try:
            return schema.model_validate_json(cleaned), usage
        except ValidationError as exc:
            raise LLMError(
                f"Model output failed validation for {schema.__name__}: {exc}\nRaw: {raw}"
            ) from exc


def _usage_from_response(resp, model: str) -> CallUsage:
    u = getattr(resp, "usage", None)
    if u is None:
        return CallUsage()
    prompt = int(getattr(u, "prompt_tokens", 0) or 0)
    completion = int(getattr(u, "completion_tokens", 0) or 0)
    total = int(getattr(u, "total_tokens", 0) or (prompt + completion))

    # OpenRouter returns actual cost as an extra field on usage.
    cost = getattr(u, "cost", None)
    if cost is None:
        extra = getattr(u, "model_extra", None) or {}
        cost = extra.get("cost")
    if cost is None:
        cost = _estimate_cost(model, prompt, completion)
    return CallUsage(prompt, completion, total, float(cost or 0.0))


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    model_l = model.lower()
    for key, (in_price, out_price) in _FALLBACK_PRICES.items():
        if key in model_l:
            return (
                prompt_tokens / 1_000_000 * in_price
                + completion_tokens / 1_000_000 * out_price
            )
    return 0.0


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1] if "\n" in text else text
        if text.endswith("```"):
            text = text[: -3]
        # drop a leading "json" language tag if present
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
    return text.strip()


def _extract_json(text: str) -> str:
    """Extract the first balanced JSON object from a model response.

    Models sometimes wrap JSON in code fences or append explanatory prose after
    the closing brace; this returns just the ``{...}`` block.
    """
    text = _strip_code_fence(text)
    start = text.find("{")
    if start == -1:
        return text
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]
