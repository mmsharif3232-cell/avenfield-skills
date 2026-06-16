# Avenfield Skills — Operating Guide

## Prime Objective

**Execute cold-email campaigns FAST. Pure execution over perfection — but ZERO careless mistakes.**

The goal is throughput, not polish. Don't over-engineer, don't gold-plate, don't
stall on "could this be cleaner." Ship the campaign. The one thing that is never
acceptable is a careless/avoidable mistake — the kind that gets caught in review
or, worse, goes out to a real lead.

### What "fast execution" means
- Move directly to running the skill. Skip exploratory detours and optional polish.
- Don't ask for confirmation on routine, reversible steps — just do them.
- Prefer the smallest correct action that gets the campaign moving.
- Default to action; only pause when a mistake would be hard to undo (see below).

### What "no careless mistakes" means (the non-negotiables)
Before anything goes OUT (an email send, a lead push to Instantly, a sheet write
that others rely on), do a fast sanity pass:

1. **Right audience** — correct campaign, correct lead list, no test rows, no dupes.
2. **Right content** — no broken merge tags / spintax (`{{firstName}}`, `{first|second}`
   left unrendered), no placeholder text (`XXXX`, `[COMPANY]`, "Hi there,"), no
   "Re:" fakery unless intended. **Run `avenfield-spamguard` on any copy before it
   ships** — subjects, bodies, follow-ups — and remember merge variables can smuggle
   banned words in (e.g. `{{serviceLine}}` = "marketing"), so scan rendered values too.
3. **Right recipients** — emails verified (use `avenfield-verify`); drop invalid /
   disposable / role addresses unless explicitly told otherwise.
4. **Right links & names** — personalization fields resolve, company/first-name
   pulled from the correct column, links go where they should.
5. **No leakage** — never commit secrets; secrets live only under `~/.avenfield/`.

These checks are fast and mandatory. They are not "perfectionism" — they are the
difference between speed and recklessness. Everything outside this list, optimize
for speed.

### Irreversible-action rule
Sends, bulk lead pushes, and destructive sheet/Instantly writes are hard to undo.
For those, run the sanity pass above first. For reversible work, just execute.

### Keep the skills updated
Whenever you build a new capability, fix a behaviour, or learn a better workflow,
fold it back into the relevant skill (the script + its `SKILL.md`) and commit +
push — don't leave it as a one-off script. The skills are the durable record of
how we run campaigns; a fix that only lives in a chat is a fix that's lost next
session.

## The Skills (see README.md for full detail)
- `avenfield-browser-render` — render / scrape / screenshot / extract any site (single, batch, or dedupe-column → sidecar tab → map back).
- `avenfield-verify` — verify email deliverability (valid / catch-all / invalid / disposable / role).
- `avenfield-instantly` — drive Instantly v2 (campaigns, leads incl. bulk push-leads, sequences, generic passthrough).
- `avenfield-instantly-upload` — upload a sheet of leads into a campaign (column→field/var mapping, test-first, idempotent, never launches).
- `avenfield-sheets` — read/write any Google Sheet via the service account (incl. create/share/row-height/wrap).
- `avenfield-openai` — full OpenAI access (chat, extract, raw passthrough).
- `avenfield-personalize` — GPT personalization over scraped data (presets, test-first, cost estimate, spamguard, auto-retry, map-back).
- `avenfield-spamguard` — always-on deliverability/spam scan for all copy (run before anything ships).
- `avenfield-spintax` — spintax copy into Instantly {{RANDOM|...}} format (8 rules) + deterministic audit (count, banned scan, article/format).
