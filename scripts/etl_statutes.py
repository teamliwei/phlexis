# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""etl_statutes.py - Subsystem 0b: statute registry + section index.

Walks the ph-law-library statute folders (RAs, Acts, Commonwealth Acts, BP, EO,
AO, MO, MC, proclamations, PDs) into corpus.db tables:

    statutes(id, number, title, date, category, source_path, sha256)
    statute_sections(id, statute_id, section_no, heading, start, end)

so Filter A can map "RA 4136 sec. 35" to source text. Section cues:
'Sec. N', 'SECTION N', 'Art. N'. Idempotent/resumable by sha256.

Usage:
  uv run scripts/etl_statutes.py [--corpus DIR] [--db FILE] [--limit N]
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sqlite3
import sys
import time
from pathlib import Path

# AGENTS.md Rule 10: direct paths only. Run from the app folder.
if not Path("lib").is_dir():
    sys.exit("ERROR: run this script from the app folder (lib/ not found here)")
sys.path.insert(0, "lib")

from harness_core import sha256_text  # noqa: E402

DEFAULT_CORPUS = Path(r"F:\kraft\ph-law-library\data")
DEFAULT_DB = Path("data/corpus.db")

CATEGORIES = {
    "02_republic_acts": "RA",
    "03_acts_1901_1935": "ACT",
    "04_commonwealth_acts": "CA",
    "05_batas_pambansa": "BP",
    "06_executive_orders": "EO",
    "07_administrative_orders": "AO",
    "08_memorandum_orders": "MO",
    "09_memorandum_circulars": "MC",
    "10_proclamations": "PROC",
    "12_presidential_decrees": "PD",
}

NUM_FROM_FILE_RE = re.compile(
    r"^(?P<cat>[A-Za-z.]+?)_?(?P<num>[A-Za-z0-9.\-]+?)_(?P<date>\d{4}-\d{2}-\d{2})")
SECTION_RE = re.compile(
    r"^(?:SECTION|SEC\.?|Art\.?)\s+(\d+[A-Za-z]?)\.?[\s.\-:\u2013]*(.{0,120})",
    re.I | re.M)


def ensure_schema(con: sqlite3.Connection) -> None:
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS statutes (
            id INTEGER PRIMARY KEY, number TEXT, title TEXT, date TEXT,
            category TEXT, source_path TEXT UNIQUE, sha256 TEXT,
            ingested_at TEXT);
        CREATE INDEX IF NOT EXISTS idx_statutes_num ON statutes(number);
        CREATE TABLE IF NOT EXISTS statute_sections (
            id INTEGER PRIMARY KEY, statute_id INTEGER REFERENCES statutes(id),
            section_no TEXT, heading TEXT, start INTEGER, end INTEGER);
        CREATE INDEX IF NOT EXISTS idx_ss_no ON statute_sections(statute_id, section_no);
        """)


def parse_file(path: Path, category_code: str) -> dict | None:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    sha = sha256_text(text)
    m = NUM_FROM_FILE_RE.match(path.stem)
    number = m.group("num") if m else path.stem
    date = m.group("date") if m else ""
    if not date:
        dm = re.search(r"(\d{4}-\d{2}-\d{2})", path.stem)
        date = dm.group(1) if dm else ""
    title = text.strip().splitlines()[0][:200] if text.strip() else path.stem
    return {"number": number, "title": title, "date": date,
            "category": category_code, "sha256": sha, "text": text}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    args.db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(args.db)
    ensure_schema(con)

    files: list[tuple[Path, str]] = []
    for folder, code in CATEGORIES.items():
        d = args.corpus / folder
        if d.is_dir():
            files.extend((p, code) for p in sorted(d.rglob("*.txt")))
    if args.limit:
        files = files[:args.limit]

    counts = {"new": 0, "skip": 0, "error": 0}
    t0 = time.time()
    for n, (path, code) in enumerate(files, 1):
        try:
            info = parse_file(path, code)
            row = con.execute("SELECT id FROM statutes WHERE sha256=? AND category=?",
                              (info["sha256"], code)).fetchone()
            if row:
                counts["skip"] += 1
            else:
                cur = con.execute(
                    "INSERT INTO statutes (number,title,date,category,source_path,"
                    "sha256,ingested_at) VALUES (?,?,?,?,?,?,?)",
                    (info["number"], info["title"], info["date"], code,
                     str(path), info["sha256"], dt.datetime.now().isoformat()))
                for m in SECTION_RE.finditer(info["text"]):
                    con.execute(
                        "INSERT INTO statute_sections (statute_id,section_no,"
                        "heading,start,end) VALUES (?,?,?,?,?)",
                        (cur.lastrowid, m.group(1), (m.group(2) or "").strip(),
                         m.start(), m.end()))
                counts["new"] += 1
        except Exception as exc:  # noqa: BLE001
            counts["error"] += 1
            print(f"ERROR {path}: {exc!r}", flush=True)
        if n % 50 == 0:
            con.commit()
            rate = n / max(time.time() - t0, 1)
            print(f"[{time.strftime('%H:%M:%S')}] etl_statutes: {n}/{len(files)} "
                  f"{counts} rate={rate:.0f}/s", flush=True)
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM statutes").fetchone()[0]
    ns = con.execute("SELECT COUNT(*) FROM statute_sections").fetchone()[0]
    con.close()
    print(f"DONE etl_statutes: {counts} total={n} sections={ns}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
