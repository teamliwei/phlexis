# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""etl_cases.py - Subsystem 0a: parse ph-law-library SC decisions -> SQLite.

Ingests .txt files from data/11_sc_decisions into F:/kraft/app/data/corpus.db:
metadata extraction (deterministic regex/cue based), cue-phrase holding
segmentation, hierarchical passage chunking (~512 tokens, 20% overlap) with
character offsets. PDFs are OCR-tagged into ocr_pending, never silently dropped.
Idempotent and resumable: files whose sha256 is already ingested are skipped.

Usage:
  uv run scripts/etl_cases.py [--corpus DIR] [--db FILE] [--limit N]
Run long pulls in the background with output to a log file (workspace Rule 6).
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sqlite3
import sys
import time
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_ROOT / "lib"))

from harness_core import sha256_text  # noqa: E402

DEFAULT_CORPUS = Path(r"F:\kraft\ph-law-library\data\11_sc_decisions")
DEFAULT_DB = APP_ROOT / "data" / "corpus.db"

# MiniLM has a 256-token context (AGENTS.md Rule 7 mandates it): 512-token
# passages (the bge-m3-era choice) lost their second half to embedding
# truncation. 180-word chunks (~240 wordpieces on legal text) fit the window;
# 20% overlap preserves continuity at boundaries.
PASSAGE_TOKENS = 180
PASSAGE_OVERLAP = 0.20

# cue phrases, case-insensitive, PH decision conventional structure
SECTION_CUES = [
    ("ANTECEDENT_FACTS", r"ANTECEDENT\s+FACTS"),
    ("FACTS", r"FACTS:?"),
    ("ISSUES", r"ISSUES?:?"),
    ("RULING", r"RULING:?"),
    ("DISPOSITIVE", r"(?:DISPOSITIVE|WHEREFORE)"),
]
GR_RE = re.compile(r"G\.?\s*R\.?\s*(?:Nos?\.?)?\s*(\d{5,7})", re.I)
DATE_FILE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
PONENTE_RE = re.compile(
    r"(?:ponente|PER\s+CURIAM|\bJ\.?\s*:?)", re.I)
PONENTE_LINE_RE = re.compile(
    r"^([A-Z][A-Z.\- ]+[A-Z]),?\s+J\.?:?$", re.M)


def ensure_schema(con: sqlite3.Connection) -> None:
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY,
            gr_no TEXT, title TEXT, ponente TEXT, date TEXT,
            decision_type TEXT, binding_tier TEXT,
            source_path TEXT UNIQUE, sha256 TEXT, body_text TEXT,
            body_format TEXT, ingested_at TEXT);
        CREATE INDEX IF NOT EXISTS idx_cases_gr ON cases(gr_no);
        CREATE INDEX IF NOT EXISTS idx_cases_sha ON cases(sha256);
        -- the sha256 index is critical: without it every resume-skip scans the
        -- full cases table (which stores body_text, ~2 GB) per file
        CREATE TABLE IF NOT EXISTS sections (
            id INTEGER PRIMARY KEY, case_id INTEGER REFERENCES cases(id),
            name TEXT, start INTEGER, end INTEGER);
        CREATE TABLE IF NOT EXISTS passages (
            id INTEGER PRIMARY KEY, case_id INTEGER REFERENCES cases(id),
            section_id INTEGER REFERENCES sections(id), seq INTEGER,
            start INTEGER, end INTEGER, text TEXT);
        CREATE INDEX IF NOT EXISTS idx_passages_case ON passages(case_id);
        CREATE TABLE IF NOT EXISTS ocr_pending (
            source_path TEXT PRIMARY KEY, reason TEXT, found_at TEXT);
        CREATE TABLE IF NOT EXISTS etl_meta (
            key TEXT PRIMARY KEY, value TEXT);
        """)


def extract_metadata(text: str, path: Path) -> dict:
    head = text[:2000]
    gr = GR_RE.search(head)
    dm = DATE_FILE_RE.search(path.name)
    date = dm.group(1) if dm else ""
    if not date:
        dm2 = re.search(
            r"(?:promulgated|decided|resolved)\s+(?:on\s+)?([A-Z][a-z]+ \d{1,2}, \d{4})",
            text[:4000])
        date = dm2.group(1) if dm2 else ""
    # decision type from filename prefix (G.R. / A.C. / A.M. / etc.)
    dtype = path.name.split("_")[0] if "_" in path.name else "UNK"
    pon = PONENTE_LINE_RE.search(text[:3000])
    title = text.strip().splitlines()[0][:200] if text.strip() else path.stem
    return {
        "gr_no": gr.group(1) if gr else "",
        "title": title,
        "ponente": pon.group(1) if pon else "",
        "date": date,
        "decision_type": dtype,
        "binding_tier": "SC_BINDING" if dtype.startswith(("G.R", "GR")) else "SC_PERSUASIVE",
        "body_format": "txt",
    }


def segment_sections(text: str) -> list[tuple[str, int, int]]:
    """Cue-phrase segmentation; paragraphs (char offsets) feed chunking."""
    spans: list[tuple[str, int, int]] = []
    marks: list[tuple[int, str]] = []
    for name, cue in SECTION_CUES:
        for m in re.finditer(cue, text, re.I):
            # only accept cues at line starts (section headers), else noise
            if m.start() == 0 or text[m.start() - 1] == "\n":
                marks.append((m.start(), name))
    marks.sort()
    for i, (pos, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        if not spans or spans[-1][0] != pos:
            spans.append((name, pos, end))
    if not spans:  # no cues: whole body as one RULING-ish bucket, flagged low-conf
        spans = [("BODY", 0, len(text))]
    return spans


def chunk_passages(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """~512-token windows with 20% overlap inside [start, end); char offsets
    are into the ORIGINAL text (paragraph-level provenance)."""
    sub = text[start:end]
    words = [(m.start(), m.end()) for m in re.finditer(r"\S+", sub)]
    if not words:
        return []
    step = max(1, int(PASSAGE_TOKENS * (1 - PASSAGE_OVERLAP)))
    out = []
    i = 0
    while i < len(words):
        take = words[i:i + PASSAGE_TOKENS]
        if not take:
            break
        s = start + take[0][0]
        e = start + take[-1][1]
        out.append((s, e))
        if i + PASSAGE_TOKENS >= len(words):
            break
        i += step
    return out


def ingest_file(con: sqlite3.Connection, path: Path) -> str:
    raw = path.read_bytes()
    sha = sha256_text(raw.decode("utf-8", errors="replace"))
    row = con.execute("SELECT id FROM cases WHERE sha256=?", (sha,)).fetchone()
    if row:
        return "skip"
    if path.suffix.lower() == ".pdf":
        con.execute("INSERT OR REPLACE INTO ocr_pending VALUES (?,?,?)",
                    (str(path), "pdf_no_text_layer", dt.datetime.now().isoformat()))
        return "ocr_pending"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    meta = extract_metadata(text, path)
    cur = con.execute(
        "INSERT INTO cases (gr_no,title,ponente,date,decision_type,binding_tier,"
        "source_path,sha256,body_text,body_format,ingested_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (meta["gr_no"], meta["title"], meta["ponente"], meta["date"],
         meta["decision_type"], meta["binding_tier"], str(path), sha,
         text, meta["body_format"], dt.datetime.now().isoformat()))
    case_id = cur.lastrowid
    for name, s, e in segment_sections(text):
        scol = con.execute(
            "INSERT INTO sections (case_id,name,start,end) VALUES (?,?,?,?)",
            (case_id, name, s, e))
        for seq, (ps, pe) in enumerate(chunk_passages(text, s, e)):
            con.execute(
                "INSERT INTO passages (case_id,section_id,seq,start,end,text) "
                "VALUES (?,?,?,?,?,?)",
                (case_id, scol.lastrowid, seq, ps, pe, text[ps:pe]))
    return "new"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--limit", type=int, default=0, help="smoke-test only")
    ap.add_argument("--rebuild-passages", action="store_true",
                    help="wipe cases/sections/passages and re-ingest everything "
                         "with the current chunk size (use after a chunk-size "
                         "change; full rerun)")
    args = ap.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(args.db)
    ensure_schema(con)
    # chunk-size stamp: --rebuild-passages wipes ONLY when the stored chunking
    # differs from the current one. Re-wiping on every rerun destroyed prior
    # progress (2026-11-12 incident: a 40k-case run was wiped by a restart).
    stamp = con.execute("SELECT value FROM etl_meta WHERE key='passage_chunk_tokens'"
                        ).fetchone()
    stamp_ok = stamp is not None and stamp[0] == str(PASSAGE_TOKENS)
    if args.rebuild_passages:
        if stamp_ok:
            print("rebuild-passages: DB already uses the current chunk size "
                  f"({PASSAGE_TOKENS} tokens) - resuming without wipe", flush=True)
        else:
            # unstamped DB (pre-fix build): verify chunking empirically before
            # wiping - 180-word chunks average ~1.3 KB, 512-word ~3.3 KB
            avg = con.execute("SELECT AVG(LENGTH(text)) FROM "
                              "(SELECT text FROM passages LIMIT 500)").fetchone()[0]
            if avg is not None and avg < 1600:
                print(f"rebuild-passages: chunking verified current "
                      f"(avg passage {avg:.0f} chars) - resuming without wipe",
                      flush=True)
            else:
                con.executescript("DELETE FROM passages; DELETE FROM sections; "
                                  "DELETE FROM cases;")
                con.commit()
                print(f"rebuild-passages: wiped cases/sections/passages (chunk "
                      f"size changed to {PASSAGE_TOKENS}; avg was "
                      f"{0 if avg is None else int(avg)} chars)", flush=True)
    con.execute("INSERT OR REPLACE INTO etl_meta VALUES ('passage_chunk_tokens', ?)",
                (str(PASSAGE_TOKENS),))
    con.commit()
    n_existing = con.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    print(f"RESUME CHECK: {n_existing} cases already ingested - NOTHING will be "
          f"deleted in this mode; already-ingested files are skipped via the "
          f"sha256 index (fast), fresh files are ingested (counters: skip= "
          f"fast-forward, new= fresh work)", flush=True)
    files = sorted(args.corpus.rglob("*.txt")) + sorted(args.corpus.rglob("*.pdf"))
    if args.limit:
        files = files[:args.limit]
    counts = {"new": 0, "skip": 0, "ocr_pending": 0, "error": 0}
    t0 = time.time()
    for n, path in enumerate(files, 1):
        try:
            counts[ingest_file(con, path)] += 1
        except Exception as exc:  # noqa: BLE001 - per-file isolation (R8)
            counts["error"] += 1
            print(f"ERROR {path}: {exc!r}", flush=True)
        if n % 25 == 0:
            con.commit()
            rate = n / max(time.time() - t0, 1)
            eta_min = (len(files) - n) / max(rate, 0.1) / 60
            print(f"[{time.strftime('%H:%M:%S')}] etl_cases: {n}/{len(files)} "
                  f"{counts} rate={rate:.0f}/s eta={eta_min:.0f}min", flush=True)
    con.commit()
    con.execute("INSERT OR REPLACE INTO etl_meta VALUES ('cases_last_run', ?)",
                (dt.datetime.now().isoformat(),))
    con.commit()
    n_cases = con.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    n_pass = con.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
    con.close()
    print(f"DONE etl_cases: {counts} total_cases={n_cases} total_passages={n_pass}",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
