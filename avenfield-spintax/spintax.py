#!/usr/bin/env python3
"""Avenfield spintax — the deterministic audit backbone for Instantly spintax.

Claude writes the {{RANDOM|...|...}} copy (following SKILL.md's eight rules); this
script makes Phase-2 auditing exact instead of eyeballed:
  • count     — total combinations + per-block breakdown
  • audit     — scan every option for banned words (spamguard + spintax list),
                article-agreement risks, em dashes, format errors, custom-vars
                wrapped in blocks; then print N resolved sample combinations
  • combos    — print N random fully-resolved combinations

Only {{RANDOM|...}} blocks are spun; custom variables like {{firstName}} are left
intact. Reuses avenfield-spamguard for the banned-word list.

USAGE
  S=~/.claude/skills/avenfield-spintax/spintax.py
  python3 $S count  --file copy.txt
  python3 $S audit  --file copy.txt --samples 80
  cat copy.txt | python3 $S combos --n 5
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SG = _HERE.parent / "avenfield-spamguard"
if not (_SG / "spamguard.py").exists():
    _SG = Path.home() / ".claude" / "skills" / "avenfield-spamguard"
sys.path.insert(0, str(_SG))
try:
    import spamguard
except Exception:
    spamguard = None

# Spintax-specific bans (from the spec) on top of spamguard's list.
SPINTAX_BANNED = {"get", "chance", "call", "million", "loans", "insurance", "credit",
                  "cash", "deal", "access", "billing", "new", "now", "today", "free",
                  "only", "cost", "life", "finance", "financial", "bank", "open",
                  "sales", "medical", "urgent", "marketing", "investment", "invoice",
                  "mortgage", "claims"}

BLOCK_RE = re.compile(r"\{\{RANDOM\|(.*?)\}\}")
# case/space-sloppy block openers that violate the format
BAD_OPENER_RE = re.compile(r"\{\{\s*random\s*\|", re.I)


def banned_set():
    s = set(SPINTAX_BANNED)
    if spamguard:
        s |= set(spamguard.RULES["banned_words"])
    return s


def parse_blocks(text):
    """Return list of option-lists for each {{RANDOM|..}} block, in order."""
    return [m.group(1).split("|") for m in BLOCK_RE.finditer(text)]


def count(text):
    blocks = parse_blocks(text)
    per = [len(b) for b in blocks]
    total = 1
    for n in per:
        total *= n
    return {"blocks": len(blocks), "per_block": per, "total_combinations": total}


def resolve(text, rng=random):
    return BLOCK_RE.sub(lambda m: rng.choice(m.group(1).split("|")), text)


def _hits(word_text, bset):
    low = word_text.lower()
    return sorted({w for w in bset
                   if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low)})


def audit(text, samples=60):
    bset = banned_set()
    blocks = parse_blocks(text)
    issues = {"banned_options": [], "article_risks": [], "em_dashes": [],
              "format": [], "vars_in_block": [], "single_option_blocks": []}

    # format: sloppy openers (lowercase RANDOM, spaces)
    for m in BAD_OPENER_RE.finditer(text):
        if m.group(0) != "{{RANDOM|":
            issues["format"].append(f"bad block opener: {m.group(0)!r} (must be '{{{{RANDOM|')")

    for i, opts in enumerate(blocks):
        if len(opts) < 2:
            issues["single_option_blocks"].append({"block": i, "options": opts})
        for opt in opts:
            if "{{" in opt or "}}" in opt:
                issues["vars_in_block"].append({"block": i, "option": opt})
            if "—" in opt or "–" in opt:
                issues["em_dashes"].append({"block": i, "option": opt})
            for w in _hits(opt, bset):
                issues["banned_options"].append({"block": i, "option": opt, "banned": w})
        # pipe spacing inside the block
        if any(o != o.strip() for o in opts):
            issues["format"].append({"block": i, "issue": "space around a pipe/option"})

    # article agreement: a fixed 'a'/'an' immediately before a block with mixed starts
    for m in re.finditer(r"\b(a|an)\s+\{\{RANDOM\|(.*?)\}\}", text):
        art, opts = m.group(1).lower(), m.group(2).split("|")
        starts_vowel = [o.strip()[:1].lower() in "aeiou" for o in opts if o.strip()]
        if len(set(starts_vowel)) > 1 or (art == "a" and any(starts_vowel)) \
                or (art == "an" and not all(starts_vowel)):
            issues["article_risks"].append({"article": art, "options": opts,
                                             "fix": "pull the article inside each option (a/an)"})

    # sample resolved combinations + scan them too
    rng = random.Random(0)
    seen, sample_combos, bad_combos = set(), [], []
    tries = 0
    while len(sample_combos) < samples and tries < samples * 20:
        tries += 1
        c = resolve(text, rng)
        if c in seen:
            continue
        seen.add(c)
        sample_combos.append(c)
        if "—" in c or _hits(c, bset):
            bad_combos.append(c)

    clean = not any(issues[k] for k in issues) and not bad_combos
    return {"count": count(text), "clean": clean, "issues": issues,
            "samples_generated": len(sample_combos),
            "failing_samples": bad_combos[:5],
            "sample_combinations": [re.sub(r"\s+", " ", c).strip() for c in sample_combos[:5]]}


def _read(args):
    if args.text:
        return args.text
    if args.file:
        return Path(args.file).read_text(errors="replace")
    return sys.stdin.read()


def main():
    ap = argparse.ArgumentParser(description="Instantly spintax: count / audit / combos.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("count", "audit", "combos"):
        p = sub.add_parser(name)
        p.add_argument("--text"); p.add_argument("--file")
        if name == "audit":
            p.add_argument("--samples", type=int, default=60)
        if name == "combos":
            p.add_argument("--n", type=int, default=5)
        p.set_defaults(cmd=name)
    args = ap.parse_args()
    text = _read(args)
    if args.cmd == "count":
        print(json.dumps(count(text), indent=2))
    elif args.cmd == "audit":
        print(json.dumps(audit(text, args.samples), ensure_ascii=False, indent=2))
    else:
        rng = random.Random()
        for k in range(args.n):
            print(f"--- combo {k+1} ---")
            print(re.sub(r"\s+", " ", resolve(text, rng)).strip())


if __name__ == "__main__":
    main()
