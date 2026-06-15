---
name: avenfield-instantly
description: "Drive Instantly (v2 API) — list campaigns, add leads, push sequences, or call any endpoint. Use ANY TIME Momin wants to do something in Instantly — 'push these leads to Instantly', 'add them to campaign X', 'what campaigns do I have', 'upload this sequence', 'load these into Instantly', 'create a lead', 'update the campaign', or any send-side action once copy + leads are ready. Has a generic passthrough so it can hit ANY Instantly v2 endpoint with any method/body, plus convenience commands for the common cases. It does NOT write copy, spintax, or verify emails — it's the Instantly transport."
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

The usual flow: you have verified, enriched leads (from `avenfield-verify` + research). Loop them through `add-lead` (one call each, idempotent), mapping their fields into `custom_variables` so the campaign's `{{variables}}` resolve. Confirm the campaign id with `campaigns` first.

## Conventions (Avenfield)
Respect the locked Instantly setup: one campaign per list, custom variables camelCase, bodies start with the first name, `{{accountSignature}}` for sign-off. Re-pushing the same leads is safe (skips dupes).

## Notes
- Instantly is behind Cloudflare; the script sends a normal User-Agent so it isn't 403'd.
- `add-lead` and `push-sequence` are **real writes** to a live campaign — confirm the campaign id and that copy is approved before bulk-pushing.
