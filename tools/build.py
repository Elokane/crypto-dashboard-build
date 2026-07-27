#!/usr/bin/env python3
"""
build.py — reassemble the full dashboard from the immutable shell + the data payload.

  python3 build.py <shelldir> <out.html> [--stamp "build v19.1 · board v14.1 · baked 2026-07-27"]

<shelldir> holds shell.html, const_meta.json and data/ (one .js per constant plus
_html.json). Every marker in the shell must be filled and every data file must be
consumed — a mismatch is a hard error, never a silent partial build.

This is the only sanctioned way to produce the dashboard. Nothing is retyped: the
engine is copied byte-for-byte from shell.html and only the data values are spliced.
"""
import argparse
import json
import re
import sys
from pathlib import Path


def fail(msg):
    print(f"BUILD FAILED: {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("shelldir")
    ap.add_argument("out")
    ap.add_argument("--stamp", default=None,
                    help="overwrite the footer build stamp text")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    d = Path(args.shelldir)
    shell = (d / "shell.html").read_text(encoding="utf-8")
    meta = {m["name"]: m for m in json.loads((d / "const_meta.json").read_text(encoding="utf-8"))}
    datadir = d / "data"

    html_slots = json.loads((datadir / "_html.json").read_text(encoding="utf-8"))
    cpath = datadir / "_comments.json"
    comments = json.loads(cpath.read_text(encoding="utf-8")) if cpath.exists() else {}

    # ---- fill constant markers ----
    used = set()
    def const_sub(m):
        name = m.group(1)
        f = datadir / f"{name}.js"
        if not f.exists():
            fail(f"data/{name}.js missing but shell expects it")
        used.add(name)
        value = f.read_text(encoding="utf-8").rstrip("\n")
        mm = meta.get(name, {})
        out = (mm.get("decl_prefix", f"const {name} =")
               + mm.get("pre_value_ws", " ")
               + value + ";" + mm.get("gap", "") + comments.get(name, ""))
        return out

    built, n_const = re.subn(r"/\*__CONST:([A-Z0-9_]+)__\*/", const_sub, shell)

    # ---- fill html markers ----
    used_html = set()
    def html_sub(m):
        name = m.group(1)
        if name not in html_slots:
            fail(f"html slot '{name}' missing from data/_html.json")
        used_html.add(name)
        return html_slots[name]

    built, n_html = re.subn(r"<!--__HTML:([A-Za-z0-9_]+)__-->", html_sub, built)

    # ---- integrity gates ----
    leftover = re.findall(r"/\*__CONST:[^*]+__\*/|<!--__HTML:[^-]+-->", built)
    if leftover:
        fail(f"unfilled markers remain: {leftover[:5]}")

    unknown = set(comments) - set(m["name"] for m in meta.values() if True) - used
    if unknown:
        fail(f"_comments.json names unknown constants: {sorted(unknown)}")
    on_disk = {p.stem for p in datadir.glob("*.js")}
    if on_disk - used:
        fail(f"data files never used by the shell: {sorted(on_disk - used)}")
    if set(html_slots) - used_html:
        fail(f"html slots never used by the shell: {sorted(set(html_slots) - used_html)}")

    if args.stamp:
        built, n = re.subn(r'(<span class="badge" id="buildstamp">)[^<]*(</span>)',
                           lambda m: m.group(1) + args.stamp + m.group(2), built)
        if n != 1:
            fail(f"expected exactly one buildstamp, patched {n}")

    # structural smoke tests — cheap, catch a catastrophic splice
    for probe in ["</html>", "renderAll();", "const TOKENS", "id=\"buildstamp\"",
                  "function renderBench", "BACKFILL_CSV"]:
        if probe not in built:
            fail(f"structural probe missing from output: {probe!r}")
    if built.count("<script>") != 1:
        fail(f"expected exactly 1 <script> block, found {built.count('<script>')}")

    Path(args.out).write_text(built, encoding="utf-8")

    if not args.quiet:
        b = len(built.encode("utf-8"))
        print(f"built {args.out}: {len(built):,} chars / {b:,} bytes "
              f"({n_const} consts, {n_html} html slots)")
        m = re.search(r'id="buildstamp">([^<]*)<', built)
        print(f"stamp: {m.group(1) if m else '??'}")
        if b > 200 * 1024:
            print(f"WARNING: {b:,} bytes exceeds Notion's 200 KiB inline attachment cap "
                  f"— source_url upload required", file=sys.stderr)


if __name__ == "__main__":
    main()
