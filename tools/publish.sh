#!/usr/bin/env bash
# publish.sh — the ONE command a scheduled run invokes to ship the dashboard.
#
#   GH_TOKEN=... GH_REPO=owner/repo ./tools/publish.sh [--stamp "build v19.1 · board v14.1 · baked 2026-07-27"]
#
# Sequence, fail-closed at every step:
#   1. build   shell.html + data/  ->  dist/dashboard.html   (nothing retyped)
#   2. validate  evaluate the built file, assert data invariants
#   3. guard   refuse to push if a credential ever appears in tracked content
#   4. push    commit + push to the public repo
#   5. emit    print the COMMIT-PINNED raw URL for Notion to fetch
#
# Step 5 matters: raw.githubusercontent.com caches aggressively by branch ref, so a
# branch URL can serve yesterday's build for minutes. Pinning to the commit SHA makes
# the URL content-addressed — Notion always gets exactly the build we just made.
set -euo pipefail

cd "$(dirname "$0")/.."
STAMP=""
[[ "${1:-}" == "--stamp" ]] && STAMP="$2"

: "${GH_TOKEN:?GH_TOKEN not set}"
: "${GH_REPO:?GH_REPO not set (owner/repo)}"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

say "1/5 build"
mkdir -p dist
if [[ -n "$STAMP" ]]; then
  python3 tools/build.py . dist/dashboard.html --stamp "$STAMP"
else
  python3 tools/build.py . dist/dashboard.html
fi

say "2/5 validate"
BOARD=$(grep -o 'board v[0-9.]*' dist/dashboard.html | head -1 | sed 's/board //')
ASOF=$(grep -o 'const BAKED_ASOF = "[0-9-]*"' dist/dashboard.html | grep -o '[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}')
node tools/validate_build.js dist/dashboard.html --board "$BOARD" --asof "$ASOF"

say "3/5 credential guard"
# Never let a token reach a public repo. Scan everything git would actually commit.
git add -A >/dev/null 2>&1 || true
if git diff --cached --name-only 2>/dev/null | while read -r f; do
     [[ -f "$f" ]] && grep -lE 'github_pat_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9]{30,}|gho_[A-Za-z0-9]{30,}' "$f" || true
   done | grep -q .; then
  echo "ABORT: a GitHub credential pattern appears in staged content. Nothing pushed." >&2
  exit 1
fi
echo "  clean — no credential pattern in tracked content"

say "4/5 push"
git config user.email "engine@crypto-watchlist.local"
git config user.name  "Crypto Watchlist Engine"
if git diff --cached --quiet; then
  echo "  no changes to commit — reusing current HEAD"
else
  git commit -q -m "dashboard build $(grep -o 'id=\"buildstamp\">[^<]*' dist/dashboard.html | sed 's/.*>//')"
  echo "  committed"
fi
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git push -q "https://x-access-token:${GH_TOKEN}@github.com/${GH_REPO}.git" "HEAD:${BRANCH}" 2>&1 \
  | sed 's/github_pat_[A-Za-z0-9_]*/[REDACTED]/g'
SHA=$(git rev-parse HEAD)
echo "  pushed ${SHA:0:12} to ${BRANCH}"

say "5/5 publish URL"
URL="https://raw.githubusercontent.com/${GH_REPO}/${SHA}/dist/dashboard.html"
echo "$URL"

# Verify the URL is actually live and anonymous before handing it to Notion —
# a private repo or a propagation lag would otherwise fail silently in the embed.
for i in 1 2 3 4 5 6; do
  CODE=$(curl -s -o /tmp/_pub_check -w '%{http_code}' --max-time 20 "$URL" || echo 000)
  if [[ "$CODE" == "200" ]]; then
    LOCAL=$(sha256sum dist/dashboard.html | cut -d' ' -f1)
    REMOTE=$(sha256sum /tmp/_pub_check | cut -d' ' -f1)
    if [[ "$LOCAL" == "$REMOTE" ]]; then
      echo "  verified: 200, anonymous, sha256 matches local build"
      echo "PUBLISH_URL=$URL"
      exit 0
    fi
    echo "  served content differs from local build — retrying ($i/6)" >&2
  else
    echo "  raw URL not live yet (http=$CODE) — retrying ($i/6)" >&2
  fi
  sleep 5
done
echo "ABORT: pushed, but the raw URL never served the exact build. Do NOT attach to Notion." >&2
echo "  If http=404 the repo is probably PRIVATE — Notion cannot fetch it anonymously." >&2
exit 1
