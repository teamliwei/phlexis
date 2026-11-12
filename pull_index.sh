#!/usr/bin/env bash
# pull_index.sh - local counterpart to embed_and_push.sh: fetch the latest
# index release asset built on the remote instance and extract it into
# data/index/. Requires curl and tar (both present in Git Bash on Windows).
# Reads GITHUB_TOKEN from .env.
set -euo pipefail
cd "$(dirname "$0")"

[ -f .env ] || { echo "ERROR: .env not found"; exit 1; }
set -a; source .env; set +a
[ -n "${GITHUB_TOKEN:-}" ] || { echo "ERROR: GITHUB_TOKEN empty in .env"; exit 1; }

API="https://api.github.com/repos/teamliwei/phlexis"
TAG=$(curl -sf "$API/releases?per_page=1" \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" | \
  python -c "import json,sys;r=json.load(sys.stdin);print(r[0]['tag_name'] if r else '')")
[ -n "$TAG" ] || { echo "ERROR: no index releases found"; exit 1; }
echo "latest index release: $TAG"

ASSET_URL=$(curl -sf "$API/releases/tags/$TAG" \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" | \
  python -c "import json,sys;a=json.load(sys.stdin)['assets'];print(a[0]['url'] if a else '')")
[ -n "$ASSET_URL" ] || { echo "ERROR: release has no assets"; exit 1; }

mkdir -p data/index
curl -sfL -o data/index.tar.gz \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -H "Accept: application/octet-stream" "$ASSET_URL"
tar -xzf data/index.tar.gz -C data/index
rm -f data/index.tar.gz
echo "index $TAG extracted into data/index/"
