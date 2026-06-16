#!/usr/bin/env python3
"""Avenfield qualify — classify leads against an ICP, then extract the winners.

Two jobs, one skill:

  classify  — score every scraped company against an ICP (Ideal Customer
              Profile) by reading its website markdown. This is GPT
              classification and is delegated to avenfield-personalize with a
              preset (presets/<icp>.json), so all of personalize's machinery —
              test-first, cost estimate, concurrency, auto-retry on rate limits,
              live status — comes for free. `classify` just prints the exact
              command to run (or runs it with --go).

  extract   — the genuinely new capability: given a results tab that already
              holds the qualification flag (e.g. is_ma=true) and a SOURCE tab of
              raw leads (one row per contact), build a NEW tab/sheet containing
              ONLY the lead rows whose website qualified — carrying the
              qualification columns across, matched by normalised URL. This is
              how you go from "753 unique sites scored" back to "the N lead rows
              that belong to the winners".

USAGE
  Q=~/.claude/skills/avenfield-qualify/qualify.py

  # 1. classify (prints the personalize command; add --go to run it)
  python3 $Q classify --sheet <ID> --tab leads --content-col F --key-col A \
        --icp ma_qualify --out-col G --test 15
  python3 $Q classify ... --run --go        # full run

  # 2. extract qualified leads into a new tab
  python3 $Q extract --sheet <ID> \
        --source-tab ma_advisers_us_instantly --source-url-col website \
        --qual-tab leads --qual-url-col url \
        --flag-col is_ma --flag-value true \
        --carry-cols ma_type,ma_confidence,ma_reason \
        --dest-tab qualified_leads \
        [--min-confidence high] [--conf-col ma_confidence] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHEETS = _HERE.parent / "avenfield-sheets"
if not (_SHEETS / "sheets.py").exists():
    _SHEETS = Path.home() / ".claude" / "skills" / "avenfield-sheets"
sys.path.insert(0, str(_SHEETS))
import sheets as sh  # noqa: E402

CONF_RANK = {"high": 3, "medium": 2, "low": 1, "": 0}


def norm_url(u: str) -> str:
    """Normalise a URL/domain for matching: drop scheme, www., trailing slash, case."""
    u = (u or "").strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.rstrip("/")


def col_to_idx(letter: str) -> int:
    """'A'->0, 'B'->1 … (column letter to 0-based index)."""
    n = 0
    for ch in letter.strip().upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def resolve_col(spec: str, headers: list[str]) -> int:
    """Accept a column LETTER ('C') or a header NAME ('website') -> 0-based index."""
    spec = (spec or "").strip()
    if re.fullmatch(r"[A-Za-z]+", spec) and spec.lower() not in {h.lower() for h in headers}:
        return col_to_idx(spec)
    low = [h.strip().lower() for h in headers]
    if spec.lower() in low:
        return low.index(spec.lower())
    raise SystemExit(f"Column {spec!r} not found. Headers: {headers}")


def read_tab(sheet_id: str, tab: str) -> list[list[str]]:
    raw = sh._api("GET", f"{sh.SHEETS}/{sheet_id}/values/{tab}!A1:ZZ", None)
    return raw.get("values", [])


# ── classify: delegate to avenfield-personalize ──────────────────────────────
def cmd_classify(args):
    personalize = _HERE.parent / "avenfield-personalize" / "personalize.py"
    if not personalize.exists():
        personalize = Path.home() / ".claude" / "skills" / "avenfield-personalize" / "personalize.py"
    # Prefer the preset bundled with THIS skill; fall back to personalize's copy.
    preset_here = _HERE / "presets" / f"{args.icp}.json"
    cmd = ["python3", str(personalize),
           "--sheet", args.sheet, "--tab", args.tab,
           "--content-col", args.content_col, "--key-col", args.key_col,
           "--out-col", args.out_col, "--concurrency", str(args.concurrency)]
    if preset_here.exists():
        p = json.loads(preset_here.read_text())
        # pass the bundled preset's prompt + vars explicitly so personalize need
        # not have its own copy
        import tempfile
        pf = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
        pf.write(p["prompt"]); pf.close()
        cmd += ["--prompt-file", pf.name, "--vars", json.dumps(p["vars"]),
                "--model", p.get("model", "gpt-4o-mini")]
        if p.get("max_chars"):
            cmd += ["--max-chars", str(p["max_chars"])]
    else:
        cmd += ["--preset", args.icp]
    if args.run:
        cmd += ["--run"]
    else:
        cmd += ["--test", str(args.test)]
    if args.estimate:
        cmd += ["--estimate"]

    printable = " ".join(re.sub(r"(\s)", r"\1", c) if " " not in c else f'{c!r}' for c in cmd)
    if args.go:
        import subprocess
        sys.exit(subprocess.call(cmd))
    print("# classify delegates to avenfield-personalize. Run:")
    print(printable)
    print("\n# (add --go to run it directly through this skill)")


# ── extract: build a qualified-leads tab from a results tab ───────────────────
def cmd_extract(args):
    # 1. qualified URL set from the results tab
    qrows = read_tab(args.sheet, args.qual_tab)
    if not qrows:
        raise SystemExit(f"Results tab {args.qual_tab!r} is empty.")
    qhdr = qrows[0]
    qurl_i = resolve_col(args.qual_url_col, qhdr)
    flag_i = resolve_col(args.flag_col, qhdr)
    conf_i = resolve_col(args.conf_col, qhdr) if args.min_confidence else None
    carry = [c.strip() for c in args.carry_cols.split(",")] if args.carry_cols else []
    carry_i = {c: resolve_col(c, qhdr) for c in carry}

    flag_val = args.flag_value.strip().lower()
    min_rank = CONF_RANK.get((args.min_confidence or "").lower(), 0)

    qual = {}  # norm_url -> {carry col: value}
    for r in qrows[1:]:
        def g(i): return (r[i] if i is not None and len(r) > i else "").strip()
        if g(flag_i).lower() != flag_val:
            continue
        if conf_i is not None and CONF_RANK.get(g(conf_i).lower(), 0) < min_rank:
            continue
        key = norm_url(g(qurl_i))
        if key:
            qual[key] = {c: g(i) for c, i in carry_i.items()}

    # 2. walk the source tab, keep rows whose website qualified
    srows = read_tab(args.sheet, args.source_tab)
    if not srows:
        raise SystemExit(f"Source tab {args.source_tab!r} is empty.")
    shdr = srows[0]
    surl_i = resolve_col(args.source_url_col, shdr)

    out_hdr = list(shdr) + carry
    out = [out_hdr]
    matched_sites = set()
    for r in srows[1:]:
        url = r[surl_i] if len(r) > surl_i else ""
        key = norm_url(url)
        if key in qual:
            matched_sites.add(key)
            row = list(r) + [""] * (len(shdr) - len(r))
            row += [qual[key].get(c, "") for c in carry]
            out.append(row)

    summary = {
        "qualified_unique_sites": len(qual),
        "sites_with_lead_rows": len(matched_sites),
        "qualified_lead_rows": len(out) - 1,
        "dest_tab": args.dest_tab,
    }

    if args.dry_run:
        summary["mode"] = "dry-run (nothing written)"
        summary["sample"] = out[1:4]
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return

    # 3. write to dest tab (create if missing, else clear first)
    tabs = sh._api("GET", f"{sh.SHEETS}/{args.sheet}", None).get("sheets", [])
    titles = {t["properties"]["title"] for t in tabs}
    if args.dest_tab not in titles:
        sh._api("POST", f"{sh.SHEETS}/{args.sheet}:batchUpdate",
                {"requests": [{"addSheet": {"properties": {"title": args.dest_tab}}}]})
    else:
        sh._api("POST", f"{sh.SHEETS}/{args.sheet}/values/{args.dest_tab}!A1:ZZ:clear", {})

    CHUNK = 500
    for i in range(0, len(out), CHUNK):
        chunk = out[i:i + CHUNK]
        sh._api("POST", f"{sh.SHEETS}/{args.sheet}/values:batchUpdate",
                {"valueInputOption": "RAW",
                 "data": [{"range": f"{args.dest_tab}!A{i+1}", "values": chunk}]})

    summary["mode"] = "written"
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="Qualify leads against an ICP, then extract the winners.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("classify", help="score leads (delegates to avenfield-personalize)")
    c.add_argument("--sheet", required=True)
    c.add_argument("--tab", default="leads")
    c.add_argument("--content-col", required=True)
    c.add_argument("--key-col", required=True)
    c.add_argument("--out-col", required=True)
    c.add_argument("--icp", default="ma_qualify", help="preset name in presets/<icp>.json")
    c.add_argument("--concurrency", type=int, default=10)
    c.add_argument("--test", type=int, default=15)
    c.add_argument("--run", action="store_true")
    c.add_argument("--estimate", action="store_true")
    c.add_argument("--go", action="store_true", help="actually run the personalize command")
    c.set_defaults(func=cmd_classify)

    e = sub.add_parser("extract", help="build a qualified-leads tab from a results tab")
    e.add_argument("--sheet", required=True)
    e.add_argument("--source-tab", required=True, help="raw leads, one row per contact")
    e.add_argument("--source-url-col", required=True, help="website column (letter or header)")
    e.add_argument("--qual-tab", required=True, help="tab holding the qualification flag")
    e.add_argument("--qual-url-col", required=True)
    e.add_argument("--flag-col", default="is_ma")
    e.add_argument("--flag-value", default="true")
    e.add_argument("--conf-col", default="ma_confidence")
    e.add_argument("--min-confidence", help="drop below this: high|medium|low")
    e.add_argument("--carry-cols", default="", help="comma-sep result cols to copy across")
    e.add_argument("--dest-tab", required=True)
    e.add_argument("--dry-run", action="store_true")
    e.set_defaults(func=cmd_extract)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
