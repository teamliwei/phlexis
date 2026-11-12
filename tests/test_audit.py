import pytest

from harness_core import AuditRecord
from audit import AuditLedger, verify


@pytest.fixture
def ledger(tmp_path):
    return AuditLedger(tmp_path / "ledger.jsonl")


def _rec(t, payload=None):
    return AuditRecord(event_type=t, case_id="C1", payload=payload or {})


def test_chain_appends_and_verifies(ledger):
    e1 = ledger.append(_rec("A", {"x": 1}))
    e2 = ledger.append(_rec("B"))
    assert e2["prev_hash"] == e1["event_hash"]
    ok, msg = verify(ledger.path)
    assert ok, msg


def test_tamper_detection(ledger):
    ledger.append(_rec("A", {"x": 1}))
    ledger.append(_rec("B", {"y": 2}))
    # tamper with the FIRST event's payload
    lines = ledger.path.read_text(encoding="utf-8").splitlines()
    import json
    ev = json.loads(lines[0])
    ev["body"]["payload"]["x"] = 999
    lines[0] = json.dumps(ev, sort_keys=True, separators=(",", ":"))
    ledger.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, msg = verify(ledger.path)
    assert not ok
    assert "tampered" in msg or "mismatch" in msg


def test_empty_ledger(tmp_path):
    ok, _ = verify(tmp_path / "missing.jsonl")
    assert ok
