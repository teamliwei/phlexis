#!/usr/bin/env bash
# embed_and_push.sh - remote embedding pipeline (run on the remote instance).
#
# Flow: clone/pull the repo from origin -> run the MiniLM embedding build ->
# upload the index artifacts as a GitHub RELEASE asset (git cannot carry the
# ~760 MB vectors file; release assets allow 2 GB) -> commit the build-state
# pointer and push.
#
# Setup on the remote instance (one-time, manual):
#   1. put this repo's .env next to the script (or in the repo root) with
#      GITHUB_TOKEN=<token>   (fine-grained, Contents read/write)
#   2. transfer corpus.db into data/ (out-of-band; it is NOT in the repo)
#   3. install uv (https://docs.astral.sh/uv/) and curl + tar
# Usage: ./embed_and_push.sh [repo-dir]
set -euo pipefail

REPO_URL="https://github.com/teamliwei/phlexis.git"
DIR="${1:-$HOME/phlexis}"

# --- locate/load .env (repo root after clone; script dir before) ---
load_env() {
  local f="$1"
  [ -f "$f" ] || return 1
  # shellcheck disable=SC1090
  set -a; source "$f"; set +a
  return 0
}
load_env "$DIR/.env" || load_env "$(dirname "$0")/.env" || {
  echo "ERROR: .env with GITHUB_TOKEN not found (looked in $DIR and script dir)"; exit 1
}
[ -n "${GITHUB_TOKEN:-}" ] || { echo "ERROR: GITHUB_TOKEN empty in .env"; exit 1; }

AUTH="x-access-token:${GITHUB_TOKEN}"

# --- clone or refresh the repo ---
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch origin
  git -C "$DIR" reset --hard origin/main   # remote build machine: local edits not expected
else
  git clone "https://${AUTH}@${REPO_URL#https://}" "$DIR"
fi
cd "$DIR"
mkdir -p data

# --- corpus.db must be present out-of-band (2.8 GB, not in git) ---
if [ ! -f data/corpus.db ]; then
  echo "ERROR: data/corpus.db missing."
  echo "Transfer it to this machine (SCP/cloud) into $DIR/data/ and rerun."
  exit 1
fi

# --- embedding build (resumable, thread-capped per AGENTS.md Rule 8) ---
command -v uv >/dev/null || { echo "ERROR: uv not installed"; exit 1; }
uv run --python 3.12 scripts/embed_index.py

# --- package index artifacts ---
STAMP=$(date +%Y%m%d-%H%M%S)
TAG="index-${STAMP}"
TARBALL="index-${STAMP}.tar.gz"
BUILD_ID=$(python3 -c "import json;print(json.load(open('data/index/build_state.json'))['model'])" 2>/dev/null || echo minilm)
echo "index model: $BUILD_ID"
tar -czf "$TARBALL" -C data/index vectors.f16 passages.jsonl build_state.json
echo "tarball: $(du -h "$TARBALL" | cut -f1)"

# --- upload as a GitHub release asset (2 GB cap; no LFS quota) ---
API="https://api.github.com/repos/teamliwei/phlexis"
RELEASE_JSON=$(curl -sf -X POST "$API/releases" \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  -d "{\"tag_name\":\"$TAG\",\"name\":\"$TAG\",\"body\":\"MiniLM index build $STAMP\"}") \
  || { echo "ERROR: release creation failed (check token scope)"; exit 1; }
UPLOAD_URL=$(echo "$RELEASE_JSON" | python3 -c \
  "import json,sys;print(json.load(sys.stdin)['upload_url'].split('{')[0])")
curl -sf -X POST "${UPLOAD_URL}?name=$TARBALL" \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -H "Content-Type: application/gzip" \
  --data-binary "@$TARBALL" \
  || { echo "ERROR: asset upload failed"; exit 1; }
echo "release $TAG uploaded"

# --- commit the pointer + build state (small files only) ---
echo "$TAG" > data/index/RELEASE.txt
git add -f data/index/build_state.json data/index/RELEASE.txt
git -c user.name="remote-embed" -c user.email="remote-embed@users.noreply.github.com" \
  commit -m "index build $TAG ($BUILD_ID)" || echo "nothing new to commit"
git push "https://${AUTH}@${REPO_URL#https://}" HEAD:main

rm -f "$TARBALL"
echo "DONE: index build $TAG complete; pull it locally with pull_index.sh"
