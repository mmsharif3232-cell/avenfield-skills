---
name: avenfield-instantly-upload
description: "Upload a Google Sheet of leads straight into an Instantly campaign — the sheet→Instantly workflow. Use ANY TIME Momin wants to 'upload the sheet to Instantly', 'push these leads into campaign X', 'load the Goodfirms list into Instantly', 'add the sheet's leads with the merge variables', or get a lead list from Sheets into a campaign. Maps sheet columns → Instantly lead fields (first/last/company/website) + campaign merge variables (custom vars like serviceLine), drops bad/duplicate emails, fills blank merge vars so no {{tag}} renders empty, and pushes TEST-first then bulk on --run. Idempotent (skips leads already in the campaign). NEVER launches the campaign — it only adds leads. Wraps avenfield-instantly (transport) + avenfield-sheets (read). For writing copy/sequences use avenfield-instantly; for verifying emails first use avenfield-verify."
---

# Avenfield Instantly Upload

Sheet → Instantly, end to end. `upload.py` reads a tab with `avenfield-sheets`,
maps columns to lead fields + merge variables, and pushes them into a campaign
with `avenfield-instantly`'s idempotent, parallel add. It **never launches** a
campaign — only adds leads (the campaign stays in whatever status it was).

## Guardrails (built in)
- **Dry-run / test first.** `--dry-run` builds + validates + samples, pushes
  nothing. No `--run` = pushes only `--test N` (default 10) and reads a few back
  so you can confirm the merge vars stored. `--run` does the whole sheet.
- **Clean list.** Drops blank + malformed emails, de-dupes by email.
- **No empty merge tags.** `--var-default name=value` fills blanks (e.g. a lead
  with no service line gets `marketing`) so `{{serviceLine}}` never renders empty.
- **Idempotent.** Re-running skips leads already in the campaign (`--allow-dupes`
  to override).

## Run it

```bash
U=~/.claude/skills/avenfield-instantly-upload/upload.py

# 1) DRY RUN — see counts + a sample, push nothing
python3 $U --sheet "<ID>" --tab "Goodfirms-verified" --campaign-name "ppr-002" \
  --email-col D --first-col A --last-col B --company-col G --website-col H \
  --var serviceLine=J --var-default serviceLine=marketing --dry-run

# 2) TEST — push first 10, read a few back
python3 $U ...same... --test 10

# 3) FULL upload (idempotent; campaign stays draft)
python3 $U ...same... --run --concurrency 8
```

## Column mapping
- Field cols: `--email-col` (required), `--first-col`, `--last-col`,
  `--company-col`, `--website-col`. Each takes a **letter** (`D`) or a **header
  name** (`"Email"`). `--map-by-header` auto-detects the common ones; explicit
  flags override.
- Merge variables: `--var name=COL` (repeatable), COL is a letter or header.
  These become the lead's custom variables and resolve as `{{name}}` in the copy
  (stored in Instantly's lead `payload`).
- Campaign: `--campaign <ID>` or `--campaign-name "<partial>"` (errors if 0 or >1
  match, so you never push to the wrong one).

## Variable mapping (how Instantly resolves the copy)
- `first_name` → `{{firstName}}`, `company_name` → `{{companyName}}`, `website` set.
- Each `--var` (e.g. `serviceLine`) → `{{serviceLine}}` via the lead payload.
- `{{accountSignature}}` is account-level (on the sending mailbox) — not per lead.

## Proven run — RaiseView `ppr-002`
`--email-col D --first-col A --last-col B --company-col G --website-col H
--var serviceLine=J --var-default serviceLine=marketing` →
2,355 valid unique leads, 7 blank service lines filled with `marketing`, pushed
0 failures into the draft, campaign left unlaunched. Verify a lead with
`avenfield-instantly request POST /leads/list` (vars live under `payload`).

## Notes
- Pair with `avenfield-verify` first if you want to drop risky emails before upload.
- This skill doesn't touch the sequence/schedule or send state — use
  `avenfield-instantly` for copy/sequence and to launch when you're ready.
