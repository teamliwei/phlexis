import pytest

from harness_core import QuoteStatus
from quoteverify import normalize, verify_numeric, verify_quote


def test_tier1_exact_with_drift():
    dossier = "Recorded speed: 100 km/h.  Posted limit: 60 km/h."
    quote = "Recorded speed: 100 km/h."
    status, span = verify_quote(quote, dossier)
    assert status is QuoteStatus.VERIFIED
    assert span is not None
    # span maps back into the original string
    assert dossier[span[0]:span[1]].startswith("Recorded speed")


def test_tier1_normalization_unicode():
    # smart quotes + em dash + case differences still match exactly
    dossier = "The officer said \u201cstop\u201d \u2014 then the siren sounded."
    quote = "the officer said \"stop\" - then the siren sounded"
    status, _ = verify_quote(quote, dossier)
    assert status is QuoteStatus.VERIFIED


def test_tier2_small_edits():
    dossier = "The vehicle was traveling at a high rate of speed on the highway."
    # quote has two small edits (word swap + punctuation)
    quote = "The vehicle was travelling at a high rate of speed on the highway!"
    status, _ = verify_quote(quote, dossier)
    assert status is QuoteStatus.VERIFIED


def test_unverified_purged():
    dossier = "Dispatcher confirms no emergency call was received."
    status, _ = verify_quote("laser reading at 130 km/h", dossier)
    assert status is QuoteStatus.UNVERIFIED


def test_soft_hyphen_and_whitespace():
    dossier = "cal\u00adi-bration valid"
    status, _ = verify_quote("Calibration valid", dossier)
    assert status is QuoteStatus.VERIFIED


def test_numeric_forms():
    assert verify_numeric("q", "posted limit of sixty kilometers", 60)
    assert verify_numeric("q", "recorded 100 km/h", 100, unit="km/h")
    assert not verify_numeric("q", "nothing here", 78)


def test_normalize_offset_map():
    n = normalize("A  b\tc")  # original indices: 0'A' 1' ' 2' ' 3'b' 4'\t' 5'c'
    assert n.text == "a b c"
    assert n.index[2] == 3            # normalized 'b' maps to original index 3
    assert n.span_to_original(2, 5) == (3, 6)
