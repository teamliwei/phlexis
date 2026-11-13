#!/usr/bin/env bash
# embed_and_push.sh - run from the cloned app folder. All paths hardcoded literals.
set -euo pipefail

GITHUB_TOKEN=$(grep -m1 '^GITHUB_TOKEN=' .env | cut -d= -f2- | tr -d '\r')
AUTH="x-access-token:${GITHUB_TOKEN}"

uv run --python 3.12 scripts/embed_index.py

tar -czf index.tar.gz -C data/index vectors.f16 passages.jsonl build_state.json

UPLOAD_URL=$(curl -sf "https://api.github.com/repos/teamliwei/phlexis/releases/tags/index-build" \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  | python3 -c "import json,sys;r=json.load(sys.stdin);print(r['upload_url'].split('{')[0] if r else '')" || true)
if [ -z "$UPLOAD_URL" ]; then
  curl -sf -X POST "https://api.github.com/repos/teamliwei/phlexis/releases" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    -d '{"tag_name":"index-build","name":"index-build","body":"MiniLM index"}' >/dev/null
  UPLOAD_URL=$(curl -sf "https://api.github.com/repos/teamliwei/phlexis/releases/tags/index-build" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    | python3 -c "import json,sys;print(json.load(sys.stdin)['upload_url'].split('{')[0])")
fi

# replace the previous asset on reruns (fixed name index.tar.gz)
ASSET_ID=$(curl -sf "https://api.github.com/repos/teamliwei/phlexis/releases/tags/index-build" \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  | python3 -c "import json,sys;a=json.load(sys.stdin)['assets'];print(a[0]['id'] if a else '')" || true)
if [ -n "$ASSET_ID" ]; then
  curl -sf -X DELETE "https://api.github.com/repos/teamliwei/phlexis/releases/assets/${ASSET_ID}" \
    -H "Authorization: Bearer ${GITHUB_TOKEN}"
fi

curl -sf -X POST "${UPLOAD_URL}?name=index.tar.gz" \
  -H "Authorization: Bearer ${GITHUB_TOKEN}" \
  -H "Content-Type: application/gzip" \
  --data-binary "@index.tar.gz"

echo index-build > data/index/RELEASE.txt
git add -f data/index/build_state.json data/index/RELEASE.txt
git -c user.name="remote-embed" -c user.email="remote-embed@users.noreply.github.com" \
  commit -m "index build" || true
git push "https://x-access-token:${GITHUB_TOKEN}@github.com/teamliwei/phlexis.git" HEAD:main

rm -f index.tar.gz
echo "DONE: index pushed; pull locally with pull_index.sh"
