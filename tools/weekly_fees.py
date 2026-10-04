#!/usr/bin/env python3
"""
weekly_fees.py - writes data/WEEKLY_FEES.js, the payload of the "Fees by week" chart.

  python3 tools/weekly_fees.py <repo> --runid <id> [--rawdir DIR] [--weeks 12]

Seats come from data/RANKS.js (ETH dropped: unscored, its series is network gas).
For every seat it pulls the daily fees and daily holders-revenue series from
api.llama.fi (cache-busted with &cb=<runid>), sums Thursday-Wednesday weeks ending
on the last Wednesday that is a complete UTC day, and writes one weekly total per
seat per week. A day in EXCLUDE is left out and its week is scaled from the other
days (AERO 2026-09-09 is the C57 bad reading, excluded on every surface).
Lump marks are drawn only for seats with a known payment clock (LUMP_CLOCK): a
week is marked when one of its days exceeds 4x the trailing-60-day median.
Run on every rebake (run_orders duty 6f). Fails loud: a seat with no slug, a fetch
error or an empty window exits 1 and nothing is written.
"""
import argparse, datetime as D, json, re, sys, time, urllib.request
from pathlib import Path

SLUGS = {"UNI": ["uniswap"], "HYPE": ["hyperliquid"], "JUP": ["jupiter"], "AERO": ["aerodrome"],
         "PENDLE": ["pendle"], "VVV": ["venice"], "AAVE": ["aave"], "LINK": ["chainlink"],
         "LIT": ["lighter"], "PUMP": ["pump.fun"], "RAY": ["raydium"], "SYRUP": ["maple"],
         "NEAR": ["near", "near-intents"], "LQTY": ["liquity", "liquity-v2"], "SOL": ["solana"]}
HOLDER_SLUGS = {"LQTY": ["liquity"]}
NAMES = {"UNI": "Uniswap", "HYPE": "Hyperliquid", "JUP": "Jupiter", "AERO": "Aerodrome",
         "PENDLE": "Pendle", "VVV": "Venice", "AAVE": "Aave", "LINK": "Chainlink", "LIT": "Lighter",
         "PUMP": "Pump.fun", "RAY": "Raydium", "SYRUP": "Maple", "NEAR": "NEAR", "LQTY": "Liquity",
         "SOL": "Solana"}
EXCLUDE = {"AERO": ["2026-09-09"]}
LUMP_CLOCK = {"PENDLE": "lump payment every other Monday", "VVV": "monthly lump payment"}
SKIP = {"ETH"}


def fail(msg):
    print(f"WEEKLY_FEES FAILED: {msg}", file=sys.stderr)
    sys.exit(1)


def fetch(slug, dtype, runid, rawdir):
    url = f"https://api.llama.fi/summary/fees/{slug}?dataType={dtype}&cb={runid}"
    last = None
    for attempt in range(3):
        try:
            raw = urllib.request.urlopen(url, timeout=60).read()
            if rawdir:
                Path(rawdir).mkdir(parents=True, exist_ok=True)
                (Path(rawdir) / f"weekly_{slug}_{dtype}.json").write_bytes(raw)
            rows = json.loads(raw).get("totalDataChart") or []
            return {D.datetime.fromtimestamp(ts, D.timezone.utc).date(): float(v or 0) for ts, v in rows}
        except Exception as e:
            last = e
            time.sleep(3)
    fail(f"{slug} {dtype}: {last}")


def series(sym, dtype, runid, rawdir):
    out = {}
    slugs = HOLDER_SLUGS.get(sym, SLUGS[sym]) if dtype == "dailyHoldersRevenue" else SLUGS[sym]
    for s in slugs:
        for d, v in fetch(s, dtype, runid, rawdir).items():
            out[d] = out.get(d, 0.0) + v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--runid", required=True)
    ap.add_argument("--rawdir", default=None)
    ap.add_argument("--weeks", type=int, default=12)
    a = ap.parse_args()
    ranks_src = (Path(a.repo) / "data" / "RANKS.js").read_text(encoding="utf-8")
    ranks = {k: int(v) for k, v in re.findall(r"([A-Z0-9]+)\s*:\s*(\d+)", ranks_src)}
    seats = [s for s, _ in sorted(ranks.items(), key=lambda kv: kv[1]) if s not in SKIP]
    missing = [s for s in seats if s not in SLUGS]
    if missing:
        fail(f"no fee slug for seat(s) {missing} - add them to SLUGS")

    last_day = D.datetime.now(D.timezone.utc).date() - D.timedelta(days=1)
    end = last_day - D.timedelta(days=(last_day.weekday() - 2) % 7)  # newest complete Wednesday
    weeks = []
    for k in range(a.weeks - 1, -1, -1):
        we = end - D.timedelta(days=7 * k)
        weeks.append((we - D.timedelta(days=6), we))

    fees, rev, lumps = {}, {}, {}
    for s in seats:
        F = series(s, "dailyFees", a.runid, a.rawdir)
        Hs = series(s, "dailyHoldersRevenue", a.runid, a.rawdir)
        ex = {D.date.fromisoformat(x) for x in EXCLUDE.get(s, [])}
        fa, ra, la = [], [], []
        for i, (ws, we) in enumerate(weeks):
            days = [ws + D.timedelta(days=j) for j in range(7)]
            kept = [d for d in days if d not in ex and d in F]
            if not kept:
                fa.append(0); ra.append(0); continue
            fa.append(round(sum(F[d] for d in kept) / len(kept) * 7))
            ra.append(round(sum(Hs.get(d, 0.0) for d in kept) / len(kept) * 7))
            if s in LUMP_CLOCK:
                for d in kept:
                    hist = sorted(F.get(d - D.timedelta(days=m), 0.0) for m in range(1, 61))
                    med = hist[30]
                    if med > 0 and F[d] > 4 * med:
                        la.append(i); break
        if sum(fa) <= 0:
            fail(f"{s}: empty fee window")
        fees[s], rev[s] = fa, ra
        if la:
            lumps[s] = la
    order = sorted(seats, key=lambda s: -sum(fees[s]))
    out = {"asof": end.isoformat(),
           "weeks": [[ws.isoformat(), we.isoformat()] for ws, we in weeks],
           "order": order,
           "names": {s: NAMES.get(s, s) for s in order},
           "fees": fees, "rev": rev, "lumps": lumps,
           "lumpNotes": {s: LUMP_CLOCK[s] for s in order if s in LUMP_CLOCK},
           "excluded": {s: v for s, v in EXCLUDE.items() if s in order}}
    p = Path(a.repo) / "data" / "WEEKLY_FEES.js"
    p.write_text(json.dumps(out, separators=(",", ":")) + "\n", encoding="utf-8")
    tot = [sum(fees[s][i] for s in order) for i in range(len(weeks))]
    print(f"WEEKLY_FEES: {len(order)} seats, weeks {weeks[0][0]} .. {weeks[-1][1]}; "
          f"last two ${tot[-2]/1e6:.1f}M, ${tot[-1]/1e6:.1f}M")


if __name__ == "__main__":
    main()
