#!/usr/bin/env python3
"""
scope_gate.py — the Scope law's arithmetic (Methodology §C20; form rules of 2026-09-02).

One rule: guest-facing text carries findings, not process, and every section has a
budget. Form rules (2026-09-02, owner): nothing but the embed under "Live dashboard";
"How to read this page" is a closed toggle heading with no history and no correction-ID
explainer; no "accountability" anywhere; the dashboard header carries no prose and its
sourcing/process text lives only in the footer; per-token notes are short and emphasise
the outlier fact or date. This script is the budget. A write that fails it is not made; a dashboard
build that fails it is not filed. Where the law's prose and this script disagree, the
script governs until the prose is amended and the script changed in the same session.

Rev 2026-11-05 (owner, closes #337): live mode first rewrites the form Notion now serves (<toggle>, <toggle heading="h1">, <b>, <i>, embed caption
block) to the form the checks read. No cap, list or rule moved; the page was brought inside the rest by cutting and rolling.

Rev 2026-09-13 (owner directive, Methodology §C27): the Live page gains the second reader's section
"# 📡 Signals — business & revenue watch" between the Market update and the Top 7 picks — 250 words outside
its single closed "Earlier signals" toggle (400 inside) — and the above-Archive byte cap rises 90,000 -> 92,000
to house it. The only raise since the Scope law was written.

Four files, four modes:

  python3 scope_gate.py live  <live_body.md>     # Notion Live page body (fetched dump, <content> extracted)
  python3 scope_gate.py dash  <repo_dir>         # dashboard build repo (data/*.js, data/_html.json)
  python3 scope_gate.py state <state.json>       # claude/state.json
  python3 scope_gate.py orders <run_orders.json>  # claude/run_orders.json (duty lists; layout ruling 2026-09-24)

Exit 0 = PASS (warnings allowed). Exit 1 = FAIL — do not write / do not file.
Stdlib only. Identical copies live at claude/tools/scope_gate.py (project, canonical)
and tools/scope_gate.py (dashboard build repo, run by publish.sh). Change both together.
"""
import json, re, sys, os

# ----------------------------------------------------------------------------- budgets
# Words, not characters. The nearer the top of a surface, the tighter the budget.
LIVE_CAPS = {
    "_preamble":                    100,   # italic intro + About callout
    "# Thesis & framework":         140,
    "# How to read this page":      720,
    "# Live dashboard":               0,   # NOTHING between the heading and the embed
    "### Market update":            400,
    "# 📡 Signals":                 250,   # second reader's section (§C27): intro line + active signals, outside its one toggle
    "# 🏆 Top 7 picks":            1500,   # header line + ranked-on line + seven cards
    "# Vetted":                     320,
    "# X radar":                    950,   # intro + latest sweep (table included) + standing notes
    "# Crypto-exposed equities":    560,   # text outside toggles; toggle bodies capped separately
    "# What changed":               140,   # text outside toggles (intro + corrections index)
    "# Verification queue":         160,   # open questions about the businesses, never about the engine
    "# Engine cadence":              80,   # when the page updates, nothing more
    "# Honesty box":                140,   # which figures to treat with care, in plain words
}
LIVE_CARD_CAP        = 190   # each pick card (header + one-line + metrics + judgment)
LIVE_VETTED_OUTSIDE_CAP = 40  # Vetted: at most an intro line outside the per-token toggles
LIVE_VETTED_SUMMARY_CAP = 32  # Vetted: one summary line per token — the rejection in plain words
LIVE_VETTED_TOGGLE_CAP  = 150 # Vetted: the detail inside each closed toggle
LIVE_LOG_DAYS        = 14    # What-changed toggles older than this belong in the Archive
LIVE_LOG_TOGGLE_CAP  = 230   # words per What-changed toggle body
LIVE_INDEX_TOGGLE_CAP = 900  # the corrections-index toggle at the top of the log (one line per correction)
LIVE_EQ_TOGGLE_CAP   = 1800  # words per equities dossier toggle (research notes, mid-page)
LIVE_SIGNALS_TOGGLE_CAP = 400  # the Signals section's single closed "Earlier signals" toggle
LIVE_MAX_ABOVE_ARCHIVE_BYTES = 92_000  # 90_000 until 2026-09-13; raised by owner directive to house the Signals section (§C27)

DASH_CAPS = {   # data/_html.json slots, by name prefix (ratcheted 2026-08-27; caps only go down)
    "updatedChip": 8, "footBasis": 40, "hint": 32, "axisnote": 50, "buildstamp": 12,
}
DASH_RETIRED_SLOTS = {"subBasis"}   # header prose — retired 2026-09-02; build.py also refuses an unused slot
DASH_NOTE_CAPS = {  # the four rendered note slots (data-bearing, regenerated each bake)
    "NET_NOTE": 30, "BENCH_NOTE": 55, "NETFLOW_NOTE": 35, "UNLOCK_NOTE": 40,
}
TILE_PROSE_FORBIDDEN = [  # TOKENS.js note/unlock: mechanism only — figures live in the data grid
    (r"\$[\d,.]+", "dollar figure in tile prose (figures belong to the data grid)"),
    (r"\b\d{1,2}/\d{1,2}\b", "data-vintage date in tile prose"),
    (r"window ending", "window reference in tile prose"),
    (r"\bas of\b", "as-of stamp in tile prose"),
    (r"\bat the [\d.]+ price\b|price basis", "price-basis reference in tile prose"),
]
DASH_FIELD_CAPS = {  # rendered strings inside data/*.js (ratcheted 2026-08-27)
    "accrual.note": 40, "unlock": 42, "tip": 45, "net": 10, "txt": 12, "calc": 70,
    "zeros": 30, "EST_GROSS": 35, "asof": 15, "comment": 60,
}

STATE_CAPS = {  # words per string leaf, by top-level key (default applies elsewhere)
    "_default": 90, "_readme": 160, "updated_by": 160, "board_reproducibility_flag": 160,
    "run_orders": 140, "_write_rule": 160, "_cost_rule": 160, "_closing_assertion": 220,
    "open_queue_top": 70, "corrections_latest": 90, "triggers": 90,
}
STATE_MAX_BYTES = 66_000       # 90_000 until 2026-09-24; owner layout ruling: the duty lists moved to run_orders.json
ORDERS_MAX_BYTES = 36_000      # claude/run_orders.json (layout ruling 2026-09-24)
ORDERS_DUTY_CAP = 140          # words per duty, as the state cap for run_orders was

# ----------------------------------------------------------------------------- patterns
# Process, self-description, verification chatter, internal references. Case-insensitive.
FORBIDDEN = [
    (r"§\s*C\d+\w*",                                   "law section reference"),
    (r"\bqueue\s*#\s*\d+",                              "queue id"),
    (r"(?<![\w/$])#\d{3}\b",                            "bare 3-digit id"),
    (r"\(\d{2,3}\)",                                    "queue id in parentheses"),
    (r"\bclaude/|\bstate\.json\b|\brun-log\b|\bshard\b|\bsubagent\b", "file/store reference"),
    (r"\b\w+\.(?:py|md|csv|json)\b",                    "file name"),
    (r"\bproject_(?:read|write)\b|\bnotion[-_]fetch\b|\bupdate_content\b", "tool name"),
    (r"\bthis run\b|\bthe run\b|\brun's\b|\bscored run\b|\bmorning run\b|\bweekend run\b|\bmidday run\b", "run narration"),
    (r"\bthe page (?:would|says|said|keeps|records|is recording|recorded)\b", "page self-description"),
    (r"\brather than (?:silently|quietly|letting|assum\w*|imply\w*|gloss\w*|carry\w*|leav\w*)", "process reasoning"),
    (r"\b(?:said|says|saying) so\b",                    "said-so"),
    (r"\b(?:stated|recorded|disclosed|named|kept|left) rather than\b", "process reasoning"),
    (r"\bworth (?:saying|stating|noting|recording|remembering|keeping|a reader)\b", "editorial aside"),
    (r"\bdeserves (?:saying|stating|noting)\b",         "editorial aside"),
    (r"\bfor the record\b",                             "editorial aside"),
    (r"\bhonest(?:ly)?\b",                              "honesty talk"),
    (r"\b(?:second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|\w+teenth|\w+tieth|twenty-\w+|thirty-\w+|forty-\w+|\d+(?:st|nd|rd|th))\s+consecutive\b", "consecutive counter"),
    (r"\bconsecutive (?:readings?|days?|slots?|sessions?|runs?|closes?)\b", "consecutive counter"),
    (r"\bharness\b|\bchecker\b|\bassert\w*\b|\bre-?fetch\w*\b|\bbyte-identical\b|\bsha256\b|\binvariants?\b|\bround[- ]trip\b|\bcache-bust\w*\b", "verification chatter"),
    (r"\bintegrity check\w*\b",                         "verification chatter"),
    (r"\bnot narrated\b|\bnarrat(?:e|ed|es|ing|ion)\b",   "narration talk"),
    (r"\bowner directive\b|\bowner-approved\b|\bowner decision\b|\bowner action\b|\bowner-requested\b", "governance reference"),
    (r"\bENGINE:|\bengine law\b|\brebake\w*\b",         "engine instruction"),
    (r"\bdil-neg\b",                                    "internal jargon"),
    (r"\bprior gap state\b|\bearlier gap state\b",      "stale honesty-box history"),
    (r"\baccountab\w*",                                  "accountability talk (owner: never)"),
    (r"\bsign-flip guard\b|\brank weight\b",            "ranking-rule internals"),
    (r"\badapter\b|\bmachine-readable\b|\bprovider-implied\b|\bhand-set\b", "sourcing/process talk"),
    (r"\bembedded views?\b|\bself-refresh\w*\b|\bstandalone file\b|\blive fetch\w*\b", "embed self-description"),
]
PLAIN_FORBIDDEN = [   # owner, 2026-09-02: plain English above the log — no rule internals, no data-window or sourcing mechanics
    (r"\b(?:primary|net|business|valuation|hype) dial\b|\bdials?\b(?= (?:abstain|read|says|agree))", "ranking-rule jargon (dial)"),
    (r"\bhysteresis\b|\bpersistence\b|\babstain\w*\b|\bscoreable\b|\bwritten scale\b|\bno rank weight\b", "ranking-rule internals"),
    (r"\b(?:\w+ )?legs? (?:of|carry|carries)\b|\bthe (?:\d+% |net(?:-flow)? |valuation |business )?leg\b", "ranking-rule internals (legs)"),
    (r"\b(?:second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d+(?:st|nd|rd|th)) (?:scored )?reading\b|\breadings\b|\breading(?:s)? (?:on|for|of) the\b", "reading counters"),
    (r"\bprints?\b|\bprinted\b|\bprinting\b", "'print' jargon — say figure, revenue, payment"),
    (r"\bfee window\b|\bwindow (?:advanced|advances|rolls?|rolled|stood|stands)\b|\bUTC\b", "data-window mechanics"),
    (r"\battribution artifact\b|\bzero-print\b|\bsame-weekday\b|\bex-zero\b", "data-check mechanics"),
    (r"\bsecond (?:price )?(?:source|origin)\b|\bone source\b|\bhourly (?:shape|tape)\b|\bsource(?:s)? (?:is|are|was|were) (?:un)?reachable\b", "sourcing narration"),
    (r"\bdata note\b|\bsix-name context\b|\bseed[- ]six\b", "retired context / data note"),
]
HOWTO_FORBIDDEN = [   # "How to read this page": definitions only — no history, no correction bookkeeping
    (r"\b(?:since|from|as of|until|before|after) \d{1,2} (?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\b", "history in the key"),
    (r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w* \d{4}\b|\b20\d\d-\d\d-\d\d\b", "date in the key"),
    (r"\bcorrection\w*\b|\bC-number\w*|\bnumbered ID\b|\bsee the log\b", "correction bookkeeping in the key"),
]
DASH_EXTRA_FORBIDDEN = [
    (r"\bprints?\b|\bprinted\b", "'print' jargon in dashboard prose"),
    (r"\b(?:RESOLVED|CORRECTED|STATUS|UPDATED|NEW|NOTE|PRINT|RE-VERIFIED|RESTATED|WITHDRAWN|MEASURED|REFRESH|EARLY RUN)\b[^.;]{0,14}\b\d{1,2}/\d{1,2}\b", "dated run-stamp"),
    (r"\b\d{1,2}/\d{1,2}(?: [A-Z]{2,})?:", "dated run-stamp"),
    (r"\bsee the log\b|\bsee the note\b", "cross-reference to a log the dashboard does not have"),
]

TICKERS = set("""HYPE AERO UNI JUP PENDLE VVV ETH BTC AAVE LIT PUMP TAO ONDO ENA HNT RENDER SOL USDC USDT GHO
MC FDV TVL VCP MOS DAT DATS DEX DEXS ATH ARR API APY SEC OCC DTCC ETF ETFS USD PT UTC AM PM EW T1 T2 T3 T4
MSTR PURR BMNR FWDI USDE COIN HOOD GLXY CRCL MARA RIOT CLSK IREN CORZ WULF HUT BKKT PYPL NAV HPC BME IPO
EIP LP LPS DAO ATM OTC CEO CFO NYSE OI CSV JSON HTML LIVE SNAPSHOT OFFLINE STRC STRK STRF STRD""".split())
SHOUT_RE = re.compile(r"\b[A-Z][A-Z'\-]{2,}\b")

# ----------------------------------------------------------------------------- helpers
def words(s):
    s = re.sub(r"<[^>]+>", " ", s)                 # html tags
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s) # links -> text
    s = re.sub(r"[*_`~|]", " ", s)                 # markdown marks, table pipes
    return len(re.findall(r"[A-Za-z0-9$€£%][\w$€£%.,/:+\-×'’]*", s))

def shouting(text):
    """Runs of >=4 consecutive ALL-CAPS words where at least two are not tickers/acronyms."""
    hits = []
    for line in text.split("\n"):
        toks = re.findall(r"\S+", re.sub(r"<[^>]+>", " ", line))
        run = []
        for t in toks + ["."]:
            core = re.sub(r"[^A-Za-z'\-]", "", t)
            if core and SHOUT_RE.fullmatch(core):
                run.append(core)
            else:
                if len(run) >= 4 and sum(1 for w in run if w.upper() not in TICKERS) >= 2:
                    hits.append(" ".join(run))
                run = []
    return hits

def scan_patterns(text, patterns, label):
    fails = []
    for pat, why in patterns:
        for m in re.finditer(pat, text, re.I):
            ctx = text[max(0, m.start()-40):m.end()+40].replace("\n", " ")
            fails.append(f"{label}: {why} — …{ctx.strip()}…")
    for s in shouting(text):
        fails.append(f"{label}: shouting — {s[:80]}")
    return fails

# ----------------------------------------------------------------------------- live
def split_toggles(text):
    """Return (outside_text, [ (summary, body) ])."""
    toggles = re.findall(r"<details>\s*\n\s*<summary>(.*?)</summary>\s*\n(.*?)\n\s*</details>", text, re.S)
    outside = re.sub(r"<details>.*?</details>", " ", text, flags=re.S)
    return outside, toggles

def normalize_served(body):
    """Rev 2026-11-05 (owner, #337): Notion now serves <toggle> and HTML-style marks, not the <details> and
    Markdown this gate was written for. Rewrite the served form to the form the checks read. No cap changes.
    A body with no <toggle> passes through untouched."""
    if "<toggle" not in body:
        return body
    out, stack, lines, i = [], [], body.split("\n"), 0
    while i < len(lines):
        l = lines[i]
        s = l.strip()
        if s in ("<toggle>", '<toggle heading="h1">'):
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            title = lines[j].strip() if j < len(lines) else ""
            if s == "<toggle>":
                out += ["<details>", f"<summary>{title}</summary>"]
                stack.append("details")
            else:
                out.append(f'# {title} {{toggle="true"}}')
                stack.append("h1")
            i = j + 1
            continue
        if s == "</toggle>" and stack:
            if stack.pop() == "details":
                out.append("</details>")
            i += 1
            continue
        out.append(("\t" + l) if ("h1" in stack and l.strip()) else l)
        i += 1
    return "\n".join(out)

def live(path):
    body = normalize_served(open(path, encoding="utf-8").read())
    fails, warns = [], []
    if "\\</details\\>" in body or "\\<details\\>" in body:
        fails.append("escaped literal </details> present — a fake toggle")
    if body.count("<details>") != body.count("</details>"):
        fails.append(f"toggle open/close mismatch: {body.count('<details>')} vs {body.count('</details>')}")
    if body.count("<embed") != 1:
        fails.append(f"expected exactly one <embed>, found {body.count('<embed')}")
    if "**About this page**" in body or "not investment advice or a solicitation" in body:
        fails.append("About/disclaimer callout present — removed by the owner 2026-09-02; the intro line is the whole preamble")
    lines = body.rstrip("\n").split("\n")
    if not lines[-1].strip().startswith(("*By Dor Konforty", "<i>By Dor Konforty")):
        fails.append("byline is not the last line")

    # sections: split on top-level '# ' headings; Market update is a '###' inside Live dashboard
    idx = [i for i, l in enumerate(lines) if l.startswith("# ")]
    sections = []
    if idx and idx[0] > 0:
        sections.append(("_preamble", "\n".join(lines[:idx[0]])))
    for k, i in enumerate(idx):
        j = idx[k+1] if k+1 < len(idx) else len(lines)
        sections.append((lines[i], "\n".join(lines[i+1:j])))
    names = [n for n, _ in sections]
    arch = next((k for k, n in enumerate(names) if n.startswith("# Archive")), None)
    if arch is None:
        fails.append("no '# Archive' section — history must live in collapsed toggles at the bottom")
    else:
        above = "\n".join(t for n, t in sections[:arch])
        if len(above.encode()) > LIVE_MAX_ABOVE_ARCHIVE_BYTES:
            fails.append(f"text above the Archive is {len(above.encode()):,} bytes; cap {LIVE_MAX_ABOVE_ARCHIVE_BYTES:,}")
        if arch != len(sections) - 1:
            fails.append("Archive must be the last section (footer links + byline live inside it)")

    for name, text in sections[: (arch if arch is not None else len(sections))]:
        if name.startswith("# Live dashboard"):
            head, _, mu = text.partition("### Market update")
            head_wo_embed = "\n".join(l for l in re.sub(r"<embed.*?</embed>", "", head, flags=re.S).split("\n") if "<embed" not in l)
            n = words(head_wo_embed)
            if n > LIVE_CAPS["# Live dashboard"]:
                fails.append(f"text between the Live dashboard heading and the embed ({n} words) — the embed stands alone")
            if mu:
                n = words(mu)
                if n > LIVE_CAPS["### Market update"]:
                    fails.append(f"Market update {n} words > {LIVE_CAPS['### Market update']}")
            fails += scan_patterns(text, FORBIDDEN + PLAIN_FORBIDDEN, name)
            continue
        cap_key = next((k for k in LIVE_CAPS if name.startswith(k)), None)
        outside, toggles = split_toggles(text)
        if name.startswith("# How to read this page"):
            if 'toggle="true"' not in name:
                fails.append("How to read this page must be a toggle heading ({toggle=\"true\"}), closed by default")
            if any(l.strip() and not l.startswith("\t") for l in text.split("\n")):
                fails.append("How to read this page: every child line must be tab-indented inside the toggle")
            fails += scan_patterns(text, HOWTO_FORBIDDEN, name)
        if name.startswith("# What changed"):
            n = words(outside)
            if n > LIVE_CAPS["# What changed"]:
                fails.append(f"What-changed text outside toggles {n} words > {LIVE_CAPS['# What changed']}")
            if len(toggles) > LIVE_LOG_DAYS + 3:
                fails.append(f"What-changed carries {len(toggles)} toggles; older entries belong in the Archive")
            for summ, tb in toggles:
                n = words(tb)
                cap = LIVE_INDEX_TOGGLE_CAP if summ.lstrip("*<b>").startswith("Corrections index") else LIVE_LOG_TOGGLE_CAP
                if n > cap:
                    fails.append(f"log toggle '{summ[:50]}' body {n} words > {cap}")
                fails += scan_patterns(summ + "\n" + tb, FORBIDDEN, "log toggle")
            fails += scan_patterns(outside, FORBIDDEN + PLAIN_FORBIDDEN, name)
            continue
        if name.startswith("# Crypto-exposed equities"):
            n = words(outside)
            if n > LIVE_CAPS["# Crypto-exposed equities"]:
                fails.append(f"equities text outside toggles {n} words > {LIVE_CAPS['# Crypto-exposed equities']}")
            for summ, tb in toggles:
                n = words(tb)
                if n > LIVE_EQ_TOGGLE_CAP:
                    fails.append(f"equities toggle '{summ[:50]}' body {n} words > {LIVE_EQ_TOGGLE_CAP}")
            fails += scan_patterns(outside, FORBIDDEN + PLAIN_FORBIDDEN, name)
            for summ, tb in toggles:
                fails += scan_patterns(summ + "\n" + tb, FORBIDDEN, "equities toggle")
            continue
        if name.startswith("# 📡 Signals"):
            # owner 2026-09-13 (§C27): the second reader's section — active signals in plain English outside toggles,
            # at most one closed "Earlier signals" toggle for older or resolved ones. Nobody else writes here.
            n = words(outside)
            if n > LIVE_CAPS["# 📡 Signals"]:
                fails.append(f"Signals text outside toggles {n} words > {LIVE_CAPS['# 📡 Signals']}")
            if len(toggles) > 1:
                fails.append(f"Signals carries {len(toggles)} toggles; one closed 'Earlier signals' toggle at most")
            for summ, tb in toggles:
                if words(tb) > LIVE_SIGNALS_TOGGLE_CAP:
                    fails.append(f"Signals toggle '{summ[:40]}' body {words(tb)} words > {LIVE_SIGNALS_TOGGLE_CAP}")
                fails += scan_patterns(summ + "\n" + tb, FORBIDDEN, "signals toggle")
            fails += scan_patterns(outside, FORBIDDEN + PLAIN_FORBIDDEN, name)
            continue
        if name.startswith("# Vetted"):
            # owner 2026-09-03: every tracked token that is not seated sits here as a CLOSED toggle — one summary line
            # giving the rejection in plain words, the detail inside. Nothing but toggles below the heading.
            n = words(outside)
            if n > LIVE_VETTED_OUTSIDE_CAP:
                fails.append(f"Vetted: {n} words outside toggles > {LIVE_VETTED_OUTSIDE_CAP} — each token is a closed toggle, one summary line")
            if not toggles:
                fails.append("Vetted: no toggles — each tracked token needs its own closed toggle")
            for summ, tb in toggles:
                if words(summ) > LIVE_VETTED_SUMMARY_CAP:
                    fails.append(f"Vetted toggle summary '{summ[:40]}' {words(summ)} words > {LIVE_VETTED_SUMMARY_CAP} — one line")
                if words(tb) > LIVE_VETTED_TOGGLE_CAP:
                    fails.append(f"Vetted toggle '{summ[:40]}' body {words(tb)} words > {LIVE_VETTED_TOGGLE_CAP}")
                fails += scan_patterns(summ + "\n" + tb, FORBIDDEN + PLAIN_FORBIDDEN, "vetted toggle")
            fails += scan_patterns(outside, FORBIDDEN + PLAIN_FORBIDDEN, name)
            continue
        if name.startswith("# Honesty box") and toggles:
            fails.append("Honesty box carries toggles — earlier states belong in the Archive")
        if name.startswith("# 🏆 Top 7"):
            cards = re.split(r"(?:\n|<br />)(?=(?:\*\*|<b>)\d · )", text)
            for c in cards[1:]:
                n = words(c)
                if n > LIVE_CARD_CAP:
                    fails.append(f"pick card '{c[:22]}' {n} words > {LIVE_CARD_CAP}")
        if cap_key:
            n = words(text)
            if n > LIVE_CAPS[cap_key]:
                fails.append(f"{name[:40]} {n} words > {LIVE_CAPS[cap_key]}")
        else:
            warns.append(f"section without a budget: {name[:60]}")
        plain = not name.startswith("# Engine cadence")   # owner 2026-09-02: the Honesty box is plain English too
        fails += scan_patterns(text, FORBIDDEN + (PLAIN_FORBIDDEN if plain else []), name)
    return fails, warns

# ----------------------------------------------------------------------------- dash
def js_strings(src, key):
    """All string values for a given JS key (key:"..." or key: "...")."""
    out = []
    for m in re.finditer(r'\b' + re.escape(key) + r'\s*:\s*"((?:[^"\\]|\\.)*)"', src):
        out.append(m.group(1))
    return out

def dash(repo):
    fails, warns = [], []
    d = os.path.join(repo, "data")
    html = json.load(open(os.path.join(d, "_html.json"), encoding="utf-8"))
    for k in DASH_RETIRED_SLOTS & set(html):
        fails.append(f"_html.json {k}: retired slot — the dashboard header carries no prose")
    for k, v in html.items():
        cap = next((c for p, c in DASH_CAPS.items() if k.startswith(p)), 40)
        n = words(v)
        if n > cap:
            fails.append(f"_html.json {k}: {n} words > {cap}")
        fails += scan_patterns(v, FORBIDDEN + DASH_EXTRA_FORBIDDEN, f"_html.json {k}")
    checks = [
        ("TOKENS.js",   [("note", "accrual.note"), ("unlock", "unlock"), ("name", None)]),
        ("NETFLOW.js",  [("tip", "tip"), ("net", "net"), ("inNone", "net"), ("outNone", "net")]),
        ("DILNEG.js",   [("txt", "txt"), ("tip", "tip")]),
        ("UNLOCKS.js",  [("tip", "tip"), ("what", "net"), ("rate", "net"), ("pct", "net"), ("priced", "net")]),
        ("NET_MODEL.js",[("calc", "calc"), ("basis", "net")]),
        ("LAST_KNOWN.js",[("asof", "asof")]),
    ]
    lk = open(os.path.join(d, "LAST_KNOWN.js"), encoding="utf-8").read()
    for s in js_strings(lk, "asof"):
        if not re.fullmatch(r"\d{4}-\d\d-\d\d(?: \d{1,2}:\d\d [AP]M PT)?", s):
            fails.append(f"LAST_KNOWN.js asof must be a date/time only, not a sourcing note — …{s[:60]}…")
    for s in js_strings(open(os.path.join(d, "TOKENS.js"), encoding="utf-8").read(), "name"):
        if re.search(r"\(|\d{1,2}/\d{1,2}", s):
            fails.append(f"TOKENS.js name carries a parenthetical or date — …{s}…")
    for fn, keys in checks:
        p = os.path.join(d, fn)
        if not os.path.exists(p):
            continue
        src = open(p, encoding="utf-8").read()
        for key, capkey in keys:
            for s in js_strings(src, key):
                if capkey:
                    cap = DASH_FIELD_CAPS[capkey]
                    n = words(s)
                    if n > cap:
                        fails.append(f"{fn} {key}: {n} words > {cap} — …{s[:70]}…")
                fails += scan_patterns(s, FORBIDDEN + DASH_EXTRA_FORBIDDEN, f"{fn} {key}")
                if fn == "TOKENS.js" and key in ("note", "unlock"):
                    fails += scan_patterns(s, TILE_PROSE_FORBIDDEN, f"{fn} {key}")
    # UNLOCKS.zeros and EST_GROSS are arrays / object literals of strings
    for fn, capkey in (("UNLOCKS.js", "zeros"), ("EST_GROSS.js", "EST_GROSS")):
        p = os.path.join(d, fn)
        if os.path.exists(p):
            src = open(p, encoding="utf-8").read()
            seg = src.split("zeros:")[1] if fn == "UNLOCKS.js" and "zeros:" in src else src
            for m in re.finditer(r'"((?:[^"\\]|\\.)*)"', seg):
                s = m.group(1)
                if len(s) < 25:
                    continue
                n = words(s)
                if n > DASH_FIELD_CAPS[capkey]:
                    fails.append(f"{fn}: {n} words > {DASH_FIELD_CAPS[capkey]} — …{s[:70]}…")
                fails += scan_patterns(s, FORBIDDEN + DASH_EXTRA_FORBIDDEN, fn)
    for fn, cap in DASH_NOTE_CAPS.items():
        p = os.path.join(d, fn + ".js")
        if os.path.exists(p):
            s = json.loads(open(p, encoding="utf-8").read())
            n = words(s)
            if n > cap:
                fails.append(f"{fn}.js: {n} words > {cap}")
            fails += scan_patterns(s, FORBIDDEN + DASH_EXTRA_FORBIDDEN, fn)
    cp = os.path.join(d, "_comments.json")
    if os.path.exists(cp):
        for k, v in json.load(open(cp, encoding="utf-8")).items():
            n = words(v)
            if n > DASH_FIELD_CAPS["comment"]:
                fails.append(f"_comments.json {k}: {n} words > {DASH_FIELD_CAPS['comment']}")
    # rendered strings hard-coded in the shell must not carry data claims or engine text
    shell = open(os.path.join(repo, "shell.html"), encoding="utf-8").read()
    for pat, why in ((r"ENGINE:", "engine instruction in shell"), (r"\(8 seats\)|\b8 seats\b", "stale seat count in shell"),
                     (r"re-entry event ~Aug", "stale dated claim in shell"),
                     (r"(?i)accountab", "accountability in shell"), (r'class="sub"', "header prose block in shell"),
                     (r"embedded view shows|self-refresh", "snapshot banner prose in shell"),
                     (r"claude/|state\.json|validate_prints", "internal path in shell")):
        if re.search(pat, shell):
            fails.append(f"shell.html: {why}")
    return fails, warns

# ----------------------------------------------------------------------------- state
def state(path):
    fails, warns = [], []
    raw = open(path, "rb").read()
    try:
        s = json.loads(raw)
    except Exception as e:
        return [f"state.json does not parse: {e}"], []
    if len(raw) > STATE_MAX_BYTES:
        fails.append(f"state.json is {len(raw):,} bytes; cap {STATE_MAX_BYTES:,}")
    dated_key = re.compile(r"(?:_|^)(?:20\d\d[-_]?\d\d[-_]?\d\d|\d{4})$|_20\d\d_\d\d")
    def walk(o, top, path):
        if isinstance(o, dict):
            for k, v in o.items():
                if dated_key.search(k) and top not in ("law_fingerprint",):
                    fails.append(f"dated key {path}.{k} — replace, never accumulate")
                walk(v, top, f"{path}.{k}")
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, top, f"{path}[{i}]")
        elif isinstance(o, str):
            cap = STATE_CAPS.get(top, STATE_CAPS["_default"])
            n = words(o)
            if n > cap:
                fails.append(f"{path}: {n} words > {cap}")
            if "**" in o:
                fails.append(f"{path}: markdown bold in a state field")
            for sh in shouting(o):
                fails.append(f"{path}: shouting — {sh[:60]}")
    for k, v in s.items():
        walk(v, k, k)
    ro = s.get("run_orders")
    if not isinstance(ro, dict) or any(isinstance(v, list) for v in ro.values()):
        fails.append("run_orders carries duty lists; since 2026-09-24 they live in claude/run_orders.json and state holds the pointer")
    return fails, warns

# ----------------------------------------------------------------------------- orders
def orders(path):
    fails, warns = [], []
    raw = open(path, "rb").read()
    try:
        o = json.loads(raw)
    except Exception as e:
        return [f"run_orders.json does not parse: {e}"], []
    if len(raw) > ORDERS_MAX_BYTES:
        fails.append(f"run_orders.json is {len(raw):,} bytes; cap {ORDERS_MAX_BYTES:,} — close a duty, never raise the cap")
    dated_key = re.compile(r"(?:_|^)(?:20\d\d[-_]?\d\d[-_]?\d\d|\d{4})$|_20\d\d_\d\d")
    slots = [k for k, v in o.items() if isinstance(v, list)]
    if not slots:
        fails.append("run_orders.json carries no duty list")
    for k, v in o.items():
        if dated_key.search(k):
            fails.append(f"dated key {k} — replace, never accumulate")
        if isinstance(v, list):
            for i, x in enumerate(v):
                if not isinstance(x, str):
                    fails.append(f"{k}[{i}]: not a string"); continue
                n = words(x)
                if n > ORDERS_DUTY_CAP:
                    fails.append(f"{k}[{i}] ({x[:24]!r}): {n} words > {ORDERS_DUTY_CAP}")
                if "**" in x:
                    fails.append(f"{k}[{i}]: markdown bold in a duty")
                for sh in shouting(x):
                    fails.append(f"{k}[{i}]: shouting — {sh[:60]}")
        elif isinstance(v, str):
            cap = 160 if k == "_note" else 90
            if words(v) > cap:
                fails.append(f"{k}: {words(v)} words > {cap}")
    return fails, warns

# ----------------------------------------------------------------------------- main
def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("live", "dash", "state", "orders"):
        print(__doc__); sys.exit(2)
    mode, target = sys.argv[1], sys.argv[2]
    fails, warns = {"live": live, "dash": dash, "state": state, "orders": orders}[mode](target)
    for w in warns: print("WARN ", w)
    for f in fails: print("FAIL ", f)
    print(f"\nscope_gate {mode}: {len(fails)} FAIL · {len(warns)} WARN")
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
