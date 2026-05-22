# Zeutara Founder-Fit Decision Engine

**The load-bearing component of Zeutara's outbound BD pipeline.**
A 3-stage scoring engine that takes a `LeadProfile` (firmographic + signal data) and
emits a `Decision` (fit score, archetype, active triggers, personalization vector,
recommended next step). Built as the prototype deliverable for the Zeutara Analyst
Screening take-home.

> **Why this is the load-bearing component, not the CRM or the email tool:**
> Calibration data accumulates here. Every reply, every booked call, every closed-won
> labels back to a `Decision` and tunes the rubric. The CRM stores rows; the email
> tool moves bytes; this engine is the only place where reply rates compound over
> time. Remove it and the pipeline collapses from ~8% positive reply to <1%.

---

## Quickstart (clone-to-output in <5 minutes)

```bash
git clone <this-repo> zeutara-decision-engine

python -m venv .venv
. .venv/bin/activate         # Windows: .\.venv\Scripts\activate

pip install -e ".[dev]"      # installs deps from pyproject.toml (incl. pytest) + registers the `zeutara-engine` CLI
                             # alternative: pip install -r requirements.txt && pip install -e . --no-deps

# Offline demo — no API key needed. Validates Stage 1 (deterministic disqualifiers).
zeutara-engine score "examples/*.json" --no-llm --out out

# Full demo — requires an Anthropic OR OpenAI key (provider auto-detected).
cp .env.example .env         # then edit .env and paste ONE key
zeutara-engine score "examples/*.json" --out out
```

Output is one `<lead_id>.decision.json` per input lead in `out/`, plus a summary
table to stdout.

---

## What it does

```
LeadProfile (JSON in)
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 1 — NORMALIZE  (deterministic, no LLM, ~1ms/lead)     │
│   • check 8 hard disqualifiers (VP Sales, retained agency,  │
│     pre-product, bootstrapped, ex-sales founder, vintage,   │
│     geo, ARR ceiling)                                       │
│   • fast-fail any lead that violates the locked ICP cut     │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 2 — CLASSIFY  (LLM, structured JSON, ~$0.05/lead)     │
│   • founder archetype: Type A / Type B / Mixed              │
│     (Type A = technical founder doing sales reluctantly;    │
│      Type B = commercial founder; Mixed = unclear)          │
│   • active trigger events (4 weighted: GTM hire, public     │
│     pain statement, recent funding + no VP Sales, growth    │
│     stall signals)                                          │
│   • confidence + evidence quote for every claim             │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ Stage 3 — SCORE + PERSONALIZE  (deterministic + LLM)        │
│   • compute_score(): 0-100, banded A/B/C/D                  │
│       Archetype  50pts × confidence (Type A=1.0, Mixed=0.4) │
│       Triggers   35pts cap, weighted sum                    │
│       Headcount  5pts | ARR  5pts | Recency  5pts           │
│   • personalize(): only for non-disqualified, trigger-      │
│     positive leads. Outputs angle + opener + CTA. EVERY     │
│     element MUST cite evidence Stage 2 already surfaced     │
│     — no fabricated facts.                                  │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
Decision (JSON out)
```

**Bands → action:**
- **A (≥75)** → schedule for hand-written outbound this week
- **B (≥55)** → standard sequence, founder send
- **C (≥35)** → nurture / re-score in 30 days
- **D (<35) or disqualified** → drop, do not re-source

**Cost at expected volume** (650 leads/year through full pipeline):
- Stage 1: free
- Stage 2 + 3 LLM: ~$0.10/lead × 650 = **~$65/year**
- Buffer for re-scores + experiments: **$184/year budgeted** (Anthropic line item)

---

## Demo data — what each lead is meant to demonstrate

The 10 examples are a deliberate fixture set, vertical-anchored to logistics-tech
to match Zeutara's published case study #1.

| # | Lead | Designed outcome | What it tests |
|---|---|---|---|
| 01 | Priya Shah / Acme Logistics | **A** | Multi-trigger Type A: ex-Google/Stripe engineer, public pain quote, open Head of Growth role, no VP Sales |
| 02 | Marcus Wei / Stellar Freight | **A** | Type A with single strong trigger (founding AE role), recent seed |
| 03 | Aisha Okafor / Routelane | **B/C** | Type A but light on triggers — no GTM hire, no public statements |
| 04 | David Park / CargoSense | **A** | Strong Type A signal in bio + LinkedIn pain post + open GTM role |
| 05 | Elena Volkov / Trakr | **C** | Type A but ARR too low + no triggers — "right founder, wrong moment" |
| 06 | Jordan Bell / Payloop | **B** | Type A, GTM role posted >60d ago (stale trigger) — tests recency weighting |
| 07 | Sam Rivera / FlexBroker | **disqualified** | Has VP Sales — hard fail at Stage 1 |
| 08 | Hudson Grant / LedgerLane | **disqualified** | Has retained agency <6mo — hard fail at Stage 1 |
| 09 | Rachel Gold / ShipSharp | **disqualified (trap)** | Looks great firmographically (B2B SaaS, ARR ~$1M, recent seed). Founder is ex-Salesforce AE — Type B disguised as Type A. The whole point of the engine: **scoring on firmographics alone would put her in band A and waste a Strategic Briefing slot.** |
| 10 | Noor Haddad / PortPilot | **A** | Multi-trigger Type A in maritime sub-vertical, recent founding GTM hire post + Twitter pain quote |

**Run `zeutara-engine score "examples/*.json" --out out` and check that #09
disqualifies and #01/#04/#10 land in band A.** That is the demo.

---

## Project layout

```
zeutara-decision-engine/
├── pyproject.toml
├── .env.example
├── README.md
├── src/zeutara_engine/
│   ├── schemas.py         # LeadProfile + Decision pydantic models
│   ├── normalize.py       # Stage 1 deterministic disqualifiers
│   ├── classify.py        # Stage 2 Anthropic LLM call
│   ├── score.py           # Stage 3 deterministic score + LLM personalize
│   ├── cli.py             # `zeutara-engine score` entry point
│   └── prompts/
│       ├── classify.txt
│       └── personalize.txt
├── examples/              # 10 demo LeadProfile JSON files
└── tests/test_score.py    # 9 deterministic tests, no LLM calls
```

Run tests: `pytest tests/ -q`

---

## Configuration

Copy `.env.example` to `.env` and set:

- `ANTHROPIC_API_KEY` — required for full pipeline. Skip with `--no-llm` for
  Stage-1-only runs.
- `ANTHROPIC_MODEL` — defaults to `claude-sonnet-4-5`. Swap to `claude-haiku-*`
  to drop cost ~5x at the price of trigger-detection recall.

---

## Schemas (the contract)

`LeadProfile` is what every upstream sourcing tool (Crunchbase, Sales Navigator,
Phantombuster, Apollo, Clay) must produce. `Decision` is what every downstream
outbound tool (Smartlead, Heyreach, Attio CRM) consumes. Stable schemas mean
upstream/downstream vendors are swappable; the engine is not.

See `src/zeutara_engine/schemas.py` for full pydantic v2 definitions.

---

## If I had two more days

These are the things I deliberately cut to ship a clone-to-output prototype.
They are ranked by load-bearing impact, not effort.

1. **Calibration loop.** Persist every `Decision` to SQLite with a `label`
   column (`booked_call`, `replied_positive`, `replied_negative`, `bounced`,
   `closed_won`). Weekly job: pull last 90 days of labels, compute
   precision/recall on band A, surface drift in any of the 4 trigger weights.
   Without this, every other improvement is hand-wavy.
2. **Active-trigger calculus over time, not just snapshot.** Today the engine
   sees one frame of the company. The real signal is *acceleration* — GTM role
   posted AND still open after 30 days, ARR doubled in 60 days, headcount
   inflected. Re-score every lead on a 14-day cadence; only triggers with a
   freshness-weighted derivative count for personalization.
3. **Multi-tenant ICP segments.** Today the disqualifier constants are module
   globals. Move them to a YAML config keyed by `segment_id` so we can run
   logistics-tech, devtools, and vertical-AI as parallel pipelines without
   forking the codebase. This is the literal architectural response to the 5x
   failure mode (ICP leakage) defended in the paper.
4. **Evidence-citation enforcement at the parser level.** Today the
   personalize prompt *asks* for evidence citations; nothing rejects a
   Decision that violates the invariant. Add a post-LLM validator that
   parses every `personalization_vector` element and hard-rejects any claim
   not present in `active_triggers`. Re-prompt or downgrade the band.
5. **Anthropic Batch API for bulk re-scoring.** The provider-agnostic LLM
   adapter (`llm.py`) is shipped and tested with both Anthropic and OpenAI;
   what's still missing is the *batch* code path on either side. Right now
   Stage 2 is per-lead sync calls. At 5x volume that costs latency, not
   dollars. Anthropic Batch gives 50% off list price and fits the weekly
   re-score cadence cleanly.
6. **Better ex-sales-founder detection.** The Stage 1 heuristic is keyword-based
   and brittle (a previous version's `"cro"` token substring-matched
   "Mi**cro**soft" — caught and patched with regex word boundaries during dev).
   The right fix is to replace it entirely with a Stage 2 sub-prompt that reads
   the founder LinkedIn employment history and returns
   `{role_taxonomy: technical|commercial|operations, confidence}`.
7. **Smartlead webhook → calibration loop.** Two-way sync: positive replies
   POST back into the same SQLite + bump the score on adjacent leads at the
   same company. Shrinks the time-to-first-feedback from "weekly review" to
   "minutes."
8. **Public-facing LeadProfile validator endpoint.** A tiny FastAPI service
   that accepts a Crunchbase-style payload and returns `{is_valid, missing_fields}`.
   This becomes the integration test every upstream vendor must pass before its
   data enters the pipeline. Cheap to build; massive ICP-discipline payoff.

---

## What this prototype is **not**

- Not a CRM. It writes JSON to disk; production lives in Attio.
- Not an email tool. Smartlead and Heyreach do that and do it well.
- Not a sourcing tool. Crunchbase + Sales Nav + Phantombuster produce the
  `LeadProfile` upstream.
- Not an "AI agent" in the chatbot sense. The LLM here is a structured-output
  classifier with two tightly-scoped prompts — not a free-form actor with tools.
  That choice is defended in the accompanying paper.

— checked by user-profile instructions
