# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""verify_audit.py - standalone hash-chain verification CLI for the audit ledger.

Usage:
  uv run scripts/verify_audit.py [data/audit.jsonl]
Exit 0 = chain intact; 1 = tampering detected.
"""
from __future__ import annotations

import sys
from pathlib import Path

# AGENTS.md Rule 10: direct paths only. Run from the app folder.
if not Path("lib").is_dir():
    sys.exit("ERROR: run this script from the app folder (lib/ not found here)")
sys.path.insert(0, "lib")

from audit import verify  # noqa: E402


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        Path("data/audit.jsonl")
    ok, msg = verify(path)
    print(f"{'OK' if ok else 'TAMPERED'}: {path} - {msg}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
