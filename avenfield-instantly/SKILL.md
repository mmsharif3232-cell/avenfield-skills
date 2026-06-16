---
name: avenfield-instantly
description: "Drive Instantly (v2 API) — list campaigns, add leads (single or bulk), push sequences, or call any endpoint. Use ANY TIME Momin wants to do something in Instantly — 'push these leads to Instantly', 'upload the sheet into the campaign', 'add them to campaign X', 'what campaigns do I have', 'upload this sequence', 'load these into Instantly', 'create a lead', 'update the campaign', or any send-side action once copy + leads are ready. Convenience commands: campaigns, add-lead, push-leads (bulk JSONL, parallel + idempotent), push-sequence; plus a generic passthrough to ANY v2 endpoint. It does NOT write copy, spintax, or verify emails — it's the Instantly transport. NEVER launches a campaign unless explicitly told."
---

# Avenfield Instantly (v2 API)

Everything send-side in Instantly. `instantly.py` in this skill dir; key (`INSTANTLY_API_KEY`) loads from `~/.avenfield/credentials.env`.

## Convenience commands

```bash
# list campaigns (id + name + status) — safe, read-only
python3 ~/.claude/skills/avenfield-instantly/instantly.py campaigns

# add one lead to a campaign (idempotent — skips if already in it)
python3 .../instantly.py add-lead --campaign <ID> --email ana@acme.com \
  --body '{"first_name":"Ana","company_name":"Acme","website":"acme.com",
           "custom_variables":{"city":"Leeds","blurb":"…"}}'

# overwrite a campaign's email sequence (bodies are <div>-per-line HTML)
python3 .../instantly.py push-sequence --campaign <ID> \
  --steps '[{"type":"email","delay":0,"variants":[{"subject":"quick q","body":"<div>Hi {{firstName}}</div>"}]}]'
```

## Generic passthrough (full power)

Anything the v2 API supports — Claude builds the call:

```bash
python3 .../instantly.py request GET   /campaigns --query 'limit=50'
python3 .../instantly.py request GET   /leads --query 'campaign=<ID>&limit=100'
python3 .../instantly.py request POST  /leads --body '{"campaign":"<ID>","email":"a@x.com"}'
python3 .../instantly.py request PATCH /campaigns/<ID> --body '{"name":"renamed"}'
```

## Pushing a list of leads

For one or a few: `add-lead`. For a whole list: **`push-leads`** — a JSONL of lead
objects (one per line), pushed in parallel, idempotent (`skip_if_in_campaign`),
with 429/5xx retries and progress to stderr:

```bash
# each line: {"email","first_name","last_name","company_name","website",
#             "custom_variables":{"serviceLine":"..."}}
python3 .../instantly.py push-leads --campaign <ID> --file leads.jsonl --concurrency 8
cat leads.jsonl | python3 .../instantly.py push-leads --campaign <ID>     # or via stdin
```

Variable mapping (verified): native fields `first_name` / `company_name` /
`website` back `{{firstName}}` / `{{companyName}}`; anything in
`custom_variables` (e.g. `serviceLine`) is stored in the lead's `payload` and
resolves as `{{serviceLine}}`. `{{accountSignature}}` is account-level — set on
the sending mailbox, not per lead. Confirm the campaign id with `campaigns` first,
and push ONE lead + read it back before the bulk run.

Proven flow (RaiseView ppr-002): read main sheet → build leads JSONL (fill blank
merge vars with a safe default so no `{{tag}}` renders empty) → `push-leads`.
2,355 leads pushed in ~2 min, 0 failures, campaign left in **draft** (not launched).

## Conventions (Avenfield)
Respect the locked Instantly setup: one campaign per list, custom variables camelCase, bodies start with the first name, `{{accountSignature}}` for sign-off. Re-pushing the same leads is safe (skips dupes).

## Notes
- Instantly is behind Cloudflare; the script sends a normal User-Agent so it isn't 403'd.
- `add-lead` and `push-sequence` are **real writes** to a live campaign — confirm the campaign id and that copy is approved before bulk-pushing.
