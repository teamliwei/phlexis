#!/bin/bash
# watchdog_etl_cases.sh - auto-relaunch the resumable case ETL. Exits when
# etl_cases prints DONE (full corpus walked).
cd /f/kraft/app
LOG=/f/kraft/etl_cases_watchdog.log
for i in $(seq 1 100); do
  echo "[watchdog] restart #$i $(date +%F\ %T)" >> "$LOG"
  uv run --python 3.12 scripts/etl_cases.py >> "$LOG" 2>&1
  code=$?
  echo "[watchdog] etl exited code=$code $(date +%F\ %T)" >> "$LOG"
  if grep -q "DONE etl_cases" "$LOG"; then
    echo "[watchdog] case ETL complete" >> "$LOG"
    break
  fi
  sleep 10
done
echo "[watchdog] exiting $(date +%F\ %T)" >> "$LOG"
