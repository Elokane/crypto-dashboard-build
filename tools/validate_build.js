#!/usr/bin/env node
/*
 * validate_build.js — evaluate a built dashboard's script in a DOM stub and assert
 * the data invariants. This is the gate between "a run edited data/" and "we publish".
 *
 *   node validate_build.js <dashboard.html> [--board v14.1] [--asof 2026-07-27]
 *
 * Exit 0 = PASS (safe to publish). Exit 1 = FAIL (stand pat, publish nothing).
 * Failures are listed individually; warnings do not block.
 *
 * This complements validate_prints.py: that harness checks whether a fetched PRINT is
 * physically plausible; this one checks whether the FILE we are about to publish is
 * internally coherent. Neither substitutes for the other.
 */
const fs = require("fs");

const args = process.argv.slice(2);
const FILE = args[0];
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const wantBoard = opt("--board", null);
const wantAsof = opt("--asof", null);

if (!FILE) { console.error("usage: validate_build.js <dashboard.html>"); process.exit(2); }
const html = fs.readFileSync(FILE, "utf-8");

const fails = [], warns = [];
const check = (cond, msg) => { if (!cond) fails.push(msg); };
const warn = (cond, msg) => { if (!cond) warns.push(msg); };

/* ---------- DOM stub so the engine's constants evaluate cleanly ---------- */
function makeEl() {
  return new Proxy(function () {}, {
    get(t, p) {
      if (p === "style") return new Proxy({}, { get: (tt, pp) => pp === "setProperty" ? () => {} : (pp === "cssText" ? "" : () => {}), set: () => true });
      if (p === "classList") return { add() {}, remove() {}, contains() { return false; } };
      if (p === "length") return 0;
      if (p === Symbol.iterator) return function* () {};
      return (...a) => makeEl();
    },
    set() { return true; }, apply() { return makeEl(); },
  });
}
global.document = { getElementById: () => makeEl(), createElement: () => makeEl(), createElementNS: () => makeEl(), createTextNode: () => makeEl(), body: makeEl(), addEventListener: () => {} };
global.window = { addEventListener: () => {} };
global.innerWidth = 1200; global.innerHeight = 800;
global.fetch = () => Promise.reject(new Error("stub"));
global.AbortSignal = { timeout: () => undefined };
global.setInterval = () => 0; global.setTimeout = () => 0; global.clearTimeout = () => {};

const m = html.match(/<script>\n([\s\S]*?)\n<\/script>/);
if (!m) { console.error("FAIL: no engine <script> block found"); process.exit(1); }

let C = {};
try {
  eval(m[1] + `; C = { BAKED_ASOF, LAST_KNOWN, TOKENS, RANKS, BENCH, BENCH2, BH, IN12,
    NET_MODEL, DILNEG, SPARKS30, UNLOCKS, NETFLOW, HISTORY, BACKFILL, HISTORY_CSV, BACKFILL_CSV };`);
} catch (e) {
  console.error("FAIL: engine script threw on evaluation — the build is not loadable");
  console.error("  " + e.message);
  process.exit(1);
}

/* ---------- structural invariants ---------- */
const need = ["BAKED_ASOF", "LAST_KNOWN", "TOKENS", "RANKS", "BENCH", "BENCH2", "BH",
  "IN12", "NET_MODEL", "DILNEG", "SPARKS30", "UNLOCKS", "NETFLOW"];
need.forEach(k => check(C[k] != null, `constant ${k} is missing or null`));

check(/^\d{4}-\d{2}-\d{2}$/.test(C.BAKED_ASOF), `BAKED_ASOF malformed: ${C.BAKED_ASOF}`);
if (wantAsof) check(C.BAKED_ASOF === wantAsof, `BAKED_ASOF is ${C.BAKED_ASOF}, expected ${wantAsof}`);

check(Array.isArray(C.TOKENS) && C.TOKENS.length >= 8, "TOKENS is not a populated array");
const syms = new Set();
C.TOKENS.forEach((t, i) => {
  check(!!t.sym, `TOKENS[${i}] has no sym`);
  check(!syms.has(t.sym), `duplicate token entry: ${t.sym}`);
  syms.add(t.sym);
  check(t.accrual && typeof t.accrual.note === "string" && t.accrual.note.length > 20,
    `${t.sym}: accrual.note missing or too short`);
  check(typeof t.unlock === "string" && t.unlock.length > 20, `${t.sym}: unlock note missing`);
  check(t.baked && typeof t.baked === "object", `${t.sym}: baked block missing`);
  ["feesAnn", "rev", "tvl", "vol30d"].forEach(k => {
    const v = t.baked[k];
    check(v === undefined || v === null || (typeof v === "number" && isFinite(v) && v >= 0),
      `${t.sym}.baked.${k} is not a finite non-negative number: ${v}`);
  });
});

/* every board seat must have a price basis and a rank */
Object.keys(C.RANKS).forEach(s => {
  check(syms.has(s), `RANKS names ${s} but TOKENS has no such entry`);
  check(C.LAST_KNOWN.bySym[s] != null, `RANKS names ${s} but LAST_KNOWN has no price basis`);
});
const ranks = Object.values(C.RANKS).sort((a, b) => a - b);
check(JSON.stringify(ranks) === JSON.stringify(ranks.map((_, i) => i + 1)),
  `RANKS are not a contiguous 1..n sequence: ${ranks.join(",")}`);

/* prices must be finite positives */
Object.entries(C.LAST_KNOWN.bySym).forEach(([s, k]) => {
  check(typeof k.price === "number" && isFinite(k.price) && k.price > 0,
    `LAST_KNOWN.${s}.price invalid: ${k.price}`);
  ["d24", "d7"].forEach(f => check(k[f] == null || (isFinite(k[f]) && Math.abs(k[f]) < 100),
    `LAST_KNOWN.${s}.${f} implausible: ${k[f]}`));
  warn(k.mc == null || k.fdv == null || k.mc <= k.fdv * 1.02,
    `LAST_KNOWN.${s}: market cap exceeds FDV (${k.mc} > ${k.fdv})`);
});

/* benchmark series must be parallel and sane */
const bl = C.BENCH.dates.length;
["board", "eth", "btc"].forEach(k => check(C.BENCH[k].length === bl,
  `BENCH.${k} length ${C.BENCH[k].length} != dates length ${bl}`));
const b2 = C.BENCH2.dates.length;
["board", "eth", "btc"].forEach(k => check(C.BENCH2[k].length === b2,
  `BENCH2.${k} length ${C.BENCH2[k].length} != dates length ${b2}`));
C.BENCH.dates.concat(C.BENCH2.dates).forEach(d =>
  check(/^\d{4}-\d{2}-\d{2}$/.test(d), `benchmark date malformed: ${d}`));
[...C.BENCH.board, ...C.BENCH2.board].forEach(v =>
  check(isFinite(v) && v > 0 && v < 1000, `benchmark index value implausible: ${v}`));
/* dates must be strictly increasing — a duplicated append is the failure mode here */
const strictly = a => a.every((d, i) => i === 0 || d > a[i - 1]);
check(strictly(C.BENCH.dates), "BENCH.dates are not strictly increasing (duplicate append?)");
check(strictly(C.BENCH2.dates), "BENCH2.dates are not strictly increasing (duplicate append?)");

/* history: one line per run basis, dates ordered, no duplicate date */
const histDates = C.HISTORY.map(h => h.d);
check(strictly(histDates), `HISTORY dates not strictly increasing: ${histDates.join(",")}`);
check(C.BACKFILL.length > 50, `BACKFILL has only ${C.BACKFILL.length} rows — archive looks truncated`);
const bfDates = C.BACKFILL.map(h => h.d);
check(strictly(bfDates), "BACKFILL dates not strictly increasing");

/* sparklines */
Object.entries(C.SPARKS30).forEach(([s, a]) => {
  check(Array.isArray(a) && a.length >= 20, `SPARKS30.${s} has only ${a && a.length} points`);
  check(a.every(v => isFinite(v) && v > 0), `SPARKS30.${s} contains a non-positive/NaN value`);
});

/* B/H scores in range */
Object.entries(C.BH).forEach(([s, v]) => {
  check(v.b >= 0 && v.b <= 100 && v.h >= 0 && v.h <= 100, `BH.${s} out of 0-100 range`);
});

/* net-flow legs must line up with IN12 */
C.NETFLOW.rows.forEach(r => {
  check(r.in12 === 0 || (isFinite(r.in12) && r.in12 >= 0), `NETFLOW ${r.sym}.in12 invalid`);
  if (C.IN12[r.sym] != null && r.in12 > 0) {
    const drift = Math.abs(C.IN12[r.sym] - r.in12) / Math.max(r.in12, 1);
    warn(drift < 0.001, `${r.sym}: IN12 (${C.IN12[r.sym]}) and NETFLOW.in12 (${r.in12}) disagree — they must refresh together`);
  }
});

/* ---------- rendered-surface invariants ---------- */
const stamp = (html.match(/id="buildstamp">([^<]*)</) || [])[1];
check(!!stamp, "footer build stamp (id=buildstamp) is missing");
if (stamp && wantBoard) check(stamp.includes(wantBoard),
  `build stamp "${stamp}" does not carry board ${wantBoard}`);
if (stamp && wantAsof) check(stamp.includes(wantAsof),
  `build stamp "${stamp}" does not carry baked date ${wantAsof}`);
check(!/__CONST:|__HTML:/.test(html), "unfilled build markers found in the published file");
check(html.includes("</html>"), "document is truncated — no closing </html>");

const bytes = Buffer.byteLength(html, "utf8");
warn(bytes < 200 * 1024, `${bytes} bytes exceeds Notion's 200 KiB inline cap (source_url upload required)`);

/* ---------- report ---------- */
console.log(`validate_build: ${FILE}`);
console.log(`  ${bytes.toLocaleString()} bytes · stamp: ${stamp || "??"}`);
console.log(`  ${C.TOKENS.length} tokens · ${Object.keys(C.RANKS).length} ranked seats · ` +
  `${C.HISTORY.length} history marks · ${C.BACKFILL.length} archive rows · ` +
  `BENCH2 ${b2} closes`);
warns.forEach(w => console.log(`  WARN  ${w}`));
if (fails.length) {
  console.error(`\nFAIL — ${fails.length} check(s) failed. DO NOT PUBLISH.`);
  fails.forEach(f => console.error(`  FAIL  ${f}`));
  process.exit(1);
}
console.log(`\nPASS — ${warns.length} warning(s), 0 failures. Safe to publish.`);
