# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "fastembed>=0.4",
#   "numpy>=1.26",
# ]
# ///
"""retrieve.py - Subsystem 1 CLI: three-filter pipeline (plan v3 section 4).

  Filter A  metadata + statutory scoping (hard SQL filter, no vectors)
  Filter B  all-MiniLM-L6-v2 cosine over the Filter-A candidate set (exact sweep:
            numpy fp16 memmap; no recall loss at this corpus scale)
  Filter C  polarity classification is delegated to the grounding-stage LLM
            (Rev 2.2 decision); this stage emits the shortlist + synthesized
            factual-dilemma context for it.

Usage:
  uv run --python 3.12 scripts/retrieve.py --statute "RA 4136" --section 35 \
      --dilemma "unmarked SUV at high speed claiming informal emergency response" \
      [--top 30] [--limit-candidates 20000]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

APP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_ROOT / "lib"))
DEFAULT_DB = APP_ROOT / "data" / "corpus.db"
INDEX_DIR = APP_ROOT / "data" / "index"
EMBED_DIM: int | None = None  # derived from model/index state at runtime (R11)


class VectorIndex:
    """Exact cosine sweep over a fp16 memmap (plan v3 D6). faiss-cpu swap-in
    point: same two methods, if sweeps ever exceed the time budget."""

    def __init__(self, vec_path: Path, dim: int):
        size = vec_path.stat().st_size
        if dim <= 0 or size % (dim * 2) != 0:
            raise ValueError(f"index file size {size} inconsistent with dim {dim}")
        self.arr = np.memmap(vec_path, dtype=np.float16, mode="r",
                             shape=(size // (dim * 2), dim))
        self.norms = np.maximum(
            np.linalg.norm(self.arr.astype(np.float32), axis=1), 1e-9)

    def top_k(self, query: np.ndarray, candidate_rows: np.ndarray,
              k: int) -> list[tuple[int, float]]:
        sub = self.arr[candidate_rows].astype(np.float32)
        sims = (sub @ query.astype(np.float32)) / self.norms[candidate_rows]
        order = np.argsort(-sims)[:k]
        return [(int(candidate_rows[i]), float(sims[i])) for i in order]


def filter_a(con, statute: str | None, section: str | None,
             limit: int) -> tuple[list[int], dict]:
    """Hard SQL scoping: SC-binding tier + statute-anchor when given."""
    base = ("SELECT p.id FROM passages p JOIN cases c ON c.id=p.case_id "
            "WHERE c.binding_tier IN ('SC_BINDING','SC_PERSUASIVE')")
    params: list = []
    note = {"statute_anchor": None}
    if statute:
        anch = con.execute(
            "SELECT s.id, s.number, s.title FROM statutes s "
            "WHERE REPLACE(REPLACE(UPPER(s.number),' ',''),'RA','') = ? "
            "   OR s.number LIKE ?",
            (statute.upper().replace("RA ", "").replace("RA", "").strip(),
             f"%{statute}%")).fetchone()
        if anch:
            note["statute_anchor"] = {"id": anch[0], "number": anch[1],
                                      "title": anch[2]}
    if section and note["statute_anchor"]:
        note["section"] = con.execute(
            "SELECT section_no, heading, start, end FROM statute_sections "
            "WHERE statute_id=? AND section_no=?",
            (note["statute_anchor"]["id"], str(section))).fetchone()
    ids = [r[0] for r in con.execute(base + f" LIMIT {int(limit)}", params)]
    return ids, note


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--statute", default=None)
    ap.add_argument("--section", default=None)
    ap.add_argument("--dilemma", required=True)
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--limit-candidates", type=int, default=20000)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    from fastembed import TextEmbedding
    con = _connect(args.db)
    cand_rows, note = filter_a(con, args.statute, args.section,
                               args.limit_candidates)
    print(f"filter_a: {len(cand_rows)} candidates; anchor={note.get('statute_anchor')}",
          flush=True)
    if not cand_rows:
        print("no candidates - run etl/embed first", flush=True)
        return 1

    model = TextEmbedding(model="sentence-transformers/all-MiniLM-L6-v2",
                          threads=4)  # AGENTS.md Rule 7/8: MiniLM only, thread-capped
    q = next(iter(model.embed([args.dilemma])))
    state = json.loads((INDEX_DIR / "build_state.json").read_text())
    # never sweep an index built by a different model: a bge-built index swept
    # with a MiniLM query returns plausible-looking garbage (AGENTS.md Rule 7)
    if state.get("model") != "sentence-transformers/all-MiniLM-L6-v2":
        print(f"REFUSAL: index was built with {state.get('model')!r}, not "
              f"all-MiniLM-L6-v2 (AGENTS.md Rule 7). Rebuild: "
              f"uv run --python 3.12 scripts/embed_index.py", flush=True)
        return 1
    idx = VectorIndex(INDEX_DIR / "vectors.f16", int(state["dim"]))
    # passage_id -> index row position (row order = append order in the jsonl);
    # the ETL may be appending concurrently, so restrict to indexed passages
    row_of = {}
    with open(INDEX_DIR / "passages.jsonl", encoding="utf-8") as f:
        for row_pos, line in enumerate(f):
            if line.strip():
                row_of[int(json.loads(line)["passage_id"])] = row_pos
    cand_rows = np.array(sorted(row_of[p] for p in cand_rows if p in row_of),
                         dtype=np.int64)
    print(f"filter_b: {len(cand_rows)} indexed candidates", flush=True)
    hits = idx.top_k(q, cand_rows, args.top)

    out = []
    id_at_row = {row: pid for pid, row in row_of.items()}
    for row_pos, score in hits:
        pid = id_at_row[row_pos]
        row = con.execute(
            "SELECT p.text, p.start, p.end, s.name, c.gr_no, c.title, c.date, "
            "c.source_path, c.binding_tier FROM passages p "
            "JOIN sections s ON s.id=p.section_id JOIN cases c ON c.id=p.case_id "
            "WHERE p.id=?", (pid,)).fetchone()
        out.append({
            "passage_id": pid, "relevance": round(score, 4),  # advisory only
            "section": row[3], "gr_no": row[4], "title": row[5], "date": row[6],
            "source_path": row[7], "binding_tier": row[8],
            "passage_text": row[0], "offsets": [row[1], row[2]],
        })
    result = {"dilemma": args.dilemma, "statute": args.statute,
              "section": args.section, "anchor": note, "shortlist": out,
              "note": "relevance is advisory; polarity is decided by the "
                      "grounding-stage LLM with verbatim holding quotes (Rev 2.2)"}
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}", flush=True)
    else:
        print(text[:4000], flush=True)
    return 0


def _connect(db: Path):
    import sqlite3
    con = sqlite3.connect(db)
    return con


if __name__ == "__main__":
    sys.exit(main())
