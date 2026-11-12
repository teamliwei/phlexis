# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "fastembed>=0.4",
#   "numpy>=1.26",
# ]
# ///
"""bench_embed.py - throughput benchmark for the passage embedding build.

The smoke build measured 0.7 passages/s (fastembed/ONNX CPU); the full corpus
needs ~250k passages, so config matters. Tests threads/batch/parallel variants
on real passages from corpus.db and reports passages/s per config.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

APP = Path(r"F:\kraft\app")
DB = APP / "data" / "corpus.db"
MODEL = "sentence-transformers/all-MiniLM-L6-v2"  # AGENTS.md Rule 7: MiniLM only
EMBED_THREADS = 4                                  # AGENTS.md Rule 8: thread-capped


def load_passages(n: int) -> list[str]:
    con = sqlite3.connect(DB)
    rows = con.execute("SELECT text FROM passages ORDER BY id LIMIT ?", (n,)).fetchall()
    con.close()
    return [r[0] for r in rows]


def bench(name: str, texts: list[str], kwargs: dict, batch: int) -> float:
    from fastembed import TextEmbedding
    m = TextEmbedding(model=MODEL, **kwargs)
    t0 = time.time()
    count = 0
    for i in range(0, len(texts), batch):
        list(m.embed(texts[i:i + batch], batch_size=batch))
        count += len(texts[i:i + batch])
    dt = time.time() - t0
    rate = count / dt
    print(f"{name}: {rate:.1f} passages/s ({count} in {dt:.1f}s)", flush=True)
    del m
    return rate


def main() -> int:
    texts = load_passages(256)
    print(f"passages loaded: {len(texts)}; mean chars: "
          f"{int(np.mean([len(t) for t in texts]))}", flush=True)
    cpus = os.cpu_count() or 4
    print(f"cpu_count: {cpus}", flush=True)
    bench("default threads    ", texts[:64], {"threads": EMBED_THREADS}, 64)
    bench("threads=4 batch128  ", texts[:128], {"threads": EMBED_THREADS}, 128)
    bench("threads=4 batch256  ", texts[128:], {"threads": EMBED_THREADS}, 256)
    return 0


if __name__ == "__main__":
    sys.exit(main())
