#!/usr/bin/env python3
"""
validate_prose.py — catches the failure validate_build.js structurally cannot see:
PROSE THAT RESTATES A NUMBER, DRIFTING AWAY FROM THE NUMBER IT RESTATES.

WHY THIS EXISTS. The build pipeline doc has warned since 2026-07-27 that prose carrying
data claims lives in the payload and goes stale because a data update cannot reach it.
The warning was documentation, not a control, so on 2026-07-31 it happened again on five
names at once — a doc a human read once is not a gate. This is the gate.

SCOPE, so it is not over-trusted: it checks only claims that are SUPPOSED to restate a
baked value — "MC/Rev ~NNx", "MC/burn ~NNx", and "rev/burn/holders rev $N.NM/yr". It does
NOT police in-legs, emissions, cumulative totals, monitor estimates or historical asides,
because those legitimately differ and a checker that cries wolf gets ignored. Structural
coherence remains validate_build.js's job; number correctness remains validate_prints.py's.
"""
import json, re, sys, os
D=sys.argv[1] if len(sys.argv)>1 else '.'
T=open(os.path.join(D,'data/TOKENS.js')).read()
LK=open(os.path.join(D,'data/LAST_KNOWN.js')).read()
px={m.group(1): float(m.group(2)) for m in re.finditer(r'(\w+):\s*\{ price:([0-9.e+-]+)', LK)}
blocks={}
for m in re.finditer(r'\{ sym:"(\w+)",(.*?)(?=\n  \{ sym:"|\n\])', T, re.S):
    blocks[m.group(1)]=m.group(2)
fails=warns=checks=0
for sym, blk in blocks.items():
    bm=re.search(r'baked:\{([^}]*)\}', blk)
    cm=re.search(r'circ:([0-9.e+]+)', blk)
    if not bm or not cm or sym not in px: continue
    baked={k.group(1): float(k.group(2)) for k in re.finditer(r'(\w+):([0-9.e+]+)', bm.group(1))}
    rev=baked.get('rev'); mc=float(cm.group(1))*px[sym]
    if not rev: continue
    true_mult=mc/rev
    prose=re.sub(r'baked:\{[^}]*\}','',blk)
    for m in re.finditer(r'MC/(?:Rev|burn)\s*[~≈]?\s*([0-9,]+(?:\.[0-9]+)?)\s*[x×]', prose):
        checks+=1; claimed=float(m.group(1).replace(',',''))
        if abs(claimed/true_mult-1) > 0.05:
            fails+=1
            print(f"FAIL  {sym}: prose says MC/Rev ~{claimed}x; baked rev ${rev/1e6:,.2f}M at price {px[sym]:g} gives {true_mult:.1f}x")
    for m in re.finditer(r'(?:rev|revenue|burn|burns)[^.$]{0,40}\$([0-9]+(?:\.[0-9]+)?)M(?:/yr| ann)', prose):
        checks+=1; claimed=float(m.group(1))*1e6
        if abs(claimed/rev-1) > 0.05:
            warns+=1
            ctx=prose[max(0,m.start()-45):m.start()+22].replace('\n',' ')
            print(f"WARN  {sym}: prose figure ${claimed/1e6:,.2f}M/yr vs baked rev ${rev/1e6:,.2f}M  …{ctx.strip()[-70:]}…")
print(f"\nvalidate_prose: {checks} claim(s) checked · {fails} FAIL · {warns} WARN")
sys.exit(1 if fails else 0)
