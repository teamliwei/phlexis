# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""arbitrate.py - Subsystem 4 CLI: argument synthesis, arbitration, emission.

Steps 6-8 of the operational protocol (plan v3 section 7):
  STEP 6  trace -> prosecution nodes; exceptions -> defense rebuttals
          (burden = proponent); precedent boundaries -> undercuts
  STEP 7  grounded labeling -> structural proof-standard filter -> disposition
  STEP 8  hash-chained audit events + case record with reproducibility data

Usage:
  uv run scripts/arbitrate.py --trace data/trace.json --facts data/factcontext.json \
      [--precedents data/smoke_retrieval.json] [--standard beyond_reasonable_doubt] \
      [--out data/case_result.json] [--ledger data/audit.jsonl]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_ROOT / "lib"))

from argumentation import (Argument, ArgumentGraph, AttackKind,  # noqa: E402
                           Role)
from audit import AuditLedger  # noqa: E402
from harness_core import AuditRecord, Disposition, EvidentiaryTier  # noqa: E402
from prooffilter import ProofStandard, disposition  # noqa: E402


def synthesize(trace: dict, facts: dict,
               precedents: dict | None) -> tuple[ArgumentGraph, str]:
    """Build the graph from the execution trace. Nothing may assert a rule
    outcome absent from the trace - nodes reference trace rule/exception ids."""
    g = ArgumentGraph()
    primary = trace["rule_outcomes"][0]["rule_id"] if trace["rule_outcomes"] else ""
    claim_id = "claim"
    g.add(Argument(id=claim_id,
                   claim=f"primary rule {primary} fires",
                   role=Role.PROSECUTION,
                   supported_by_trace=primary,
                   tier=EvidentiaryTier.DOCUMENTED.value))
    for ro in trace["rule_outcomes"]:
        for ex in ro["exceptions"]:
            # the defense may always argue the exception; whether it survives
            # depends on its premises being trace-clean
            aid = f"defense_{ex['exception_id']}"
            g.add(Argument(id=aid,
                           claim=f"exception {ex['exception_id']}",
                           role=Role.DEFENSE,
                           supported_by_trace=f"{ro['rule_id']}/{ex['exception_id']}",
                           tier=_min_tier(facts, ex["predicates"])))
            g.attack(aid, claim_id, AttackKind.REBUTTAL)
            if not ex["fired"]:
                # trace undercuts: every exception predicate that is unknown or
                # evidentiary-tier-deficient attacks the defense argument
                # (burden = proponent: an unproven exception fails)
                for p in ex["predicates"]:
                    if p["value"] is None or p.get("tier_deficient"):
                        uid = (f"undercut_{ro['rule_id']}_{ex['exception_id']}"
                               f"_{p['name']}")
                        why = ("unknown" if p["value"] is None
                               else f"tier deficient ({p['tier']})")
                        g.add(Argument(
                            id=uid,
                            claim=f"predicate {p['name']} unproven: {why}",
                            role=Role.PRECEDENT_UNDERCUT,
                            supported_by_trace=f"{ro['rule_id']}/{ex['exception_id']}/{p['name']}",
                            tier=EvidentiaryTier.DOCUMENTED.value))
                        g.attack(uid, aid, AttackKind.UNDERCUT)
    if precedents:
        for i, p in enumerate(precedents.get("shortlist", [])[:5]):
            aid = f"prec_{i}"
            g.add(Argument(id=aid,
                           claim=f"precedent {p['gr_no']}: {p['passage_text'][:80]}",
                           role=Role.PRECEDENT_UNDERCUT, kind="precedent"))
            # a liability-affirming precedent undercuts the defense, and
            # vice versa; ambiguous precedents undercut nothing
            if p.get("polarity") == "LIABILITY_NEGATING":
                for aid_def in [a.id for a in g.arguments.values()
                                if a.role is Role.DEFENSE]:
                    g.attack(aid, aid_def, AttackKind.UNDERCUT)
    return g, claim_id


def _min_tier(facts: dict, predicates: list[dict]) -> str:
    order = [None, EvidentiaryTier.ASSERTED.value,
             EvidentiaryTier.CORROBORATED.value, EvidentiaryTier.DOCUMENTED.value]
    worst = 0
    for p in predicates:
        rec = facts.get("facts", {}).get(p["name"], {})
        tier = rec.get("tier")
        if tier in order:
            worst = max(worst, order.index(tier))
    return order[worst] or EvidentiaryTier.ASSERTED.value


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", type=Path, required=True)
    ap.add_argument("--facts", type=Path, required=True)
    ap.add_argument("--precedents", type=Path, default=None)
    ap.add_argument("--standard", default="beyond_reasonable_doubt",
                    choices=["preponderance", "clear_and_convincing",
                             "beyond_reasonable_doubt"])
    ap.add_argument("--out", type=Path, default=APP_ROOT / "data" / "case_result.json")
    ap.add_argument("--ledger", type=Path, default=APP_ROOT / "data" / "audit.jsonl")
    args = ap.parse_args()

    trace = json.loads(args.trace.read_text(encoding="utf-8"))
    facts = json.loads(args.facts.read_text(encoding="utf-8"))
    precedents = (json.loads(args.precedents.read_text(encoding="utf-8"))
                  if args.precedents and args.precedents.exists() else None)

    g, claim_id = synthesize(trace, facts, precedents)
    labels = g.label()
    disp, why = disposition(g, labels, claim_id,
                            ProofStandard(args.standard),
                            primary_unknown=trace.get("primary_unknown", False))

    result = {
        "case_id": facts.get("case_id", ""),
        "dossier_sha256": trace.get("dossier_sha256"),
        "pack_id": trace["pack_id"], "pack_sha256": trace["pack_sha256"],
        "standard": args.standard,
        "disposition": disp.value, "reason": why,
        "labels": {aid: lab.value for aid, lab in labels.items()},
        "graph": {"arguments": [
            {"id": a.id, "claim": a.claim, "role": a.role.value,
             "trace": a.supported_by_trace, "tier": a.tier}
            for a in g.arguments.values()],
            "attacks": sorted(f"{a}->{b}" for a, b in g.attacks)},
        "findings": trace.get("findings", []),
        "injection_flags": facts.get("injection_flags", []),
        "grounding_events": facts.get("events", []),
        "reproducibility": {
            "pack_sha256": trace["pack_sha256"],
            "retrieval_model": (precedents or {}).get("note")
            and "sentence-transformers/all-MiniLM-L6-v2" or None,
            "precedents_file": str(args.precedents) if args.precedents else None},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False),
                        encoding="utf-8")

    ledger = AuditLedger(args.ledger)
    ledger.append(AuditRecord(
        event_type="ARBITRATION_COMPLETE", case_id=result["case_id"],
        payload={"disposition": disp.value, "standard": args.standard,
                 "labels": result["labels"],
                 "pack_sha256": trace["pack_sha256"][:16]}))
    print(f"DONE arbitrate: {disp.value} ({why}) -> {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
