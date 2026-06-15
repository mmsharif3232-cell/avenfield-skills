---
name: avenfield-verify
description: "Verify email deliverability via OmniVerifier. Use ANY TIME Momin wants to check whether emails are valid / will bounce — 'verify these emails', 'check this list for valid emails', 'are these deliverable', 'clean this email list', 'which of these bounce', 'verify before sending', or as the deliverability gate before pushing leads to Instantly. Takes emails as args, from stdin, or extracted from a file, and returns each email's status (valid / invalid / catch-all / disposable / role / unknown) plus a summary. It only verifies — it does not render sites, write copy, or push to Instantly."
---

# Avenfield Verify (OmniVerifier)

Check email deliverability before sending. Returns one status per email so you can keep only the safe ones.

Capability: `verify.py` in this skill dir. Key (`OMNIVERIFIER_API_KEY`) loads automatically from `~/.avenfield/credentials.env`.

## Run it

```bash
# a few emails
python3 ~/.claude/skills/avenfield-verify/verify.py a@x.com b@y.com

# a whole list from a file (pulls every email-looking cell)
python3 .../verify.py --file leads.csv

# piped in (one per line)
cut -d, -f3 leads.csv | python3 .../verify.py --stdin
```

Output JSON:
```json
{ "results": {"a@x.com": "valid", "b@y.com": "catch-all"},
  "summary": {"valid": 1, "catch-all": 1}, "balance": 49998 }
```

## Statuses
`valid` (safe to send) · `catch-all` (accepts all — moderate risk) · `invalid` (will bounce — drop) · `disposable` (throwaway — drop) · `role` (info@/sales@ — judgement call) · `unknown`.

## Typical use
For a campaign list: verify → keep `valid` (and usually `catch-all`), drop `invalid`/`disposable` → then hand the survivors to `avenfield-instantly`. Each email costs ~1 OmniVerifier credit; the response reports remaining balance. Mention cost before verifying very large lists.

It's list-based under the hood (submit → process → results), so a call takes ~10–60s even for a few emails — that's normal.
