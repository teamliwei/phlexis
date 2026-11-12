# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""evaluate.py - Subsystem 3 CLI: deterministic statute evaluation (Step 5).

Loads the rule pack (IB-4 hash check against the case file if recorded) and the
grounding stage's FactContext JSON, evaluates every rule under Kleene three-valued
semantics, and writes the execution trace: every predicate with tier/polarity/
provenance, every rule and exception evaluated, gate outcomes, precedence
resolution, deontic findings (including INSUFFICIENT_GROUNDING).

Usage:
  uv run scripts/evaluate.py --pack packs/ra4136 --facts data/factcontext.json \
      [--out data/trace.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_ROOT / "lib"))

import kleene  # noqa: E402
from rulepack import fact_prov, fact_tier, fact_value, load_pack  # noqa: E402


def load_facts(path: Path):
    from harness_core import (EvidentiaryTier, FactContext, FactRecord,
                              QuoteStatus)
    data = json.loads(path.read_text(encoding="utf-8"))
    ctx = FactContext(case_id=data.get("case_id", ""),
                      dossier_sha256=data.get("dossier_sha256", ""))
    ctx.numbers = {k: (float(v) if v is not None else None)
                   for k, v in data.get("numbers", {}).items()}
    for name, rec in data.get("facts", {}).items():
        span = rec.get("span")
        ctx.facts[name] = FactRecord(
            predicate=name, value=rec.get("value"),
            quote=rec.get("quote", ""),
            quote_status=QuoteStatus(rec.get("quote_status", "UNVERIFIED")),
            quote_span=tuple(span) if span else None,
            tier=EvidentiaryTier(rec["tier"]) if rec.get("tier") else None,
            source="dossier", rationale=rec.get("rationale", ""))
    return data, ctx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", type=Path, default=APP_ROOT / "packs" / "ra4136")
    ap.add_argument("--facts", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=APP_ROOT / "data" / "trace.json")
    ap.add_argument("--expect-pack-sha", default=None,
                    help="IB-4: refuse to evaluate if pack hash differs")
    args = ap.parse_args()

    pack = load_pack(args.pack)
    if args.expect_pack_sha and args.expect_pack_sha != pack.sha256:
        print("IB-4 REFUSAL: rule pack hash mismatch (statute amended between "
              "sessions?)", flush=True)
        return 2

    raw, ctx = load_facts(args.facts)

    def fv(name):
        return fact_value(pack, ctx, name)

    trace = kleene.EvaluationTrace(pack_id=pack.pack_id, pack_sha256=pack.sha256)
    for rule in pack.rules:
        outcome = kleene.evaluate_rule(
            rule, fv,
            lambda n: fact_tier(pack, ctx, n),
            lambda n: fact_prov(pack, ctx, n),
            pack.exceptions_of(rule.rule_id))
        trace.rule_outcomes.append(outcome)
        trace.ungrounded_predicates.extend(
            po.name for po in outcome.predicates if po.value is None
            and po.name not in trace.ungrounded_predicates)

    def ser_po(po, required=None):
        deficient = False
        if required is not None and po.tier is not None:
            order = ["ASSERTED", "CORROBORATED", "DOCUMENTED"]
            deficient = order.index(po.tier) < order.index(required)
        return {"name": po.name, "value": po.value, "tier": po.tier,
                "provenance": po.provenance, "tier_deficient": deficient}

    def pred_outcomes(rule, preds):
        return [ser_po(p, pack.predicates[p.name].required_tier) for p in preds]

    out = {
        "pack_id": trace.pack_id, "pack_sha256": trace.pack_sha256,
        "dossier_sha256": raw.get("dossier_sha256"),
        "rule_outcomes": [{
            "rule_id": ro.rule_id, "description": ro.description,
            "predicates": pred_outcomes(ro, ro.predicates),
            "gate": ro.gate,
            "exceptions": [{
                "exception_id": e.exception_id, "gate": e.gate, "fired": e.fired,
                "predicates": pred_outcomes(ro, e.predicates)}
                for e in ro.exceptions],
            "finding": ro.finding} for ro in trace.rule_outcomes],
        "findings": trace.findings(),
        "ungrounded_predicates": trace.ungrounded_predicates,
        "primary_unknown": trace.primary_unknown(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(f"DONE evaluate: findings={out['findings']} "
          f"primary_unknown={out['primary_unknown']} -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
