#!/usr/bin/env python3
"""
split.py — mechanically separate the dashboard monolith into:
  shell.html      the immutable engine (HTML + CSS + JS functions + law comments),
                  with each data constant replaced IN PLACE by a marker
  const_meta.json the per-constant emission spec (leading/trailing law comments)
  slots_raw.json  the original JS source of every extracted span (audit trail)

Design note: constants are replaced IN PLACE rather than hoisted into one block.
Nothing is reordered, so evaluation order, adjacency to law comments, and the
file's layout are all preserved exactly. The only difference between the original
and a rebuild is the serialization of the data values themselves.

Usage: python3 split.py <input.html> <outdir>
"""
import json
import re
import sys
from pathlib import Path

# Data constants: everything a scored run can change.
DATA_CONSTS = [
    "BAKED_ASOF", "LAST_KNOWN", "TOKENS",
    "HISTORY_CSV", "BACKFILL_CSV",
    "UNLOCKS", "NETFLOW", "IN12", "NET_MODEL", "DILNEG",
    "SPARKS30", "BENCH", "BENCH2", "BH", "RANKS", "B2GRADES",
    # EST_GROSS is declared INSIDE renderGrossBars() but is pure data — per-token basis
    # captions that go stale with the prints. Left in the engine it would be unreachable
    # to a data-only update, which is exactly how the "venicestats implies ~$14M/yr" line
    # survived four days past the finding that contradicted it.
    "EST_GROSS",
]

# Constants that stay in the shell because they are engine, not data:
#   SLOTCOLORS, SERIESCOLORS, GRAY_SERIES, HISTORY, BACKFILL, HIST_ALL, COLS, CG_URL


def scan_value(text, i):
    """From index i (just after '='), return index just past the value's terminating ';'.
    Tracks nesting depth and skips over strings, template literals and comments."""
    depth = 0
    n = len(text)
    while i < n:
        c = text[i]
        # line comment
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        # block comment
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            if j < 0:
                raise ValueError("unterminated block comment")
            i = j + 2
            continue
        # strings and template literals
        if c in "'\"`":
            q = c
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == q:
                    i += 1
                    break
                i += 1
            continue
        if c in "{[(":
            depth += 1
        elif c in "}])":
            depth -= 1
        elif c == ";" and depth == 0:
            return i + 1
        i += 1
    raise ValueError("unterminated value")


def trailing_comment(text, i):
    """Consume any extra semicolons and a same-line trailing comment after the value.

    Returns (end_index, gap, comment). `gap` is the VERBATIM text between the value's
    terminating ';' and the comment — extra semicolons and whitespace included — so a
    rebuild reproduces the original spacing exactly instead of normalising it."""
    n = len(text)
    k = i
    while k < n and (text[k] == ";" or text[k] in " \t"):
        k += 1
    if k + 1 < n and text[k] == "/" and text[k + 1] == "*":
        e = text.find("*/", k + 2)
        if e >= 0 and "\n" not in text[i:k]:
            return e + 2, text[i:k], text[k:e + 2]
    # no trailing comment: keep any extra semicolons, stop before trailing whitespace
    j = i
    while j < n and text[j] == ";":
        j += 1
    return j, text[i:j], ""


def leading_comment(text, start):
    """Return the block comment immediately preceding `start`, if any (same or prior lines)."""
    head = text[:start]
    m = re.search(r"(/\*(?:[^*]|\*(?!/))*\*/)\s*$", head)
    return m.group(1) if m else ""


def main():
    src_path, outdir = Path(sys.argv[1]), Path(sys.argv[2])
    outdir.mkdir(parents=True, exist_ok=True)
    text = src_path.read_text(encoding="utf-8")

    spans = []
    for name in DATA_CONSTS:
        m = re.search(r"\bconst\s+" + re.escape(name) + r"\s*=", text)
        if not m:
            raise SystemExit(f"FATAL: const {name} not found")
        eq_end = m.end()
        val_end = scan_value(text, eq_end)
        after, extra_semis, tail = trailing_comment(text, val_end)
        lead = leading_comment(text, m.start())
        # preserve the exact declaration spelling ("const X =" vs "const X=") and the
        # whitespace before the value, so a rebuild is byte-identical rather than merely
        # equivalent — byte-identity is the acceptance test for a lossless split.
        raw_value = text[eq_end:val_end - 1]
        pre_ws = raw_value[:len(raw_value) - len(raw_value.lstrip())]
        spans.append({
            "name": name,
            "start": m.start(),
            "end": after,
            "raw": text[m.start():after],
            "decl_prefix": text[m.start():eq_end],
            "pre_value_ws": pre_ws,
            "value_src": raw_value.strip(),
            "extra_semis": extra_semis,
            "post_comment": tail,
            "lead_comment": lead,
        })

    # ---- HTML slots: the rendered bits that carry dates / versions ----
    html_slots = {}
    html_specs = []

    m = re.search(r'<span class="badge">Updated [^<]*</span>', text)
    html_specs.append(("updatedChip", m.start(), m.end(), m.group(0)))

    m = re.search(r'<span class="badge" id="buildstamp">[^<]*</span>', text)
    html_specs.append(("buildstamp", m.start(), m.end(), m.group(0)))

    m = re.search(r'<div class="sub">\n(.*?)\n  </div>', text, re.S)
    html_specs.append(("subBasis", m.start(1), m.end(1), m.group(1)))

    for idx, mm in enumerate(re.finditer(r'<span class="asofchip">[^<]*</span>', text)):
        html_specs.append((f"asofchip{idx}", mm.start(), mm.end(), mm.group(0)))

    # Static prose blocks that carry data claims. Blocks with an id= are filled by the
    # engine at render time and must stay in the shell; the rest are hand-written text
    # that goes stale exactly like a number does, so they belong in the data payload.
    for idx, mm in enumerate(re.finditer(
            r'<div class="axis-note">(?!\s*</div>)(?![^>]*id=)(.*?)</div>', text, re.S)):
        html_specs.append((f"axisnote{idx}", mm.start(1), mm.end(1), mm.group(1)))
    for idx, mm in enumerate(re.finditer(
            r'<div class="hint">(?![^>]*id=)(.*?)</div>', text, re.S)):
        html_specs.append((f"hint{idx}", mm.start(1), mm.end(1), mm.group(1)))

    # Some slots nest (an asofchip lives inside a hint block). Keep the CONTAINING span
    # and drop the contained one, so the outer slot carries the inner text as part of its
    # payload — one editable region instead of two that must agree.
    html_specs.sort(key=lambda x: (x[1], -(x[2] - x[1])))
    kept = []
    for spec in html_specs:
        if any(k[1] <= spec[1] and spec[2] <= k[2] for k in kept):
            continue
        kept.append(spec)
    html_specs = kept

    for name, s, e, raw in html_specs:
        html_slots[name] = raw

    # ---- build the shell: replace every span with a marker, right-to-left ----
    replacements = [(s["start"], s["end"], f"/*__CONST:{s['name']}__*/") for s in spans]
    replacements += [(s, e, f"<!--__HTML:{n}__-->") for n, s, e, _ in html_specs]
    replacements.sort(key=lambda r: r[0])

    # sanity: no overlaps
    for a, b in zip(replacements, replacements[1:]):
        if a[1] > b[0]:
            raise SystemExit(f"FATAL: overlapping spans at {a[1]} / {b[0]}")

    shell = text
    for s, e, marker in reversed(replacements):
        shell = shell[:s] + marker + shell[e:]

    (outdir / "shell.html").write_text(shell, encoding="utf-8")

    const_meta = [{
        "name": s["name"],
        "decl_prefix": s["decl_prefix"],
        "pre_value_ws": s["pre_value_ws"],
        "lead_comment": s["lead_comment"],
        "gap": s["extra_semis"],
    } for s in spans]
    (outdir / "const_meta.json").write_text(
        json.dumps(const_meta, indent=2, ensure_ascii=False), encoding="utf-8")

    (outdir / "slots_raw.json").write_text(json.dumps(
        {"consts": {s["name"]: s["raw"] for s in spans}, "html": html_slots},
        indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- data payload: one small file per constant, so a run edits only what changed ----
    datadir = outdir / "data"
    datadir.mkdir(exist_ok=True)
    for s in spans:
        (datadir / f"{s['name']}.js").write_text(s["value_src"] + "\n", encoding="utf-8")
    (datadir / "_html.json").write_text(
        json.dumps(html_slots, indent=2, ensure_ascii=False), encoding="utf-8")
    # Trailing annotations describe the CURRENT data basis ("AAVE rev = T2 est (adapter
    # waking...)"), so they go stale with the numbers and belong in the daily payload,
    # not in the immutable shell bundle.
    (datadir / "_comments.json").write_text(json.dumps(
        {s["name"]: s["post_comment"] for s in spans if s["post_comment"]},
        indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"original      {len(text):>8,} chars")
    print(f"shell         {len(shell):>8,} chars")
    extracted = sum(len(s['raw']) for s in spans) + sum(len(v) for v in html_slots.values())
    print(f"extracted     {len(text) - len(shell) + sum(len(m) for _,_,m in replacements):>8,} chars of data")
    print(f"consts        {len(spans)}  html slots {len(html_slots)}")
    for s in spans:
        print(f"  {s['name']:<14} {len(s['raw']):>7,} chars"
              + ("  +post-comment" if s["post_comment"] else ""))


if __name__ == "__main__":
    main()
