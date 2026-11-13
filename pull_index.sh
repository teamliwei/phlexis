#!/usr/bin/env bash
# pull_index.sh - run from the app folder. All paths hardcoded literals.
set -euo pipefail

GITHUB_TOKEN=$(grep -m1 '^GITHUB_TOKEN=' .env | cut -d= -f2- | tr -d '\r')

ASSET_URL=$(curl -sf "https://api.github.com/repos/teamliwei/phlexis/releases/tags/index-build" \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  | python -c "import json,sys;a=json.load(sys.stdin)['assets'];print(a[0]['url'] if a else '')")

curl -sfL -o index.tar.gz \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -H "Accept: application/octet-stream" \
  "$ASSET_URL"

mkdir -p data/index
tar -xzf index.tar.gz -C data/index
rm -f index.tar.gz
echo "index extracted into data/index/"
