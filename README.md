# crypto-dashboard-build

Build source for the **Crypto Value-Capture Watchlist** dashboard.

This repo exists for one reason: so a scheduled cloud session can rebuild and republish
the dashboard **every day, unattended, with no desktop connected** — which was impossible
while the dashboard was a single 124 KB hand-edited HTML file.

## Why the split

A cloud session can read a project doc, but only *into its context*. Re-emitting a 124 KB
file to disk means retyping it, which is both expensive and a corruption risk — so the
publication rule was "stand pat", and the dashboard drifted days behind the data.

Splitting the file fixes the actual constraint:

| | size | changes | who edits it |
|---|---|---|---|
| `shell.html` | ~70 KB | rarely | a human, deliberately |
| `data/*.js` | ~53 KB across 16 files | every run | the scheduled run |

A run fetches the shell mechanically (`git clone`), edits only the few kilobytes that
actually changed, and rebuilds. Nothing is ever retyped.

## Layout

```
shell.html          engine: HTML, CSS, chart code, law comments. Data constants replaced
                    IN PLACE by /*__CONST:NAME__*/ markers — nothing reordered.
const_meta.json     how each constant is re-emitted (exact declaration spelling/spacing)
data/               the daily payload — one file per constant
  BAKED_ASOF.js  LAST_KNOWN.js  TOKENS.js  HISTORY_CSV.js  BACKFILL_CSV.js
  UNLOCKS.js  NETFLOW.js  IN12.js  NET_MODEL.js  DILNEG.js  EST_GROSS.js
  SPARKS30.js  BENCH.js  BENCH2.js  BH.js  RANKS.js
  _html.json        rendered prose that carries data claims (stamps, hints, axis notes)
  _comments.json    per-constant basis annotations
dist/dashboard.html the built artifact — this is what Notion fetches
tools/              split.py · build.py · validate_build.js · validate_prose.py · scope_gate.py · publish.sh
```

## Daily run

```bash
git clone https://github.com/Elokane/crypto-dashboard-build.git && cd crypto-dashboard-build
# edit only what changed, e.g. data/LAST_KNOWN.js, data/TOKENS.js, data/BH.js
GH_TOKEN=… GH_REPO=Elokane/crypto-dashboard-build ./tools/publish.sh \
  --stamp "build v19.2 · board v14.1 · baked 2026-07-28"
```

`publish.sh` builds, validates, refuses to push if a credential appears in tracked
content, pushes, and prints a **commit-pinned** raw URL:

```
https://raw.githubusercontent.com/Elokane/crypto-dashboard-build/<sha>/dist/dashboard.html
```

Pinning to the SHA matters — `raw.githubusercontent.com` caches by branch ref, so a
branch URL can serve a stale build for minutes. The commit URL is content-addressed.
The script then re-fetches that URL anonymously and compares SHA-256 against the local
build, so a private repo or a propagation lag fails loudly instead of silently
publishing yesterday's numbers.

## Guarantees

- **Lossless split.** `build.py` on unmodified data reproduces the original file
  byte-for-byte. That was the acceptance test for the split, not an approximation.
- **Fail-closed build.** Unfilled marker, missing data file, orphaned data file, or more
  than one `<script>` block → hard error, nothing written.
- **Validated publish.** `validate_build.js` evaluates the built engine in a DOM stub and
  asserts the data invariants: every seat has a price basis and a rank, ranks are a
  contiguous 1..n, benchmark series are parallel and strictly increasing in date (a
  duplicated append is the failure mode there), no NaN or negative in any numeric field,
  B/H scores in range, `IN12` and `NETFLOW` in-legs agree.

Verified against four injected faults — syntax break, out-of-range score, duplicated
benchmark date, missing data file — all caught, none published.

## What this is not

`validate_build.js` checks whether the file we are about to publish is internally
coherent. It says nothing about whether the *numbers* are right — that is
`validate_prints.py`'s job, upstream, and neither substitutes for the other.
`validate_prose.py` checks that prose restating a number still matches the number, and
`scope_gate.py dash` (added 2026-08-24) enforces the Scope law on every rendered string:
word budgets per field and a forbidden-pattern list (run narration, dated run-stamps,
verification chatter, engine instructions, internal ids). Rendered prose is a current
statement of fact, rewritten each run — never an accumulation of dated notes.

Research notes, not investment advice.
