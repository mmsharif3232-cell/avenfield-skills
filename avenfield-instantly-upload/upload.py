#!/usr/bin/env python3
"""Avenfield instantly-upload — push a Google Sheet of leads into an Instantly campaign.

The sheet → Instantly workflow: read a tab, map its columns to Instantly lead
fields (first/last/company/website) + campaign merge variables (custom vars like
serviceLine), de-dupe + drop bad emails, fill blank merge vars so no {{tag}}
renders empty, then push — TEST first, bulk only on --run. NEVER launches a
campaign (it only adds leads).

Reuses the sibling skills:
  • avenfield-instantly/instantly.py — Instantly v2 transport (call + idempotent add)
  • avenfield-sheets/sheets.py        — Sheets read

USAGE
  U=~/.claude/skills/avenfield-instantly-upload/upload.py

  # DRY RUN — build + validate + show a sample + counts, push nothing
  python3 $U --sheet "<ID>" --tab "Goodfirms-verified" --campaign-name "ppr-002" \
      --email-col D --first-col A --last-col B --company-col G --website-col H \
      --var serviceLine=J --var-default serviceLine=marketing --dry-run

  # TEST — push the first 10, read a few back, then stop
  python3 $U ... --test 10

  # FULL upload (idempotent) — push everyone; campaign stays in DRAFT
  python3 $U ... --run --concurrency 8

Column specs accept a LETTER (e.g. D) or a HEADER NAME (e.g. "Email"). Use
--map-by-header to auto-detect the common Avenfield columns, then override any.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_INST = _HERE.parent / "avenfield-instantly"
if not (_INST / "instantly.py").exists():
    _INST = Path.home() / ".claude" / "skills" / "avenfield-instantly"
_SH = _HERE.parent / "avenfield-sheets"
if not (_SH / "sheets.py").exists():
    _SH = Path.home() / ".claude" / "skills" / "avenfield-sheets"
sys.path.insert(0, str(_INST))
sys.path.insert(0, str(_SH))
import instantly  # noqa: E402
import sheets      # noqa: E402

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HEADER_ALIASES = {
    "email": ["email", "email address", "e-mail"],
    "first": ["first name", "first_name", "firstname", "first"],
    "last": ["last name", "last_name", "lastname", "last"],
    "company": ["company", "company name", "company_name", "organization"],
    "website": ["website", "url", "domain", "site"],
}


def col_to_idx(col):
    idx = 0
    for ch in col.strip().upper():
        idx = idx * 26 + (ord(ch) - 64)
    return idx


def resolve_col(spec, headers):
    """A column LETTER (D) or a HEADER NAME (Email) → 0-based index, or None."""
    if spec is None:
        return None
    s = str(spec).strip()
    if re.fullmatch(r"[A-Za-z]{1,2}", s):
        return col_to_idx(s) - 1
    low = [h.strip().lower() for h in headers]
    if s.lower() in low:
        return low.index(s.lower())
    sys.exit(f"Column {spec!r} not found (not a letter, not a header in {headers}).")


def auto_header(headers, aliases):
    low = [h.strip().lower() for h in headers]
    for a in aliases:
        if a in low:
            return low.index(a)
    return None


def cell(row, idx):
    return (row[idx].strip() if idx is not None and idx < len(row) and row[idx] else "")


def resolve_campaign(args):
    if args.campaign:
        return args.campaign
    status, data = instantly.call("GET", "/campaigns", query="limit=100")
    items = data.get("items", data if isinstance(data, list) else [])
    matches = [c for c in items if args.campaign_name.lower() in (c.get("name") or "").lower()]
    if not matches:
        sys.exit(f"No campaign matching {args.campaign_name!r}. Run `instantly.py campaigns`.")
    if len(matches) > 1:
        names = [f"{c.get('id')}  {c.get('name')}" for c in matches]
        sys.exit("Multiple campaigns match — pass --campaign <ID>:\n  " + "\n  ".join(names))
    return matches[0]["id"]


def main():
    ap = argparse.ArgumentParser(description="Upload a sheet of leads into an Instantly campaign.")
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--tab", required=True)
    ap.add_argument("--campaign", help="Campaign ID.")
    ap.add_argument("--campaign-name", help="Resolve campaign by (partial) name instead of ID.")
    ap.add_argument("--start-row", type=int, default=2)
    ap.add_argument("--map-by-header", action="store_true",
                    help="Auto-detect email/first/last/company/website columns by header name.")
    ap.add_argument("--email-col"); ap.add_argument("--first-col"); ap.add_argument("--last-col")
    ap.add_argument("--company-col"); ap.add_argument("--website-col")
    ap.add_argument("--var", action="append", default=[],
                    help='Custom variable: name=COL (letter or header). Repeatable. e.g. serviceLine=J')
    ap.add_argument("--var-default", action="append", default=[],
                    help="Fallback for a blank custom var: name=value. Repeatable.")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--test", type=int, default=10, help="Rows to push in TEST mode (default 10).")
    ap.add_argument("--run", action="store_true", help="Push the WHOLE sheet (not just --test).")
    ap.add_argument("--dry-run", action="store_true", help="Build + validate + sample; push nothing.")
    ap.add_argument("--allow-dupes", action="store_true")
    args = ap.parse_args()

    if not (args.campaign or args.campaign_name):
        sys.exit("Pass --campaign <ID> or --campaign-name <text>.")

    sid = sheets._sheet_id(args.sheet)
    grid = sheets._api("GET", f"{sheets.SHEETS}/{sid}/values/"
                       f"{urllib.parse.quote(args.tab)}").get("values", [])
    if len(grid) < args.start_row:
        sys.exit("Sheet has no data rows for the given --start-row.")
    headers = grid[0]
    data = grid[args.start_row - 1:]

    # resolve field columns
    idx = {}
    if args.map_by_header:
        for k, al in HEADER_ALIASES.items():
            idx[k] = auto_header(headers, al)
    for k, spec in (("email", args.email_col), ("first", args.first_col),
                    ("last", args.last_col), ("company", args.company_col),
                    ("website", args.website_col)):
        if spec is not None:
            idx[k] = resolve_col(spec, headers)
    if idx.get("email") is None:
        sys.exit("No email column — set --email-col or --map-by-header.")

    # resolve custom-variable columns + defaults
    var_idx = {}
    for spec in args.var:
        if "=" not in spec:
            sys.exit(f"--var must be name=COL, got {spec!r}")
        name, col = spec.split("=", 1)
        var_idx[name.strip()] = resolve_col(col.strip(), headers)
    var_def = {}
    for spec in args.var_default:
        name, val = spec.split("=", 1)
        var_def[name.strip()] = val

    # build leads
    leads, seen = [], set()
    blank = bad = dupe = 0
    filled = {n: 0 for n in var_idx}
    for row in data:
        email = cell(row, idx["email"])
        if not email:
            blank += 1; continue
        if not EMAIL_RE.match(email):
            bad += 1; continue
        if email.lower() in seen:
            dupe += 1; continue
        seen.add(email.lower())
        lead = {"email": email}
        for k, fld in (("first", "first_name"), ("last", "last_name"),
                       ("company", "company_name"), ("website", "website")):
            if idx.get(k) is not None:
                lead[fld] = cell(row, idx[k])
        cv = {}
        for name, ci in var_idx.items():
            v = cell(row, ci)
            if not v and name in var_def:
                v = var_def[name]; filled[name] += 1
            cv[name] = v
        if cv:
            lead["custom_variables"] = cv
        leads.append(lead)

    print(json.dumps({"tab": args.tab, "valid_unique_leads": len(leads),
                      "blank_email": blank, "malformed": bad, "dupe_email": dupe,
                      "vars": list(var_idx), "var_defaults_filled": filled},
                     ensure_ascii=False, indent=2))
    if not leads:
        sys.exit("No valid leads to push.")

    if args.dry_run:
        print("\nDRY RUN — sample:")
        for l in leads[:5]:
            print("  " + json.dumps(l, ensure_ascii=False))
        print("\nNothing pushed. Re-run with --test N or --run.")
        return

    campaign = resolve_campaign(args)
    n = len(leads) if args.run else min(args.test, len(leads))
    todo = leads[:n]
    print(f"\n{'RUN (full)' if args.run else f'TEST (first {n})'} → campaign {campaign} · {n} leads")

    from concurrent.futures import ThreadPoolExecutor, as_completed
    ok = fail = 0
    errs = []
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as ex:
        futs = [ex.submit(instantly._add_one, campaign, l, args.allow_dupes) for l in todo]
        for i, f in enumerate(as_completed(futs), 1):
            good, status, d = f.result()
            ok += good
            if not good:
                fail += 1
                if len(errs) < 8:
                    errs.append({"status": status, "error": str(d)[:160]})
            if i % 250 == 0 or i == n:
                print(f"  {i}/{n} · ok={ok} fail={fail}", file=sys.stderr)

    summary = {"campaign": campaign, "pushed": n, "ok": ok, "failed": fail, "errors": errs,
               "launched": False}
    if not args.run:
        # read a couple back so you can confirm the merge vars stored
        st, d = instantly.call("POST", "/leads/list", body={"campaign": campaign, "limit": 3})
        summary["readback"] = [{"email": it.get("email"),
                                "first": it.get("first_name"),
                                "payload_vars": list((it.get("payload") or {}).keys())}
                               for it in d.get("items", [])]
        summary["next"] = "eyeball the readback, then re-run with --run for the full list"
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
