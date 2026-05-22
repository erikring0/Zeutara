"""Stage 1 — NORMALIZE.

Deterministic. No LLM. Computes derived features and runs hard disqualifier
checks. If a lead is disqualified here, the engine short-circuits and never
spends LLM tokens on it. This is also the only stage that runs when LLM is
unavailable (degraded mode).
"""
from __future__ import annotations
from datetime import date, timedelta
from .schemas import LeadProfile, DisqualifierCheck


# Locked ICP geography — anything outside is auto-dropped.
ALLOWED_COUNTRIES = {"US", "CA"}

# Locked ICP funding window: closed seed 4–10 months ago.
SEED_VINTAGE_MIN_DAYS = 30 * 4
SEED_VINTAGE_MAX_DAYS = 30 * 10

# ARR ceiling per locked ICP (post-website calibration).
ARR_CEILING_USD = 3_000_000

# Last-raise staleness ceiling.
LAST_RAISE_MAX_AGE_DAYS = 30 * 12


def check_disqualifiers(lead: LeadProfile, today: date | None = None) -> DisqualifierCheck:
    """Run all hard disqualifier checks. No LLM. Pure logic."""
    today = today or date.today()
    c = lead.company

    last_raise_age_days = (today - c.funding.last_round_date).days

    # ex-sales founder check is heuristic on the bio — the LLM stage will refine,
    # but we run a cheap keyword guard here too. Use regex word boundaries so
    # short tokens like "cro" don't substring-match "Microsoft".
    import re
    ceo_bg = " ".join(
        f"{f.title} {f.background} {f.bio_text}".lower()
        for f in lead.founders
        if f.is_ceo
    )
    sales_keywords = (
        r"\bvp\s+sales\b",
        r"\bvp\s+of\s+sales\b",
        r"\bhead\s+of\s+sales\b",
        r"\bchief\s+revenue\b",
        r"\bcro\b",
        r"\baccount\s+executive\b",
        r"\bsales\s+(lead|rep|representative|director|manager)\b",
        r"\bex-?salesforce\s+(ae|account\s+executive|senior\s+account\s+executive)\b",
        r"\bsenior\s+account\s+executive\b",
    )
    is_ex_sales_founder = any(re.search(k, ceo_bg) for k in sales_keywords)

    arr_too_high = (c.estimated_arr_usd or 0) > ARR_CEILING_USD
    out_of_geo = c.hq_country not in ALLOWED_COUNTRIES
    last_raise_too_old = (
        last_raise_age_days > LAST_RAISE_MAX_AGE_DAYS
        and c.funding.last_round != "Series A"
    )

    flags = DisqualifierCheck(
        has_vp_sales=c.has_vp_sales,
        retained_agency=c.has_retained_agency_6mo,
        pre_product=c.is_pre_product,
        bootstrapped=c.is_bootstrapped,
        ex_sales_founder=is_ex_sales_founder,
        last_raise_too_old=last_raise_too_old,
        out_of_geo=out_of_geo,
        arr_too_high=arr_too_high,
        all_clear=False,
    )
    flags.all_clear = not any(
        [
            flags.has_vp_sales,
            flags.retained_agency,
            flags.pre_product,
            flags.bootstrapped,
            flags.ex_sales_founder,
            flags.last_raise_too_old,
            flags.out_of_geo,
            flags.arr_too_high,
        ]
    )
    return flags


def has_active_trigger(lead: LeadProfile, today: date | None = None) -> bool:
    """Cheap pre-LLM gate: does ANY raw trigger fire? If not, score is auto-low."""
    today = today or date.today()
    sig = lead.signals

    # (a) open GTM role <45 days
    if any((today - jp.posted).days <= 45 for jp in sig.open_gtm_roles):
        return True
    # (b) hired first GTM person <60 days
    if any((today - h.started).days <= 60 for h in sig.recent_gtm_hires_60d):
        return True
    # (c) stale seed (4–10mo) with zero GTM headcount
    last_raise_days = (today - lead.company.funding.last_round_date).days
    in_window = SEED_VINTAGE_MIN_DAYS <= last_raise_days <= SEED_VINTAGE_MAX_DAYS
    if in_window and not sig.recent_gtm_hires_60d and not sig.open_gtm_roles:
        return True
    # (d) public pain statement <30 days
    if any((today - p.date).days <= 30 for p in sig.public_statements_30d):
        return True
    return False
