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

APP_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(APP_ROOT / "lib"))

from audit import verify  # noqa: E402


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        APP_ROOT / "data" / "audit.jsonl"
    ok, msg = verify(path)
    print(f"{'OK' if ok else 'TAMPERED'}: {path} - {msg}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
