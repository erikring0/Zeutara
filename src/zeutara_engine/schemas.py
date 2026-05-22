"""Pydantic schemas for LeadProfile (input) and Decision (output).

These are the contracts the engine speaks. Every upstream source produces
LeadProfile; every downstream consumer (Smartlead, Attio, Heyreach) reads
Decision.
"""
from __future__ import annotations
from datetime import date, datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, HttpUrl


# ---------- INPUT: LeadProfile ----------

class Funding(BaseModel):
    last_round: Literal["Pre-seed", "Seed", "Series A", "Series B", "Other"]
    last_round_amount_usd: int
    last_round_date: date
    investors: list[str] = []


class Company(BaseModel):
    name: str
    domain: str
    linkedin: Optional[str] = None
    crunchbase: Optional[str] = None
    hq_city: str
    hq_country: Literal["US", "CA", "Other"]
    industry_tags: list[str]
    funding: Funding
    headcount: int
    headcount_30d_change: int = 0
    estimated_arr_usd: Optional[int] = None
    has_vp_sales: bool = False
    has_retained_agency_6mo: bool = False
    is_pre_product: bool = False
    is_bootstrapped: bool = False


class Founder(BaseModel):
    name: str
    title: str
    linkedin: Optional[str] = None
    github: Optional[str] = None
    background: str = Field(
        ...,
        description="Short prose: prior roles, education, anything signalling archetype",
    )
    bio_text: str = ""
    is_ceo: bool = False


class JobPosting(BaseModel):
    title: str
    posted: date
    url: Optional[str] = None


class GtmHire(BaseModel):
    name: str
    title: str
    started: date


class PublicStatement(BaseModel):
    source: Literal["podcast", "blog", "twitter", "linkedin_post", "press"]
    url: Optional[str] = None
    date: date
    transcript_excerpt: str


class Signals(BaseModel):
    open_gtm_roles: list[JobPosting] = []
    recent_gtm_hires_60d: list[GtmHire] = []
    public_statements_30d: list[PublicStatement] = []
    github_commit_activity_90d: Literal["active", "moderate", "inactive", "unknown"] = "unknown"


class LeadProfile(BaseModel):
    lead_id: str
    company: Company
    founders: list[Founder]
    signals: Signals = Field(default_factory=Signals)


# ---------- OUTPUT: Decision ----------

class Archetype(BaseModel):
    type: Literal[
        "Type A — Technical Founder",
        "Type B — Commercial Founder",
        "Mixed / Unclear",
    ]
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence: str


class ActiveTrigger(BaseModel):
    trigger: Literal[
        "open_gtm_role",
        "recent_first_gtm_hire",
        "stale_seed_no_gtm",
        "public_pain_statement",
    ]
    detail: str
    weight: float = Field(..., ge=0.0, le=1.0)


class DisqualifierCheck(BaseModel):
    has_vp_sales: bool
    retained_agency: bool
    pre_product: bool
    bootstrapped: bool
    ex_sales_founder: bool
    last_raise_too_old: bool
    out_of_geo: bool
    arr_too_high: bool
    all_clear: bool


class PersonalizationVector(BaseModel):
    hook: str = Field(..., description="The single most specific opener anchor")
    case_study_match: str = Field(
        ..., description="Which Zeutara case study to reference"
    )
    named_pain: str
    recommended_angle: str
    do_not_mention: list[str] = []


class RecommendedAction(BaseModel):
    next_step: Literal[
        "send_email_seq_A",
        "send_email_seq_B",
        "linkedin_warm_first",
        "human_review",
        "drop_disqualified",
    ]
    priority: Literal["high", "medium", "low"]
    reasoning: str


class Metadata(BaseModel):
    model: str
    prompt_version: str
    scored_at: datetime
    input_token_count: int = 0
    output_token_count: int = 0
    cost_usd: float = 0.0


class Decision(BaseModel):
    lead_id: str
    fit_score: int = Field(..., ge=0, le=100)
    fit_band: Literal["A", "B", "C", "D"]
    archetype: Archetype
    active_triggers: list[ActiveTrigger]
    disqualifiers_checked: DisqualifierCheck
    personalization_vector: Optional[PersonalizationVector] = None  # None when disqualified
    recommended_action: RecommendedAction
    metadata: Metadata
