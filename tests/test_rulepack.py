import pytest

from harness_core import EvidentiaryTier, FactContext, FactRecord, QuoteStatus
from rulepack import fact_value, load_pack
from pathlib import Path

PACK_DIR = Path(__file__).resolve().parent.parent / "packs" / "ra4136"


def _ctx(facts: dict, numbers: dict | None = None) -> FactContext:
    ctx = FactContext(case_id="T1", dossier_sha256="0" * 64, numbers=numbers or {})
    for name, val in facts.items():
        ctx.facts[name] = FactRecord(
            predicate=name, value=val, quote="q",
            quote_status=QuoteStatus.VERIFIED, tier=EvidentiaryTier.DOCUMENTED)
    return ctx


@pytest.fixture(scope="module")
def pack():
    return load_pack(PACK_DIR)


def test_pack_loads(pack):
    assert pack.statute == "RA 4136"
    assert pack.sha256
    assert any(r.rule_id == "SPEEDING_VIOLATION" for r in pack.rules)


def test_derived_predicate_numeric(pack):
    ctx = _ctx({}, {"recorded_speed": 100.0, "posted_limit": 60.0})
    assert fact_value(pack, ctx, "speed_exceeds_limit") is True
    ctx2 = _ctx({}, {"recorded_speed": 55.0, "posted_limit": 60.0})
    assert fact_value(pack, ctx2, "speed_exceeds_limit") is False


def test_derived_unknown_operand_is_unknown(pack):
    ctx = _ctx({}, {"recorded_speed": 100.0})  # posted_limit missing -> unknown
    assert fact_value(pack, ctx, "speed_exceeds_limit") is None


def test_undeclared_predicate_rejected(tmp_path):
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "pack.toml").write_text(
        '[meta]\nstatute="X"\nversion="0"\n'
        '[rule.R]\nall_of=["nope"]\nconsequence="Y"\n',
        encoding="utf-8")
    with pytest.raises(ValueError):
        load_pack(bad)


def test_duplicate_precedence_rejected(tmp_path):
    bad = tmp_path / "bad2"
    bad.mkdir()
    (bad / "pack.toml").write_text(
        '[meta]\nstatute="X"\nversion="0"\n'
        "[predicate.p1]\nkind=\"fact\"\n[predicate.p2]\nkind=\"fact\"\n"
        '[rule.R]\nall_of=["p1"]\nconsequence="Y"\n'
        '[rule.R.exceptions.e1]\nall_of=["p2"]\nprecedence=1\nconsequence="C"\n'
        '[rule.R.exceptions.e2]\nall_of=["p2"]\nprecedence=1\nconsequence="D"\n',
        encoding="utf-8")
    with pytest.raises(ValueError):
        load_pack(bad)
