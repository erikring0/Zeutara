"""CLI: `zeutara-engine score <input-glob> --out <dir>`

End-to-end: read LeadProfile JSON files, run the 3-stage engine, write
Decision JSON files, print a summary table.
"""
from __future__ import annotations
import argparse
import glob as glob_mod
import json
import os
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Iterable

from .schemas import LeadProfile, Decision, Archetype, ActiveTrigger
from .normalize import check_disqualifiers
from .classify import classify
from .score import personalize, assemble_decision


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader — no python-dotenv dependency."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if v and not v.endswith("...") and k not in os.environ:
            os.environ[k] = v


def _expand_inputs(patterns: Iterable[str]) -> list[Path]:
    paths: list[Path] = []
    for pat in patterns:
        matches = glob_mod.glob(pat, recursive=True)
        if not matches:
            print(f"  warning: no files match {pat}", file=sys.stderr)
        for m in matches:
            p = Path(m)
            if p.is_file() and p.suffix.lower() == ".json":
                paths.append(p)
    return sorted(set(paths))


def _score_one(lead: LeadProfile) -> Decision:
    """Run all three stages on one lead."""
    flags = check_disqualifiers(lead)

    if not flags.all_clear:
        # Short-circuit: skip LLM entirely for disqualified leads.
        archetype = Archetype(
            type="Mixed / Unclear",
            confidence=0.0,
            evidence="Skipped — disqualified at Stage 1.",
        )
        triggers: list[ActiveTrigger] = []
        return assemble_decision(
            lead, archetype, triggers, flags, None, 0, 0, 0, 0, "stage1-only"
        )

    cls = classify(lead)
    pv, p_in, p_out, model_p, provider_p = personalize(
        lead, cls["archetype"], cls["active_triggers"], flags
    )
    provider = provider_p if provider_p != "skipped" else cls["provider"]
    model = model_p if model_p != "skipped" else cls["model"]
    return assemble_decision(
        lead,
        cls["archetype"],
        cls["active_triggers"],
        flags,
        pv,
        cls["input_tokens"],
        cls["output_tokens"],
        p_in,
        p_out,
        model,
        provider=provider,
    )


def _print_summary(decisions: list[Decision]) -> None:
    rows = []
    for d in decisions:
        rows.append(
            (
                d.lead_id[:34].ljust(34),
                str(d.fit_score).rjust(5),
                d.fit_band.center(6),
                str(len(d.active_triggers)).center(10),
                d.recommended_action.next_step,
            )
        )
    print()
    print("Lead                              Score   Band   Triggers   Action")
    print("-" * 88)
    for r in rows:
        print("  ".join(r))
    print()
    total_cost = sum(d.metadata.cost_usd for d in decisions)
    a_b = sum(1 for d in decisions if d.fit_band in ("A", "B"))
    print(f"Scored {len(decisions)} leads | A/B count: {a_b} | total LLM cost: ${total_cost:.4f}")


def _json_default(o):
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    raise TypeError(f"Cannot serialize {type(o)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zeutara-engine")
    sub = parser.add_subparsers(dest="cmd", required=True)
    score_p = sub.add_parser("score", help="Score a batch of LeadProfile JSON files")
    score_p.add_argument("inputs", nargs="+", help="Input JSON files or globs")
    score_p.add_argument("--out", default="outputs", help="Output directory")
    score_p.add_argument("--no-llm", action="store_true", help="Stage 1 only (offline mode)")

    args = parser.parse_args(argv)

    # Load .env from CWD if present.
    _load_dotenv(Path(".env"))

    if args.cmd == "score":
        if not args.no_llm and not (
            os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
        ):
            print(
                "ERROR: no LLM provider key set. Add ANTHROPIC_API_KEY or OPENAI_API_KEY to .env, or use --no-llm.",
                file=sys.stderr,
            )
            return 2

        inputs = _expand_inputs(args.inputs)
        if not inputs:
            print("ERROR: no input files found.", file=sys.stderr)
            return 2

        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)

        decisions: list[Decision] = []
        for path in inputs:
            lead = LeadProfile.model_validate_json(path.read_text(encoding="utf-8"))
            try:
                if args.no_llm:
                    flags = check_disqualifiers(lead)
                    archetype = Archetype(
                        type="Mixed / Unclear",
                        confidence=0.0,
                        evidence="Stage 1 only (--no-llm).",
                    )
                    decision = assemble_decision(
                        lead, archetype, [], flags, None, 0, 0, 0, 0, "stage1-only"
                    )
                else:
                    decision = _score_one(lead)
            except Exception as e:
                print(f"  ERROR scoring {path.name}: {e}", file=sys.stderr)
                continue

            out_path = out_dir / f"{lead.lead_id}.decision.json"
            out_path.write_text(
                json.dumps(decision.model_dump(mode="json"), indent=2, default=_json_default),
                encoding="utf-8",
            )
            decisions.append(decision)
            print(f"  scored: {lead.lead_id} -> {out_path}")

        _print_summary(decisions)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
