import pytest

from kleene import k_and, k_not, k_or


def test_and_table():
    assert k_and(True, True) is True
    assert k_and(True, False) is False
    assert k_and(False, False) is False
    assert k_and(None, True) is None
    assert k_and(None, False) is False      # false absorbs unknown
    assert k_and(None, None) is None


def test_or_table():
    assert k_or(False, False) is False
    assert k_or(True, None) is True
    assert k_or(None, False) is None
    assert k_or(None, None) is None


def test_not_table():
    assert k_not(True) is False
    assert k_not(False) is True
    assert k_not(None) is None


def test_no_negative_inference():
    """The core rule: absence of proof is not proof of absence. An unknown
    operand must never silently evaluate a conjunction to False."""
    assert k_and(None, None) is None
    assert k_and(None, True) is not False
