#!/bin/bash
# watchdog_etl.sh - auto-relaunch the resumable statute ETL (uv script).
# Same rationale as watchdog_juris.sh: silent kills every ~1-3 h; ETL is
# idempotent (skips ingested sha256s). Exits when etl_statutes prints DONE.
cd /f/kraft/app
LOG=/f/kraft/etl_statutes_watchdog.log
for i in $(seq 1 100); do
  echo "[watchdog] restart #$i $(date +%F\ %T)" >> "$LOG"
  uv run --python 3.12 scripts/etl_statutes.py >> "$LOG" 2>&1
  code=$?
  echo "[watchdog] etl exited code=$code $(date +%F\ %T)" >> "$LOG"
  if grep -q "DONE etl_statutes" "$LOG"; then
    echo "[watchdog] statute ETL complete" >> "$LOG"
    break
  fi
  sleep 10
done
echo "[watchdog] exiting $(date +%F\ %T)" >> "$LOG"
