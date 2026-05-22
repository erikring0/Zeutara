"""LLM adapter — provider-agnostic chat-to-JSON shim.

Routes to Anthropic if ANTHROPIC_API_KEY is set, otherwise OpenAI if
OPENAI_API_KEY is set. This is the "two more days" item #5 (multi-LLM router)
shipped early because we have an OpenAI-only test environment.

Cost constants for both providers come from public list pricing (Anthropic
Sonnet 4.5: $3/$15 per Mtok; OpenAI gpt-4o-mini: $0.15/$0.60 per Mtok at time
of writing — see openai.com/api/pricing).
"""
from __future__ import annotations
import json
import os
from typing import Literal


Provider = Literal["anthropic", "openai"]


# Per-1M-token list prices, used for Decision.metadata.cost_usd.
PRICING = {
    "anthropic": {"input": 3.0, "output": 15.0},
    "openai":    {"input": 0.15, "output": 0.60},  # gpt-4o-mini default
}


def detect_provider() -> Provider:
    """Anthropic preferred when both keys are set; OpenAI fallback."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    raise RuntimeError(
        "No LLM provider key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY."
    )


def model_for(provider: Provider) -> str:
    if provider == "anthropic":
        return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    return os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


def chat_json(
    *,
    system: str,
    user: str,
    max_tokens: int,
) -> tuple[dict, int, int, str, str]:
    """Run a chat completion that MUST return a JSON object.

    Returns (parsed_json, input_tokens, output_tokens, model, provider).
    """
    provider = detect_provider()
    model = model_for(provider)

    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        raw = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()
        in_tok = msg.usage.input_tokens
        out_tok = msg.usage.output_tokens

    else:  # openai
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        raw = (resp.choices[0].message.content or "").strip()
        in_tok = resp.usage.prompt_tokens
        out_tok = resp.usage.completion_tokens

    # Strip ```json fences if a model wraps despite instructions.
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    parsed = json.loads(raw)
    return parsed, in_tok, out_tok, model, provider


def cost_usd(in_tok: int, out_tok: int, provider: Provider) -> float:
    p = PRICING[provider]
    return (in_tok / 1_000_000 * p["input"]) + (out_tok / 1_000_000 * p["output"])
