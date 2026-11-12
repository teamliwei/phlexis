"""audit.py - hash-chained JSONL audit ledger (plan v3 section 5.4).

Append-only ledger, one line per pipeline event:
    event_hash = SHA256(prev_hash || canonical_json(event.body))
Tampering with any past line is detectable via verify(). The UI's audit tab and
scripts/verify_audit.py both call verify().
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from harness_core import AuditRecord, canonical_json

GENESIS = "0" * 64


class AuditLedger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.prev_hash = self._last_hash() if self.path.exists() else GENESIS

    def _last_hash(self) -> str:
        last = GENESIS
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    last = json.loads(line)["event_hash"]
        return last

    def append(self, record: AuditRecord) -> dict[str, Any]:
        event = record.to_event(self.prev_hash)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(canonical_json(event) + "\n")
        self.prev_hash = event["event_hash"]
        return event

    def events(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)


def verify(path: Path) -> tuple[bool, str]:
    """Recompute the whole chain. Returns (ok, message)."""
    prev = GENESIS
    n = 0
    p = Path(path)
    if not p.exists():
        return (True, "empty ledger")
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                return (False, f"line {n + 1}: not valid JSON: {exc}")
            if event.get("prev_hash") != prev:
                return (False, f"line {n + 1}: prev_hash mismatch (chain broken)")
            expected = AuditRecord(
                event_type=event["body"]["event_type"],
                case_id=event["body"]["case_id"],
                payload=event["body"].get("payload", {}),
            ).to_event(prev)["event_hash"]
            if event.get("event_hash") != expected:
                return (False, f"line {n + 1}: event_hash mismatch (content tampered)")
            prev = event["event_hash"]
            n += 1
    return (True, f"chain intact, {n} events")
