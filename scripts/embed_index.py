# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "fastembed>=0.4",
#   "numpy>=1.26",
# ]
# ///
"""embed_index.py - Subsystem 1: all-MiniLM-L6-v2 passage embeddings -> vector index.

Embeds every passage in corpus.db with sentence-transformers/all-MiniLM-L6-v2
(fastembed/ONNX, no torch - AGENTS.md Rule 9)
and stores an append-only float16 matrix + passage metadata under data/index/,
with the build id recorded into etl_meta (plan v3 sections 4, R11).

Storage layout (all append-only, resumable):
  data/index/vectors.f16      raw float16 rows, dim model-derived, passage order
  data/index/passages.jsonl   one JSON per row: passage_id/case_id/section/offsets
  data/index/build_state.json done_ids + model pin (restart-safe)

Usage:
  uv run --python 3.12 scripts/embed_index.py [--db FILE] [--batch 64]
  uv run --python 3.12 scripts/embed_index.py --limit 200   # smoke
Background + logs per Rule 6.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

# AGENTS.md Rule 10: direct paths only. Run from the app folder.
if not Path("lib").is_dir():
    sys.exit("ERROR: run this script from the app folder (lib/ not found here)")
sys.path.insert(0, "lib")
DEFAULT_DB = Path("data/corpus.db")
INDEX_DIR = Path("data/index")

MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"  # mandated (AGENTS.md Rule 7, 2026-11-10)
EMBED_THREADS = 4                  # capped per AGENTS.md Rule 8 (no resource starvation)
EMBED_DIM: int | None = None  # derived from model/index state at runtime (R11)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--limit", type=int, default=0, help="smoke-test only")
    args = ap.parse_args()

    from fastembed import TextEmbedding
    model = TextEmbedding(model=MODEL_ID, threads=EMBED_THREADS)

    con = sqlite3.connect(args.db)
    rows = con.execute(
        "SELECT id, case_id, section_id, seq, start, end, text FROM passages "
        "ORDER BY id").fetchall()
    if args.limit:
        rows = rows[:args.limit]

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    vec_path = INDEX_DIR / "vectors.f16"
    meta_path = INDEX_DIR / "passages.jsonl"
    state_path = INDEX_DIR / "build_state.json"

    done: set[int] = set()
    if state_path.exists() and vec_path.exists() and meta_path.exists():
        done = set(json.loads(state_path.read_text())["done_ids"])
        rows = [r for r in rows if r[0] not in done]
        print(f"resuming: {len(done)} already embedded, {len(rows)} to go",
              flush=True)
    elif any(p.exists() for p in (vec_path, meta_path, state_path)):
        # partial files without valid state -> start clean rather than mix
        for p in (vec_path, meta_path, state_path):
            p.unlink(missing_ok=True)
        print("stale index artifacts without state: reset", flush=True)

    if not rows:
        print("DONE embed_index: nothing to embed", flush=True)
        return 0

    t0 = time.time()
    buf: list[tuple[int, np.ndarray, str]] = []
    dim: int | None = None
    if state_path.exists():
        dim = json.loads(state_path.read_text()).get("dim")
    with open(vec_path, "ab") as vf, open(meta_path, "a", encoding="utf-8") as mf:
        def flush_buf() -> None:
            if not buf:
                return
            for pid, emb, meta in buf:
                vf.write(emb.tobytes())
                mf.write(meta + "\n")
            vf.flush()
            mf.flush()
            state_path.write_text(json.dumps(
                {"done_ids": sorted(done), "model": MODEL_ID, "dim": dim,
                 "dtype": "float16", "count": len(done)}, sort_keys=True))
            buf.clear()

        for i in range(0, len(rows), args.batch):
            batch = rows[i:i + args.batch]
            texts = [r[6][:2000] for r in batch]  # chunked to fit MiniLM's 256-token
                                                  # window; hard cap is a safety net
            embs = list(model.embed(texts, batch_size=args.batch))
            if dim is None:
                dim = int(np.asarray(embs[0]).shape[0])
                print(f"model emits dim={dim} (derived at runtime, R11)",
                      flush=True)
            for r, e in zip(batch, embs):
                pid, case_id, sec_id, seq, s, e_, _ = r
                done.add(pid)
                buf.append((pid, e.astype(np.float16), json.dumps(
                    {"passage_id": pid, "case_id": case_id, "section_id": sec_id,
                     "seq": seq, "start": s, "end": e_}, sort_keys=True)))
            n = i + len(batch)
            if (i // args.batch) % 20 == 19:
                flush_buf()  # R8: checkpoint to disk, never trust RAM
            rate = n / max(time.time() - t0, 1)
            eta = (len(rows) - n) / max(rate, 0.01) / 60
            print(f"[{time.strftime('%H:%M:%S')}] embed_index: {n}/{len(rows)} "
                  f"rate={rate:.1f}/s eta={eta:.0f}min", flush=True)
        flush_buf()

    build_id = f"{MODEL_ID.replace('/', '_')}_{dt.datetime.now().strftime('%Y%m%dT%H%M%S')}"
    con.execute("INSERT OR REPLACE INTO etl_meta VALUES ('index_build_id', ?)",
                (build_id,))
    con.execute("INSERT OR REPLACE INTO etl_meta VALUES ('index_model', ?)",
                (MODEL_ID,))
    con.commit()
    con.close()
    print(f"DONE embed_index: passages={len(done)} dim={dim} "
          f"bytes={len(done) * (dim or 0) * 2} build={build_id}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
