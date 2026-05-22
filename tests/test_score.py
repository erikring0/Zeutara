"""Deterministic tests — no LLM calls. Run with: python -m pytest tests/ -q

Tests the scoring math and disqualifier logic. The LLM stages are tested
manually via the demo data (eyeball check on `examples/`).
"""
from datetime import date

from zeutara_engine.schemas import (
    LeadProfile, Company, Founder, Funding, Signals,
    Archetype, ActiveTrigger, JobPosting,
)
from zeutara_engine.normalize import check_disqualifiers, has_active_trigger
from zeutara_engine.score import compute_score


def _make_lead(**company_overrides) -> LeadProfile:
    base_company = dict(
        name="Acme Logistics",
        domain="acme.io",
        hq_city="New York, NY",
        hq_country="US",
        industry_tags=["B2B SaaS", "Logistics"],
        funding=Funding(
            last_round="Seed",
            last_round_amount_usd=4_500_000,
            last_round_date=date(2025, 9, 12),
            investors=["Index"],
        ),
        headcount=11,
        estimated_arr_usd=350_000,
    )
    base_company.update(company_overrides)
    return LeadProfile(
        lead_id="acme-test",
        company=Company(**base_company),
        founders=[
            Founder(
                name="Priya Shah",
                title="CEO & Co-founder",
                background="ex-Google SWE 6yrs, ex-Stripe PM 3yrs, MIT CS",
                bio_text="Building the OS for mid-market freight forwarders.",
                is_ceo=True,
            )
        ],
        signals=Signals(
            open_gtm_roles=[
                JobPosting(title="Head of Growth", posted=date(2026, 4, 22))
            ]
        ),
    )


def test_disqualifier_clean_lead():
    lead = _make_lead()
    flags = check_disqualifiers(lead, today=date(2026, 5, 20))
    assert flags.all_clear is True


def test_disqualifier_vp_sales_kills():
    lead = _make_lead(has_vp_sales=True)
    flags = check_disqualifiers(lead, today=date(2026, 5, 20))
    assert flags.all_clear is False
    assert flags.has_vp_sales is True


def test_disqualifier_arr_too_high():
    lead = _make_lead(estimated_arr_usd=4_000_000)
    flags = check_disqualifiers(lead, today=date(2026, 5, 20))
    assert flags.arr_too_high is True
    assert flags.all_clear is False


def test_disqualifier_out_of_geo():
    lead = _make_lead(hq_country="Other")
    flags = check_disqualifiers(lead, today=date(2026, 5, 20))
    assert flags.out_of_geo is True
    assert flags.all_clear is False


def test_score_disqualified_returns_zero():
    lead = _make_lead(has_vp_sales=True)
    flags = check_disqualifiers(lead, today=date(2026, 5, 20))
    archetype = Archetype(type="Type A — Technical Founder", confidence=0.95, evidence="ex-Google SWE")
    triggers = [ActiveTrigger(trigger="open_gtm_role", detail="Head of Growth", weight=0.45)]
    score, band = compute_score(lead, archetype, triggers, flags)
    assert score == 0
    assert band == "D"


def test_score_strong_fit_band_a():
    lead = _make_lead()
    flags = check_disqualifiers(lead, today=date(2026, 5, 20))
    archetype = Archetype(type="Type A — Technical Founder", confidence=0.95, evidence="ex-Google SWE")
    triggers = [
        ActiveTrigger(trigger="open_gtm_role", detail="Head of Growth", weight=0.45),
        ActiveTrigger(trigger="public_pain_statement", detail="Podcast", weight=0.40),
    ]
    score, band = compute_score(lead, archetype, triggers, flags)
    assert score >= 75
    assert band == "A"


def test_score_type_b_founder_low():
    lead = _make_lead()
    flags = check_disqualifiers(lead, today=date(2026, 5, 20))
    archetype = Archetype(type="Type B — Commercial Founder", confidence=0.9, evidence="ex-VP Sales")
    triggers = [ActiveTrigger(trigger="open_gtm_role", detail="x", weight=0.45)]
    score, band = compute_score(lead, archetype, triggers, flags)
    # No archetype credit for Type B → score capped well below A
    assert score < 55
    assert band in ("C", "D")


def test_active_trigger_detection():
    lead = _make_lead()
    assert has_active_trigger(lead, today=date(2026, 5, 20)) is True


def test_no_active_trigger_returns_false():
    lead = _make_lead(headcount=11)
    lead.signals.open_gtm_roles = []
    # last_round_date 2025-09-12 → ~8mo ago at 2026-05-20 → in window, no GTM hires
    # so trigger (c) stale_seed_no_gtm WILL fire. Move date out of window:
    lead.company.funding.last_round_date = date(2025, 1, 1)
    assert has_active_trigger(lead, today=date(2026, 5, 20)) is False
