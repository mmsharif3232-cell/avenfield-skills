#!/usr/bin/env python3
"""Avenfield clean-emails — deterministically clean a scraped email column.

Emails scraped off the web (Google-Maps / site crawls) arrive filthy:
URL-encoded leading spaces (%20), zero-width unicode prefixes, leading
underscores/dashes, markdown hyperlinks glued onto the address, encoded label
text ("email us at ..."), phone numbers concatenated in front, doubled-TLD
garbage (.cominfo, .commonday), template placeholders (_email@yourwebsite.com,
+1@model.phone.replace), SMS gateways (digits@tmomail.net) and supplier-chain
addresses. None of that should ever reach a verifier or Instantly.

This skill is PURE PYTHON — no GPT, no API guessing. It URL-decodes, strips the
junk, extracts the first real-looking address, validates the TLD, and blocks
known placeholder / supplier / gateway domains. Every cell gets a status so you
can see exactly what happened (cleaned / unchanged / placeholder / supplier /
invalid / empty). Nothing is fabricated: if a cell can't yield a real address
the email is blanked and flagged — better an empty cell than a wrong send.

USAGE
  E=~/.claude/skills/avenfield-clean-emails/clean_emails.py

  # Dry-run: read the column, print the status breakdown + 20 samples, write nothing
  python3 $E --sheet <URL|ID> --tab "Test to find more Emails" \
      --email-col K --status-col L --dry-run

  # Full run: clean col K in place, write the status into col L
  python3 $E --sheet <URL|ID> --tab "Test to find more Emails" \
      --email-col K --status-col L

  # Self-test the cleaner on the built-in dirty sample (no sheet needed)
  python3 $E --self-test

Notes
  • --email-col / --status-col accept a column LETTER (K) or a header NAME (email).
  • --status-col is optional; omit it to only rewrite the email column.
  • Idempotent: a cell already holding its cleaned value comes back 'unchanged'.
  • Writes are chunked (--chunk, default 500) to stay under Sheets API limits.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHEETS = _HERE.parent / "avenfield-sheets"
if not (_SHEETS / "sheets.py").exists():
    _SHEETS = Path.home() / ".claude" / "skills" / "avenfield-sheets"
sys.path.insert(0, str(_SHEETS))
import sheets as sh  # noqa: E402

# ── cleaning rules ────────────────────────────────────────────────────────────

# Zero-width / bidi characters that get scraped in front of an address.
ZERO_WIDTH = ["​", "‌", "‍", "﻿", "‎", "‏", "⁠"]

# A liberal email matcher — we validate the TLD separately afterwards.
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# A phone number glued in front of a local-part: (305) 826-2645info@...
PHONE_PREFIX_RE = re.compile(r"^[\(]?\d{3}[\)]?[\s.\-]*\d{3}[\s.\-]*\d{4}\s*")

# Markdown hyperlink:  [text](url)  — the address (if any) lives in the text.
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\((?:[^)]*)\)")

# Known good TLDs. Anything else is treated as junk — but com/net/org are also
# truncated out of doubled-TLD garbage (.cominfo -> .com, .commonday -> .com).
KNOWN_TLDS = {
    # ccTLDs / common
    "com", "net", "org", "co", "us", "ca", "uk", "io", "biz", "info", "us",
    "edu", "gov", "tv", "me", "ai", "app", "us", "online", "site", "pro",
    # multi-char gTLDs that START with com/net/org (must stay valid, not be
    # truncated): without these, foo.company would wrongly become foo.com.
    "company", "computer", "community", "network", "construction", "contractors",
    "services", "solutions", "email", "center", "plumbing", "build", "homes",
    "house", "repair", "energy", "tech", "cool", "us",
}
# Multi-label TLDs (e.g. .co.uk) — handled by suffix check.
MULTI_TLDS = {"co.uk", "com.au", "co.nz", "co.za", "com.br"}

# Generic / template placeholder domains — never a real business inbox.
PLACEHOLDER_DOMAINS = {
    "yourwebsite.com", "yourcompany.com", "yourdomain.com", "mysite.com",
    "example.com", "example.org", "example.net", "domain.com", "mail.com",
    "email.com", "mailservice.com", "model.phone.replace", "latofonts.com",
    "wixpress.com", "sentry.io", "sentry.wixpress.com", "test.com",
    "hardwarestore.com",
}

# SMS-to-email gateways — a phone number, not an inbox.
GATEWAY_DOMAINS = {
    "tmomail.net", "vtext.com", "txt.att.net", "messaging.sprintpcs.com",
    "vzwpix.com", "mms.att.net", "pm.sprint.com", "msg.fi.google.com",
}

# Supplier / manufacturer / distributor chains — not a prospect, a vendor.
SUPPLIER_DOMAINS = {
    "sidharvey.com", "uri.com", "ferguson.com", "galarson.com",
    "ampcorporate.com", "waxman.com", "daikincomfort.com", "carrier.com",
    "lennoxpros.com", "grainger.com", "supplyhouse.com", "johnstonesupply.com",
    "basf.com",
}


def _split_domain(domain: str) -> tuple[str, str]:
    """Return (label_before_tld_ignored, tld). Just the last label as the TLD."""
    parts = domain.split(".")
    return ".".join(parts[:-1]), parts[-1]


def _validate_and_fix_tld(domain: str) -> str | None:
    """Return a domain with a valid TLD, recovering common doubled-TLD junk.

    'flahvac.com'        -> 'flahvac.com'
    'flahvac.cominfo'    -> 'flahvac.com'   (com + trailing 'info')
    'yahoo.commonday'    -> 'yahoo.com'     (com + trailing 'monday')
    'foo.company'        -> 'foo.company'   (real TLD, left intact)
    'foo.bogusxyz'       -> None            (unrecoverable junk)
    """
    domain = domain.lower().strip(".")
    if not domain or "." not in domain:
        return None
    # multi-label TLD (.co.uk etc.)
    for suf in MULTI_TLDS:
        if domain.endswith("." + suf):
            return domain
    head, tld = _split_domain(domain)
    if not head:
        return None
    if tld in KNOWN_TLDS:
        return domain
    # Not a known TLD — try to recover a doubled-TLD glued on by the scraper.
    for base in ("com", "net", "org"):
        if tld.startswith(base) and len(tld) > len(base):
            return f"{head}.{base}"
    return None


def clean_email(raw: str) -> tuple[str, str]:
    """Clean one raw cell value. Returns (cleaned_email, status).

    status: empty | unchanged | cleaned | placeholder | supplier | invalid
    """
    if raw is None:
        return "", "empty"
    original = raw
    s = raw.strip()
    if not s:
        return "", "empty"

    # 1. URL-decode (handles %20, %28, %22, %e2%80%8d, double-encoding).
    for _ in range(2):  # twice catches %2520-style double encoding
        d = urllib.parse.unquote(s)
        if d == s:
            break
        s = d

    # 2. Strip zero-width / bidi chars anywhere in the string.
    for z in ZERO_WIDTH:
        s = s.replace(z, "")

    # 3. If a markdown link is present, the real address is in the link TEXT;
    #    the (url) part is a website, not an email. Drop the (url), keep text.
    if "](" in s:
        s = MD_LINK_RE.sub(r"\1", s)

    s = s.strip()

    # 4. Strip a phone number glued to the front of the local-part.
    s = PHONE_PREFIX_RE.sub("", s)

    # 5. Strip leading junk (underscores, dashes, quotes, plus, dots, spaces)
    #    so a clean address can be matched. Done by the regex search anyway,
    #    but this also removes label noise like '"email us at '.
    #    (We rely on EMAIL_RE.search to find the first plausible address.)
    m = EMAIL_RE.search(s)
    if not m:
        return "", "invalid"
    cand = m.group(0).lower().rstrip(".")

    local, _, domain = cand.partition("@")
    # Strip leading junk the regex swept into the local-part (_, -, ., +).
    local = local.lstrip("_-.+")
    # Strip a leading 'www.' wrongly captured into the domain (markdown links).
    domain = re.sub(r"^www\.", "", domain)
    if not local or not domain:
        return "", "invalid"

    # 6. Block known placeholder / gateway / supplier domains (exact match,
    #    BEFORE TLD repair — these may have non-standard TLDs like .replace).
    if domain in PLACEHOLDER_DOMAINS:
        return "", "placeholder"
    if domain in GATEWAY_DOMAINS:
        return "", "invalid"
    if domain in SUPPLIER_DOMAINS:
        return "", "supplier"

    # 7. Validate / repair the TLD.
    fixed_domain = _validate_and_fix_tld(domain)
    if fixed_domain is None:
        return "", "invalid"
    domain = fixed_domain
    # Re-check the repaired domain against the block-lists (e.g. .cominfo junk
    # could in principle repair into a blocked domain).
    if domain in PLACEHOLDER_DOMAINS:
        return "", "placeholder"
    if domain in SUPPLIER_DOMAINS:
        return "", "supplier"

    # 8. Local-part sanity: must have ≥1 letter and be ≥1 char after junk-strip.
    #    Catches all-numeric inboxes (phone fragments) and empty/single garbage.
    #    A short local-part (e.g. 'hr', 'pr') is KEPT — avenfield-verify is the
    #    deliverability gate; we don't fabricate typo-fixes here.
    if len(local) < 1 or not re.search(r"[a-z]", local):
        return "", "invalid"

    cleaned = f"{local}@{domain}"

    # 9. Status: unchanged if the original (trimmed, lowercased) already equalled
    #    the cleaned value; otherwise we cleaned it.
    if original.strip().lower() == cleaned:
        return cleaned, "unchanged"
    return cleaned, "cleaned"


# ── column helpers (letter or header name) ───────────────────────────────────
def col_to_idx(letter: str) -> int:
    n = 0
    for ch in letter.strip().upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def idx_to_col(idx: int) -> str:
    s = ""
    idx += 1
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def resolve_col(spec: str, headers: list[str]) -> int:
    spec = (spec or "").strip()
    low = [h.strip().lower() for h in headers]
    if re.fullmatch(r"[A-Za-z]+", spec) and spec.lower() not in low:
        return col_to_idx(spec)
    if spec.lower() in low:
        return low.index(spec.lower())
    raise SystemExit(f"Column {spec!r} not found. Headers: {headers}")


def _range(tab: str, cells: str) -> str:
    """Range for a URL path segment (tab name URL-encoded)."""
    return urllib.parse.quote(tab, safe="") + "!" + cells


def _range_body(tab: str, cells: str) -> str:
    """Range for a JSON request body (tab name single-quoted if it has spaces/&)."""
    if any(c in tab for c in (" ", "&", "'", "!")):
        tab = "'" + tab.replace("'", "''") + "'"
    return tab + "!" + cells


def read_tab(sheet_id: str, tab: str) -> list[list[str]]:
    raw = sh._api("GET", f"{sh.SHEETS}/{sheet_id}/values/{_range(tab, 'A1:ZZ')}", None)
    return raw.get("values", [])


# ── commands ──────────────────────────────────────────────────────────────────
SELF_TEST_SAMPLE = [
    ("%20info@flahvac.com", "info@flahvac.com", "cleaned"),
    ("%28305%29%20826-2645info@flahvac.cominfo", "info@flahvac.com", "cleaned"),
    ("%e2%80%8dspringfield@truckserviceco.com", "springfield@truckserviceco.com", "cleaned"),
    ("%e2%80%8bhello@rysenservices.com", "hello@rysenservices.com", "cleaned"),
    ("%20service@[www.fitops.com](https://www.fitops.com)", "service@fitops.com", "cleaned"),
    ("%20%22email%20us%20at%20info@choicehomewarranty.com", "info@choicehomewarranty.com", "cleaned"),
    ("%20%20info@jbcoteconstruction.com", "info@jbcoteconstruction.com", "cleaned"),
    ("-agreenfield@dvachvac.com", "agreenfield@dvachvac.com", "cleaned"),
    ("---percyfranco403@gmail.com", "percyfranco403@gmail.com", "cleaned"),
    ("_zhollis@icloud.com", "zhollis@icloud.com", "cleaned"),
    ("_email@yourwebsite.com", "", "placeholder"),
    ("_company@mail.com", "", "placeholder"),
    ("+1@model.phone.replace", "", "placeholder"),
    ("17175724870@tmomail.net", "", "invalid"),
    ("_concepts@yahoo.commonday", "concepts@yahoo.com", "cleaned"),
    ("%20nfo@ahservicepros.com", "nfo@ahservicepros.com", "cleaned"),
    ("191@hardwarestore.com", "", "placeholder"),
    ("_2063@basf.com", "", "supplier"),
    ("1bayerair@gmail.com", "1bayerair@gmail.com", "unchanged"),
    ("info@goodhopehvac.com", "info@goodhopehvac.com", "unchanged"),
    ("", "", "empty"),
]


def cmd_self_test(args):
    fails = 0
    for raw, exp_email, exp_status in SELF_TEST_SAMPLE:
        email, status = clean_email(raw)
        ok = email == exp_email and status == exp_status
        if not ok:
            fails += 1
        mark = "ok " if ok else "FAIL"
        print(f"[{mark}] {raw!r:55} -> {email!r:40} ({status})"
              + ("" if ok else f"   expected {exp_email!r} ({exp_status})"))
    print(f"\n{len(SELF_TEST_SAMPLE) - fails}/{len(SELF_TEST_SAMPLE)} passed.")
    sys.exit(1 if fails else 0)


def cmd_clean(args):
    sheet_id = sh._sheet_id(args.sheet)
    rows = read_tab(sheet_id, args.tab)
    if not rows:
        raise SystemExit(f"Tab {args.tab!r} is empty.")
    hdr = rows[0]
    email_i = resolve_col(args.email_col, hdr)
    status_i = resolve_col(args.status_col, hdr) if args.status_col else None

    counts: dict[str, int] = {}
    samples: list[tuple[str, str, str]] = []
    email_vals: list[list[str]] = []   # one cell per data row
    status_vals: list[list[str]] = []
    changed = 0

    for r in rows[1:]:
        raw = r[email_i] if len(r) > email_i else ""
        cleaned, status = clean_email(raw)
        counts[status] = counts.get(status, 0) + 1
        if cleaned != (raw or "").strip():
            changed += 1
            if len(samples) < 20 and status in ("cleaned", "placeholder", "supplier", "invalid"):
                samples.append((raw, cleaned, status))
        email_vals.append([cleaned])
        status_vals.append([status])

    summary = {
        "tab": args.tab,
        "data_rows": len(rows) - 1,
        "status_breakdown": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        "cells_changed": changed,
        "email_col": idx_to_col(email_i),
        "status_col": idx_to_col(status_i) if status_i is not None else None,
    }

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if samples:
        print("\nsample changes (raw -> cleaned [status]):")
        for raw, cleaned, status in samples:
            print(f"  {raw!r:55} -> {cleaned!r:40} [{status}]")

    if args.dry_run:
        print("\n(dry-run — nothing written)")
        return

    # Write email column (and status column if requested) in chunks.
    def write_col(col_idx: int, values: list[list[str]]):
        col = idx_to_col(col_idx)
        for i in range(0, len(values), args.chunk):
            chunk = values[i:i + args.chunk]
            start = 2 + i  # data starts at row 2
            sh._api("POST", f"{sh.SHEETS}/{sheet_id}/values:batchUpdate", {
                "valueInputOption": "RAW",
                "data": [{"range": _range_body(args.tab, f"{col}{start}:{col}{start + len(chunk) - 1}"),
                          "values": chunk}],
            })

    write_col(email_i, email_vals)
    if status_i is not None:
        write_col(status_i, status_vals)
    print(f"\nwritten: email -> col {idx_to_col(email_i)}"
          + (f", status -> col {idx_to_col(status_i)}" if status_i is not None else ""))


def main():
    ap = argparse.ArgumentParser(description="Deterministically clean a scraped email column in a Google Sheet.")
    ap.add_argument("--self-test", action="store_true", help="run the built-in cleaner test cases and exit")
    ap.add_argument("--sheet", help="sheet URL or ID")
    ap.add_argument("--tab", help="tab name")
    ap.add_argument("--email-col", help="email column letter (K) or header name")
    ap.add_argument("--status-col", help="optional status column letter or header name")
    ap.add_argument("--chunk", type=int, default=500)
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    if args.self_test:
        cmd_self_test(args)
    if not (args.sheet and args.tab and args.email_col):
        ap.error("--sheet, --tab and --email-col are required (unless --self-test)")
    cmd_clean(args)


if __name__ == "__main__":
    main()
