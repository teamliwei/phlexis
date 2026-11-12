# The Neuro-Symbolic Legal Harness (Python)

Implementation of `docs/kraft-legal-implementation-plan-v3.md` (supersedes the
removed Rust toolchain). Philippine-law decision-support harness: verbatim fact
grounding, three-filter jurisprudence retrieval over the `ph-law-library`
corpus, Kleene three-valued statute evaluation, ASPIC+/Dung argument
arbitration, hash-chained audit ledger, local web UI.

**Standing disclaimer:** outputs are decision-support artifacts for practitioner
review, not legal advice.

## Layout

```
lib\        pure-stdlib core (no third-party imports): domain types, quote
            verification, Kleene engine, rule packs, argumentation, audit
scripts\    every stage is a standalone PEP 723 script (deps in the
            # /// script header), run with `uv run scripts/<name>.py`
packs\      TOML rule packs (first pack: RA 4136)
tests\      pytest + hypothesis (29 tests incl. brute-force grounded-extension
            property tests)
data\       corpus.db (SQLite WAL), vector index, case artifacts, audit ledger
```

## Quick reference

```
# tests (deterministic core)
uv run --python 3.12 --with pytest --with hypothesis -m pytest tests/ -q

# Subsystem 0 - ETL (background + log per workspace Rule 6)
uv run --python 3.12 scripts/etl_cases.py                      # 11_sc_decisions -> SQLite
uv run --python 3.12 scripts/etl_statutes.py                   # statute registry + sections
# Subsystem 1 - retrieval
uv run --python 3.12 scripts/embed_index.py                    # MiniLM passage index
uv run --python 3.12 scripts/retrieve.py --dilemma "..." --statute "RA 4136" --section 35
# Subsystem 2 - grounding (needs local Unsloth/llama.cpp OpenAI-compatible server)
uv run --python 3.12 scripts/ground.py --dossier <file> --pack packs/ra4136 \
    --shortlist data/smoke_retrieval.json --base-url http://127.0.0.1:8080/v1
# Steps 5-8 - deterministic tail
uv run scripts/evaluate.py --facts data/factcontext.json
uv run scripts/arbitrate.py --trace data/trace.json --facts data/factcontext.json
uv run --python 3.12 scripts/verify_pack.py packs/ra4136       # z3 CI gate
uv run scripts/verify_audit.py                                 # ledger chain check
# UI
uv run --python 3.12 scripts/serve.py --port 8765              # http://127.0.0.1:8765
```

All long runs go in the background with logs (workspace AGENTS.md Rule 6);
ETL/embedding stages are idempotent and resumable.

## Environment notes

- Python 3.12 runtime is pinned per-script via uv (`--python 3.12`); the box's
  default 3.14 may lack ML wheels.
- Embedding model: **sentence-transformers/all-MiniLM-L6-v2** (AGENTS.md Rule 7,
  2026-11-10: bge-m3 permanently banned, artifacts deleted). Index derives the
  dim at runtime and records it in `data/index/build_state.json`; model swaps
  force a re-index; embeddings are never silently mixed. Thread-capped (Rule 8).
  torch is banned as a dependency (Rule 9) - fastembed/ONNX only.
- The audit ledger is append-only JSONL, hash-chained
  (`event_hash = SHA256(prev_hash || canonical_json(body))`); tampering with
  any past line is detected by `verify_audit.py` and on UI load.

## Status (2026-11-08)

- M0 core + tests: DONE (29 passed).
- M1 ETL: DONE code-wise; full-corpus run in background (`../etl_*_full.log`).
- M2 retrieval: embed + exact fp16 sweep + statute-anchor scoping smoke-verified.
- M3 grounding: implemented; needs the live Unsloth endpoint for P/R measurement.
- M4 RA 4136 pack + z3 verification: DONE (pack verified).
- M5 arbitration: DONE; golden scenarios B/C produce correct dispositions.
- M6 web UI: DONE v1 (DAG, provenance, audit tab).
- Corpus gap: SC jurisprudence pull resumed, ~8% at relaunch
  (`ph-law-library/logs/chain_juris3.log`).
