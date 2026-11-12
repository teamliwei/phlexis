"""quoteverify.py - verbatim provenance verification (plan v3 section 5.1).

Normalizes dossier and quote text, then verifies in tiers:
  1. exact substring on normalized text            -> VERIFIED
  2. containment within <=2 edit ops (bounded)     -> VERIFIED
  3. >=95% token trigram overlap, multi-sentence   -> VERIFIED_FUZZY (flagged)
Unverified output must be purged to unknown by the caller; no retry loop may
rescue a quote (IB-2).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from harness_core import QuoteStatus

# Chars unified during normalization so "smart quotes" and dashes cannot defeat
# exact matching.
_CHAR_MAP = {
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u2212": "-",
    "\u00ad": "",     # soft hyphen
    "\u00a0": " ",    # nbsp
}
_WS = re.compile(r"\s+")


@dataclass
class Normalized:
    text: str
    index: list[int]  # index[i] = offset in the ORIGINAL string for text[i]

    def span_to_original(self, start: int, end: int) -> tuple[int, int]:
        if not self.index:
            return (start, end)
        lo = self.index[min(start, len(self.index) - 1)]
        hi = self.index[min(end - 1, len(self.index) - 1)] + 1
        return (lo, hi)


def normalize(text: str) -> Normalized:
    """NFKC, casefold, unify quotes/dashes, strip soft hyphens, collapse whitespace.
    Keeps an offset map back into the original string."""
    out: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(unicodedata.normalize("NFKC", text)):
        ch = _CHAR_MAP.get(ch, ch)
        if ch.isspace():
            if out and out[-1] != " ":
                out.append(" ")
                idx.append(i)
        else:
            for c in ch.casefold():
                out.append(c)
                idx.append(i)
    while out and out[-1] == " ":
        out.pop()
        idx.pop()
    return Normalized("".join(out), idx)


def _levenshtein_leq(a: str, b: str, k: int) -> bool:
    """Bounded Levenshtein: True if edit distance(a, b) <= k. O(len(a)*k) bands."""
    la, lb = len(a), len(b)
    if abs(la - lb) > k:
        return False
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        lo = max(1, i - k)
        hi = min(lb, i + k)
        # build banded row
        cur = [k + 1] * (lb + 1)
        if lo == 1:
            cur[0] = i
        for j in range(lo, hi + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        if min(cur[lo:hi + 1]) > k and i > k:
            return False
        prev = cur
    return prev[lb] <= k


def _trigrams(tokens: list[str]) -> set[tuple[str, ...]]:
    if len(tokens) < 3:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[i:i + 3]) for i in range(len(tokens) - 2)}


def verify_quote(quote: str, dossier: str, dossier_norm: Normalized | None = None
                 ) -> tuple[QuoteStatus, tuple[int, int] | None]:
    """Verify quote appears verbatim in dossier. Returns (status, norm_span)."""
    if not quote or not quote.strip():
        return (QuoteStatus.UNVERIFIED, None)
    dn = dossier_norm or normalize(dossier)
    qn = normalize(quote)
    # Tier 1: exact substring on normalized text.
    pos = dn.text.find(qn.text)
    if pos >= 0:
        return (QuoteStatus.VERIFIED, (pos, pos + len(qn.text)))
    # Tier 2: containment within <=2 edit operations on sliding windows.
    if len(qn.text) <= 600:
        w = len(qn.text)
        for delta in (0, 1, 2):
            for start in range(0, max(1, len(dn.text) - w - delta + 1)):
                window = dn.text[start:start + w + delta]
                if _levenshtein_leq(qn.text, window, 2):
                    return (QuoteStatus.VERIFIED, (start, start + len(window)))
    # Tier 3: >=95% trigram overlap for multi-sentence quotes (flagged fuzzy).
    q_sents = re.split(r"[.!?]+", qn.text)
    if len([s for s in q_sents if s.strip()]) >= 2:
        q_tri = _trigrams(qn.text.split())
        if q_tri:
            d_tri = _trigrams(dn.text.split())
            overlap = len(q_tri & d_tri) / len(q_tri)
            if overlap >= 0.95:
                return (QuoteStatus.VERIFIED_FUZZY, None)
    return (QuoteStatus.UNVERIFIED, None)


_NUMERAL_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "twenty": "20", "thirty": "30", "forty": "40",
    "fifty": "50", "sixty": "60", "seventy": "70", "eighty": "80",
    "ninety": "90", "hundred": "100",
}


def verify_numeric(quote: str, span_text: str, value: float, unit: str = "") -> bool:
    """Numeric facts additionally verify the numeral appears in the matched span
    (or the span + one adjacent context). Accepts digit, word, or value+unit forms."""
    hay = normalize(span_text).text
    if unit:
        hay += " " + normalize(unit).text
    sval = f"{value:g}"
    if sval in hay:
        return True
    # word numerals ("sixty" for 60) within the normalized span
    for word, digit in _NUMERAL_WORDS.items():
        if word in hay and float(digit) == value:
            return True
    return False
