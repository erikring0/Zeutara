"""Stage 3 — SCORE + PERSONALIZE.

`compute_score` is fully deterministic — auditable, replayable, no LLM.
`personalize` is the second LLM call, gated on the score being non-trivial.

The score formula is intentionally simple and inspectable. Calibration over
time happens by tuning the weights, NOT by training a model. That keeps the
engine honest at low volume.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from importlib import resources
from typing import Optional

from .schemas import (
    LeadProfile,
    Archetype,
    ActiveTrigger,
    DisqualifierCheck,
    PersonalizationVector,
    RecommendedAction,
    Decision,
    Metadata,
)
from .classify import PROMPT_VERSION
from .llm import chat_json, cost_usd


# ---- DETERMINISTIC SCORING ----

ARCHETYPE_WEIGHT = 50  # Type A is half the score; this is the dominant signal
TRIGGER_WEIGHT_CAP = 35  # all triggers combined cap here
HEADCOUNT_FIT_WEIGHT = 5
ARR_FIT_WEIGHT = 5
RECENCY_WEIGHT = 5  # last raise is in 4–10mo sweet spot


def _archetype_subscore(a: Archetype) -> int:
    if a.type == "Type A — Technical Founder":
        return int(ARCHETYPE_WEIGHT * a.confidence)
    if a.type == "Type B — Commercial Founder":
        return 0
    return int(ARCHETYPE_WEIGHT * 0.4 * a.confidence)  # mixed = partial credit


def _trigger_subscore(triggers: list[ActiveTrigger]) -> int:
    raw = sum(t.weight for t in triggers)
    return int(min(TRIGGER_WEIGHT_CAP, raw * TRIGGER_WEIGHT_CAP))


def _firmographic_subscore(lead: LeadProfile) -> int:
    score = 0
    # Headcount fit: 5–25 is sweet spot
    if 5 <= lead.company.headcount <= 25:
        score += HEADCOUNT_FIT_WEIGHT
    elif lead.company.headcount <= 50:
        score += HEADCOUNT_FIT_WEIGHT // 2
    # ARR fit: $100k–$2M is sweet spot
    arr = lead.company.estimated_arr_usd or 0
    if 100_000 <= arr <= 2_000_000:
        score += ARR_FIT_WEIGHT
    elif arr <= 3_000_000:
        score += ARR_FIT_WEIGHT // 2
    return score


def _recency_subscore(lead: LeadProfile, today=None) -> int:
    from datetime import date
    today = today or date.today()
    age_days = (today - lead.company.funding.last_round_date).days
    if 30 * 4 <= age_days <= 30 * 10:
        return RECENCY_WEIGHT
    if age_days < 30 * 4 or age_days <= 30 * 12:
        return RECENCY_WEIGHT // 2
    return 0


def compute_score(
    lead: LeadProfile,
    archetype: Archetype,
    triggers: list[ActiveTrigger],
    disqualifiers: DisqualifierCheck,
) -> tuple[int, str]:
    """Return (score 0–100, fit_band)."""
    if not disqualifiers.all_clear:
        return 0, "D"
    score = (
        _archetype_subscore(archetype)
        + _trigger_subscore(triggers)
        + _firmographic_subscore(lead)
        + _recency_subscore(lead)
    )
    score = max(0, min(100, score))
    if score >= 75:
        band = "A"
    elif score >= 55:
        band = "B"
    elif score >= 35:
        band = "C"
    else:
        band = "D"
    return score, band


# ---- LLM PERSONALIZATION ----

def _load_personalize_prompt() -> str:
    return (
        resources.files("zeutara_engine.prompts")
        .joinpath("personalize.txt")
        .read_text(encoding="utf-8")
    )


def personalize(
    lead: LeadProfile,
    archetype: Archetype,
    triggers: list[ActiveTrigger],
    disqualifiers: DisqualifierCheck,
) -> tuple[Optional[PersonalizationVector], int, int, str, str]:
    """Returns (PersonalizationVector | None, input_tokens, output_tokens, model, provider)."""
    if not disqualifiers.all_clear or not triggers:
        return None, 0, 0, "skipped", "skipped"

    payload = {
        "lead": lead.model_dump(mode="json"),
        "archetype": archetype.model_dump(),
        "active_triggers": [t.model_dump() for t in triggers],
        "disqualifiers_checked": disqualifiers.model_dump(),
    }
    user = (
        f"Decision context JSON:\n```json\n{json.dumps(payload, default=str, indent=2)}\n```\n\n"
        "Return ONLY the personalization JSON object."
    )
    parsed, in_tok, out_tok, model, provider = chat_json(
        system=_load_personalize_prompt(), user=user, max_tokens=600
    )
    pv = PersonalizationVector.model_validate(parsed)
    return pv, in_tok, out_tok, model, provider


# ---- ACTION SELECTION ----

def recommend_action(
    score: int,
    band: str,
    disqualifiers: DisqualifierCheck,
    triggers: list[ActiveTrigger],
) -> RecommendedAction:
    if not disqualifiers.all_clear:
        # Find the first failing flag for the reason string.
        bad = [k for k, v in disqualifiers.model_dump().items() if v and k != "all_clear"]
        return RecommendedAction(
            next_step="drop_disqualified",
            priority="low",
            reasoning=f"Disqualified: {', '.join(bad) or 'unknown'}",
        )
    if band == "A":
        return RecommendedAction(
            next_step="send_email_seq_A",
            priority="high",
            reasoning=f"Score {score}, band A, {len(triggers)} active trigger(s). Hot.",
        )
    if band == "B":
        return RecommendedAction(
            next_step="send_email_seq_B",
            priority="medium",
            reasoning=f"Score {score}, band B. Warm — softer opener, no urgency frame.",
        )
    if band == "C":
        return RecommendedAction(
            next_step="human_review",
            priority="low",
            reasoning=f"Score {score}, band C. Borderline — surface to operator for override.",
        )
    return RecommendedAction(
        next_step="drop_disqualified",
        priority="low",
        reasoning=f"Score {score}, band D. Below threshold — do not contact this cycle.",
    )


def assemble_decision(
    lead: LeadProfile,
    archetype: Archetype,
    triggers: list[ActiveTrigger],
    disqualifiers: DisqualifierCheck,
    pv: Optional[PersonalizationVector],
    classify_in_tok: int,
    classify_out_tok: int,
    personalize_in_tok: int,
    personalize_out_tok: int,
    model: str,
    provider: str = "anthropic",
) -> Decision:
    score, band = compute_score(lead, archetype, triggers, disqualifiers)
    in_tok = classify_in_tok + personalize_in_tok
    out_tok = classify_out_tok + personalize_out_tok
    if provider in ("anthropic", "openai"):
        cost = cost_usd(in_tok, out_tok, provider)  # type: ignore[arg-type]
    else:
        cost = 0.0
    return Decision(
        lead_id=lead.lead_id,
        fit_score=score,
        fit_band=band,  # type: ignore[arg-type]
        archetype=archetype,
        active_triggers=triggers,
        disqualifiers_checked=disqualifiers,
        personalization_vector=pv,
        recommended_action=recommend_action(score, band, disqualifiers, triggers),
        metadata=Metadata(
            model=model,
            prompt_version=PROMPT_VERSION,
            scored_at=datetime.now(timezone.utc),
            input_token_count=in_tok,
            output_token_count=out_tok,
            cost_usd=round(cost, 4),
        ),
    )
