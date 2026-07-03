---
name: avenfield-spamguard
description: "Always-on deliverability/spam guardrails for every piece of cold-email copy. Use ANY TIME copy is written, reviewed, or about to ship — subject lines, openers, second lines, follow-ups, CTAs — and as a mandatory pre-send / pre-push QA. 'check this copy', 'is this subject spammy', 'scan the campaign for banned words', 'QA the sequence', 'will this hurt deliverability'. Scans for banned single words, internal-QA banned phrases, promotional/pressure wording, phishing-style language, blacklisted categories, and formatting bans (em dashes, ALL CAPS, multiple !!, greeting prefixes). Reports hits + safe-replacement suggestions, can scan a live Instantly sequence, and rewrites company names that contain a banned token. Rules live in rules.json. If a checker/QA flags a token, treat it as banned going forward unless Momin explicitly approves an exception."
---

# Avenfield Spamguard

Deliverability guardrails as code. `spamguard.py` + `rules.json`. Scans copy for
everything that gets cold email filtered or flagged, and suggests plain-language
rewrites. **Run it on anything before it ships** — that's part of the CLAUDE.md
pre-send sanity pass.

## Run it

```bash
G=~/.claude/skills/avenfield-spamguard/spamguard.py

echo "Hi Sam, act now — free trial!!" | python3 $G check     # stdin
python3 $G check --text "limited time offer in marketing"
python3 $G check --file draft.txt
python3 $G check-campaign --campaign <ID>     # scan a live Instantly sequence (spintax-aware)
python3 $G fix-company "Buckeye Insurance"    # -> "Buckeye"
```

`check` returns JSON: `banned_words`, `banned_phrases`, `high_risk_phrases`,
`phishing_phrases`, `blacklist_categories`, `formatting`, `suggestions`, and a
`clean` boolean. Spintax/merge syntax (`{{RANDOM|..}}`, `{{firstName}}`) is
flattened first, so real alternatives are scanned without false-flagging
`RANDOM` or braces.

## What it enforces (full lists in rules.json)
- **Banned single words** (internal QA): get, now, deal, marketing, cash, urgent, …
- **Banned short phrases**: circle back, great fit, following up here, …
- **Promotional / pressure**: act now, free trial, limited time, best deal, …
- **Phishing-style**: verify identity, account update, click to verify, …
- **Blacklisted categories**: casino, weight loss, miracle cure, …
- **Formatting**: no em dashes, no ALL CAPS (≥4 letters; SEO/PPC/PR/CMO are fine),
  no multiple `!!`, no Hi/Hello/Hey greeting before the first name.

## Detection nuance
- A banned token is still caught next to hyphens/punctuation (`cash-cycle` → `cash`)
  but NOT buried inside a longer word (`cashier` is fine) — avoids false positives.
- **Merge variables can smuggle banned words in.** Scanning the template misses
  what `{{serviceLine}}` resolves to — e.g. `marketing` is banned, so a value like
  "digital marketing" injects it into otherwise-clean copy. Scan the rendered
  values too (e.g. the service-line column), not just the sequence.

## Rewriting
- `fix-company` drops the banned token first (the stated first choice):
  `Calcon Mutual Mortgage` → `Calcon Mutual`. Edit `rules.json` `company_name_rewrites`
  for locked overrides.
- Safe replacements (in `rules.json` → `replacements`) are surfaced as
  `suggestions`. Style: plain, observational, permission over pressure.

## Exceptions
If a token is flagged, treat it as banned going forward **unless Momin explicitly
approves an exception** (e.g. "marketing" for an audience of marketing agencies).
Record approved exceptions by removing the token from `rules.json`.
