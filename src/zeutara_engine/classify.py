"""Stage 2 — CLASSIFY.

Single LLM call. Reads LeadProfile, returns archetype + active triggers as
strict JSON. Provider-agnostic via `llm.chat_json`.
"""
from __future__ import annotations
import json
from importlib import resources
from typing import TypedDict

from .schemas import LeadProfile, Archetype, ActiveTrigger
from .llm import chat_json


PROMPT_VERSION = "v0.3.1"


class ClassificationResult(TypedDict):
    archetype: Archetype
    active_triggers: list[ActiveTrigger]
    input_tokens: int
    output_tokens: int
    model: str
    provider: str


def _load_prompt() -> str:
    return (
        resources.files("zeutara_engine.prompts")
        .joinpath("classify.txt")
        .read_text(encoding="utf-8")
    )


def classify(lead: LeadProfile) -> ClassificationResult:
    """Run the classifier. Returns parsed pydantic objects + token counts."""
    system_prompt = _load_prompt()
    user_payload = json.dumps(lead.model_dump(mode="json"), indent=2, default=str)
    user = (
        f"LeadProfile JSON:\n```json\n{user_payload}\n```\n\n"
        "Return ONLY the JSON object specified in the system prompt."
    )

    parsed, in_tok, out_tok, model, provider = chat_json(
        system=system_prompt, user=user, max_tokens=1024
    )

    archetype = Archetype.model_validate(parsed["archetype"])
    triggers = [ActiveTrigger.model_validate(t) for t in parsed.get("active_triggers", [])]

    return ClassificationResult(
        archetype=archetype,
        active_triggers=triggers,
        input_tokens=in_tok,
        output_tokens=out_tok,
        model=model,
        provider=provider,
    )
