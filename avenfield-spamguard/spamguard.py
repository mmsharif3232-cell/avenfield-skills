#!/usr/bin/env python3
"""Avenfield spamguard — deliverability/spam scan for cold-email copy.

Always-on guardrails. Scans subject lines, openers, bodies, follow-ups, CTAs for
banned words/phrases, phishing-style + promotional wording, blacklisted
categories, and formatting bans (em dashes, ALL CAPS, multiple !!, greeting
prefix). Reports hits + safe-replacement suggestions. Also scans a live Instantly
campaign's sequence so you can QA before launch.

Rules live in rules.json (edit there to add/remove tokens). Nuance: a banned
token is still caught with adjacent hyphens/punctuation (cash-cycle → cash) but
NOT inside a longer word (cashier is fine), to avoid false positives.

USAGE
  G=~/.claude/skills/avenfield-spamguard/spamguard.py
  echo "Hi Sam, act now for a free trial!!" | python3 $G check
  python3 $G check --text "limited time offer"
  python3 $G check --file draft.txt
  python3 $G check-campaign --campaign <ID>      # scan a live Instantly sequence
  python3 $G fix-company "Buckeye Insurance"     # → "Buckeye"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
RULES = json.loads((_HERE / "rules.json").read_text())
_BANNED = set(RULES["banned_words"])


def _instantly():
    p = _HERE.parent / "avenfield-instantly"
    if not (p / "instantly.py").exists():
        p = Path.home() / ".claude" / "skills" / "avenfield-instantly"
    sys.path.insert(0, str(p))
    import instantly
    return instantly


def word_hits(text):
    low = text.lower()
    # token bounded by non-letters on both sides → catches hyphen/punct variants,
    # ignores the token buried inside a longer word.
    return sorted({w for w in RULES["banned_words"]
                   if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low)})


def phrase_hits(text, key):
    low = text.lower()
    return sorted({p for p in RULES[key] if p.lower() in low})


def formatting_hits(text):
    f = []
    if "—" in text or "–" in text:
        f.append("em/en dash")
    if re.search(r"!\s*!", text):
        f.append("multiple exclamation marks")
    caps = re.findall(r"\b[A-Z]{4,}\b", text)   # >=4 keeps SEO/PPC/PR/CMO safe
    f += [f"ALL CAPS: {c}" for c in sorted(set(caps))]
    if re.match(r"^\s*(hi|hello|hey)\b", text, re.I):
        f.append("greeting prefix before first name")
    return f


def _flatten_spintax(text):
    """Drop spintax/merge control syntax ({{RANDOM|..}}, braces, pipes) but KEEP the
    inner words, so we scan the real alternatives without flagging 'RANDOM'/braces."""
    text = re.sub(r"\{\{\s*RANDOM\s*\|", " ", text, flags=re.I)
    return text.replace("{{", " ").replace("}}", " ").replace("|", " ")


def check_text(text):
    text = _flatten_spintax(text)
    res = {
        "banned_words": word_hits(text),
        "banned_phrases": phrase_hits(text, "banned_phrases"),
        "high_risk_phrases": phrase_hits(text, "high_risk_phrases"),
        "phishing_phrases": phrase_hits(text, "phishing_phrases"),
        "blacklist_categories": phrase_hits(text, "blacklist_categories"),
        "formatting": formatting_hits(text),
    }
    sugg = {}
    for cat in ("banned_phrases", "high_risk_phrases", "phishing_phrases", "blacklist_categories"):
        for p in res[cat]:
            if p.lower() in RULES["replacements"]:
                sugg[p] = RULES["replacements"][p.lower()]
    res["suggestions"] = sugg
    res["clean"] = not any(res[k] for k in
                           ("banned_words", "banned_phrases", "high_risk_phrases",
                            "phishing_phrases", "blacklist_categories", "formatting"))
    return res


def fix_company(name):
    """Deterministic best-effort: drop banned tokens first (the stated first choice)."""
    parts = name.split()
    kept = [p for p in parts if re.sub(r"[^a-z]", "", p.lower()) not in _BANNED]
    if len(kept) >= 2 or (len(kept) == 1 and len(kept[0]) > 3):
        return " ".join(kept)
    # removing the token leaves too little → initialism of the non-banned heads
    initials = "".join(p[0].upper() for p in parts
                       if re.sub(r"[^a-z]", "", p.lower()) not in _BANNED) or parts[0][:2].upper()
    tail = parts[-1] if re.sub(r"[^a-z]", "", parts[-1].lower()) not in _BANNED else ""
    return (initials + (" " + tail if tail else "")).strip()


def _read_text(args):
    if args.text:
        return args.text
    if args.file:
        return Path(args.file).read_text(errors="replace")
    return sys.stdin.read()


def cmd_check(args):
    print(json.dumps(check_text(_read_text(args)), ensure_ascii=False, indent=2))


def cmd_check_campaign(args):
    inst = _instantly()
    status, d = inst.call("GET", f"/campaigns/{args.campaign}")
    camp = d.get("result", d) if isinstance(d, dict) else d
    findings = []
    clean = True
    for si, seq in enumerate(camp.get("sequences") or []):
        for sti, step in enumerate(seq.get("steps") or []):
            for vi, v in enumerate(step.get("variants") or []):
                blob = (v.get("subject") or "") + "\n" + re.sub(r"<[^>]+>", " ", v.get("body") or "")
                r = check_text(blob)
                if not r["clean"]:
                    clean = False
                    findings.append({"step": sti, "variant": vi,
                                     "subject": (v.get("subject") or "")[:60],
                                     "banned_words": r["banned_words"],
                                     "high_risk_phrases": r["high_risk_phrases"],
                                     "banned_phrases": r["banned_phrases"],
                                     "phishing_phrases": r["phishing_phrases"],
                                     "formatting": r["formatting"]})
    print(json.dumps({"campaign": args.campaign, "name": camp.get("name"),
                      "clean": clean, "findings": findings}, ensure_ascii=False, indent=2))


def cmd_fix_company(args):
    print(fix_company(args.name))


def main():
    ap = argparse.ArgumentParser(description="Cold-email deliverability/spam scanner.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check", help="Scan text (--text/--file/stdin) for banned + risky wording.")
    p.add_argument("--text"); p.add_argument("--file"); p.set_defaults(fn=cmd_check)
    p = sub.add_parser("check-campaign", help="Scan a live Instantly campaign's sequence copy.")
    p.add_argument("--campaign", required=True); p.set_defaults(fn=cmd_check_campaign)
    p = sub.add_parser("fix-company", help="Rewrite a company name to drop a banned token.")
    p.add_argument("name"); p.set_defaults(fn=cmd_fix_company)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
