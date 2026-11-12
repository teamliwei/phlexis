"""harness_core.py - domain types shared by every harness stage.

Pure stdlib. Everything downstream of Step 5 (statute evaluation, argumentation,
labeling, proof filtering) is deterministic and depends only on this module plus
the other lib modules. Third-party deps live exclusively in scripts/ PEP 723
headers (plan: docs/kraft-legal-implementation-plan-v3.md).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------- enums

class EvidentiaryTier(str, Enum):
    DOCUMENTED = "DOCUMENTED"      # instrument/record in the dossier
    CORROBORATED = "CORROBORATED"  # observation consistent with an independent item
    ASSERTED = "ASSERTED"          # a party's own claim only


class QuoteStatus(str, Enum):
    VERIFIED = "VERIFIED"            # tier 1 exact / tier 2 <=2-edit containment
    VERIFIED_FUZZY = "VERIFIED_FUZZY"  # tier 3 trigram overlap, surfaced as fuzzy
    UNVERIFIED = "UNVERIFIED"        # purged to unknown, never persisted as fact


class Polarity(str, Enum):
    LIABILITY_AFFIRMING = "LIABILITY_AFFIRMING"
    LIABILITY_NEGATING = "LIABILITY_NEGATING"
    AMBIGUOUS = "AMBIGUOUS"


class BindingTier(str, Enum):
    SC_BINDING = "SC_BINDING"          # SC en banc / division: binds
    SC_PERSUASIVE = "SC_PERSUASIVE"    # SC resolutions etc.: persuasive
    OTHER = "OTHER"                    # CA, Sandiganbayan: persuasive at best
    FOREIGN = "FOREIGN"


class Disposition(str, Enum):
    LIABILITY_ESTABLISHED = "LIABILITY_ESTABLISHED"
    NO_LIABILITY = "NO_LIABILITY"
    IMMUNITY = "IMMUNITY"
    INSUFFICIENT_GROUNDING = "INSUFFICIENT_GROUNDING"
    UNDECIDED = "UNDECIDED"


class Label(str, Enum):
    IN = "IN"
    OUT = "OUT"
    UNDECIDED = "UNDECIDED"


# Three-valued fact value: True / False / None (= unknown). Kleene semantics live
# in kleene.py; None never means "false" anywhere in the pipeline.


# ---------------------------------------------------------------- json/hash

def canonical_json(obj: Any) -> str:
    """Stable serialization used for hashing and ledger chaining."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- domain records

@dataclass
class FactRecord:
    """One extracted fact with full provenance. value=None means unknown."""
    predicate: str
    value: Optional[bool]            # True / False / None (unknown)
    quote: str = ""                  # verbatim dossier quote (required pre-verification)
    quote_status: QuoteStatus = QuoteStatus.UNVERIFIED
    quote_span: Optional[tuple[int, int]] = None  # (start, end) in normalized dossier
    tier: Optional[EvidentiaryTier] = None
    source: str = ""                 # dossier document id / span reference
    rationale: str = ""              # LLM analogy rationale for discretionary binds
    precedent_citations: list[str] = field(default_factory=list)

    def purged(self) -> bool:
        return self.value is None or self.quote_status is QuoteStatus.UNVERIFIED


@dataclass
class FactContext:
    """The verified fact set for one case. Only verified records belong here;
    unverified extraction output is purged to unknown before construction."""
    case_id: str
    dossier_sha256: str
    facts: dict[str, FactRecord] = field(default_factory=dict)
    injection_flags: list[str] = field(default_factory=list)
    numbers: dict[str, Optional[float]] = field(default_factory=dict)  # numeric facts
    events: list[dict] = field(default_factory=list)  # IB-2/IB-3/IB-5 audit events

    def value_of(self, predicate: str) -> Optional[bool]:
        rec = self.facts.get(predicate)
        return None if rec is None else rec.value


@dataclass
class PrecedentBoundary:
    """Output of the retrieval pipeline: one precedent-backed factual boundary."""
    citation: str
    holding_quote: str
    holding_span: Optional[tuple[int, int]] = None
    polarity: Polarity = Polarity.AMBIGUOUS
    binding_tier: BindingTier = BindingTier.OTHER
    relevance: float = 0.0           # advisory display data, never a threshold
    polarity_rationale: str = ""
    source_path: str = ""


# ---------------------------------------------------------------- audit record

@dataclass
class AuditRecord:
    """One pipeline event. audit.py chains these into a hash-chained JSONL ledger."""
    event_type: str                  # e.g. IB-2_QUOTE_PURGED, STEP5_TRACE
    case_id: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_event(self, prev_hash: str) -> dict[str, Any]:
        body = {
            "event_type": self.event_type,
            "case_id": self.case_id,
            "payload": self.payload,
        }
        event = {"prev_hash": prev_hash, "body": body}
        event["event_hash"] = sha256_text(prev_hash + canonical_json(body))
        return event
