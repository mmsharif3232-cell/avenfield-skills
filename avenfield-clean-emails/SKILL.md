---
name: avenfield-clean-emails
description: "Deterministically clean a scraped/dirty email column in a Google Sheet — no GPT, no guessing. Use ANY TIME an email list looks filthy: leading %20 / URL-encoding, zero-width unicode prefixes, leading underscores or dashes (_info@, ---name@), markdown hyperlinks glued onto the address (service@[www.x.com](https://x.com)), phone numbers concatenated in front ((305) 826-2645info@x.com), doubled-TLD garbage (.cominfo, .commonday), template placeholders (_email@yourwebsite.com, +1@model.phone.replace), SMS gateways (digits@tmomail.net), or supplier-chain addresses (@ferguson.com). Triggers: 'clean these emails', 'the email column is a mess', 'strip the junk off these addresses', 'fix the scraped emails before verifying/uploading'. Reads one email column, writes back the cleaned address plus a per-row status (cleaned/unchanged/placeholder/supplier/invalid/empty). Does NOT verify deliverability (use avenfield-verify next) or find missing emails (that's a render+harvest job)."
---

# Avenfield Clean-Emails

Scraped email columns arrive filthy. This skill turns one dirty column into a
clean one **deterministically** — pure Python, zero API/GPT calls, so it's fast,
free, and never fabricates an address. Every cell gets a status so you can see
exactly what happened, and anything it can't confidently resolve is **blanked +
flagged**, never guessed. Better an empty cell than a wrong send.

## Pipeline position
`scrape/harvest emails → clean-emails → avenfield-verify → avenfield-instantly-upload`

Run this BEFORE verifying — verifying junk wastes credits, and a `%20info@…`
address fails verification even though the real address is fine.

## Commands

### `clean` — in-place: clean the email column and write a status column

```bash
E=~/.claude/skills/avenfield-clean-emails/clean_emails.py

# Dry-run: status breakdown + 20 sample changes, writes nothing
python3 $E clean --sheet "<URL|ID>" --tab "Main" \
    --email-col L --status-col N --dry-run

# Full run: clean col L in-place, status into col N
python3 $E clean --sheet "<URL|ID>" --tab "Main" \
    --email-col L --status-col N

# Sanity-check the cleaner itself (no sheet needed)
python3 $E --self-test
```

### `extract` — clean + filter (valid only) + deduplicate → new tab

```bash
# Preview counts, write nothing
python3 $E extract --sheet "<URL|ID>" --tab "Main" \
    --email-col L --dest-tab clean_emails --dry-run

# Full run: writes clean_emails tab with all original columns + email_clean_status
python3 $E extract --sheet "<URL|ID>" --tab "Main" \
    --email-col L --dest-tab clean_emails
```

- `--email-col` accepts a column **letter** (`L`) or a **header name** (`email`).
- `--status-col` (clean command) is optional — omit to only rewrite the email column.
- `--dry-run` reports and writes nothing. **Always dry-run first** on a real list.
- `--chunk` (default 500) controls write batch size.
- **Idempotent:** re-running `extract` clears + rewrites the dest tab; re-running `clean` on already-clean values returns `unchanged`.

## The cleaning algorithm (in order)
1. **URL-decode** twice (`%20`→space, `%28`→`(`, `%22`→`"`, `%e2%80%8d`→ZWJ; twice catches `%2520` double-encoding).
2. **Strip zero-width / bidi chars** (U+200B/C/D, U+FEFF, U+200E/F, U+2060) anywhere in the string.
3. **Markdown link** `[text](url)` → keep the **text** (the `(url)` is a website, not the email).
4. **Strip a phone number** glued to the front of the local-part (`(305) 826-2645info@…` → `info@…`).
5. **Regex-extract** the first plausible address `[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}`.
6. **Strip leading junk** off the local-part (`_`, `-`, `.`, `+`) and a stray `www.` off the domain.
7. **Block-lists** (exact domain, before TLD repair): placeholder/template, SMS gateway, supplier-chain.
8. **TLD validate + repair**: known-TLD set; doubled-TLD garbage repaired (`flahvac.cominfo`→`.com`, `yahoo.commonday`→`yahoo.com`). Real multi-char gTLDs (`.company`, `.network`, `.services`) are preserved, not truncated. Unrecoverable TLD → `invalid`.
9. **Local-part sanity**: must contain a letter (all-numeric local-parts like `191@` or `17175724870@` → `invalid`).

## Status values
| status | meaning | email cell |
|--------|---------|-----------|
| `unchanged` | was already a clean address | kept |
| `cleaned` | junk stripped, valid address extracted | cleaned value |
| `placeholder` | template/generic domain (`yourwebsite.com`, `mail.com`, `model.phone.replace`, `hardwarestore.com`…) | **blank** |
| `supplier` | manufacturer/distributor chain (`ferguson.com`, `basf.com`, `lennoxpros.com`…) | **blank** |
| `invalid` | bad TLD, all-numeric local-part, or SMS gateway (`tmomail.net`) | **blank** |
| `empty` | source cell was blank | blank |

## Hard-won lessons (baked in)
- **Decode BEFORE matching.** The single most common defect is a leading `%20`
  (URL-encoded space); the address underneath is perfect. Decode first or you
  verify-fail thousands of good leads.
- **The `(url)` of a markdown link is NOT the email.** Keep the link text.
- **Never invent a typo-fix.** `nfo@…` (a chewed `info@`) is KEPT, not "fixed" —
  we can't tell it from a legit short inbox (`hr@`, `pr@`). The deliverability
  call belongs to `avenfield-verify`, not a regex.
- **Blank, don't guess.** Placeholder/supplier/invalid rows are emptied + flagged.
  An empty cell is recoverable; a fabricated address gets bounced or, worse, sent.
- **Repair doubled TLDs only for com/net/org**, and only when the trailing label
  isn't itself a real gTLD — otherwise `foo.company` would wrongly become `foo.com`.
- **Block supplier chains.** HVAC scrapes pull `@ferguson.com`, `@basf.com`,
  `@lennoxpros.com` — vendors the contractor buys FROM, not prospects.

To extend a block-list (new placeholder/supplier domain) or TLD, edit the sets
at the top of `clean_emails.py` and add a case to `SELF_TEST_SAMPLE`, then run
`--self-test`.

## Does NOT
Verify deliverability (`avenfield-verify`) · find/harvest missing emails (render
+ scrape) · upload (`avenfield-instantly-upload`). It cleans one column in place.
