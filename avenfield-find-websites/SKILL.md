---
name: avenfield-find-websites
description: "Find an organization's REAL official website from its name + location, by rendering a live DuckDuckGo search and letting gpt-5-mini pick the official site from the real results (grounded → no hallucinated URLs), with a render-verify guard. Use ANY TIME a sheet has org/company/hospital names but missing, weak, or unconfirmed website URLs: 'find these hospitals' websites', 'confirm the official sites for this list', 'fill in the confirmed_url column', 'which of these guessed URLs are actually right'. Pipeline per row: (1) guess-first — render-verify an existing best-guess URL if present; (2) render the DuckDuckGo HTML results page via Cloudflare for real candidate URLs; (3) gpt-5-mini picks the official homepage (its own domain or its parent health system) from those real results; (4) confirm a grounded high/medium pick straight away, else render-verify the page (name/city or acronym on page) before accepting; (5) write the confirmed URL to confirmed_url + a status note to va_notes. Blank beats wrong — unverifiable candidates are recorded in notes, never as confirmed. Proven: 96% (976/1,017) on a real US hospital list at ~$0.50. Commands: estimate / trace / test / run. Does NOT verify email deliverability (avenfield-verify) or scrape page content for data (avenfield-browser-render)."
---

# Avenfield Find-Websites

The job a VA does by hand — Google an org by name + city + state, find their real
official website, confirm it's actually them — done at scale and **safely**.

## Why not just ask GPT?
A plain chat model invents official-looking URLs (we learned this on
email-finding). So this skill never trusts a *generated* URL — only a URL the live
search actually returned. Blank beats wrong: a false positive (wrong URL marked
confirmed) is worse than a false negative (right URL left in notes).

## Pipeline position
`(list of org names) → find-websites → [render/qualify/verify/upload]`

## How it works (one method — DDG render → GPT pick → verify)
Per row, in order:
1. **Guess-first short-circuit** — if `auto_best_guess` is set (and not a
   directory), render-verify it. A correct guess confirms in one render, no search.
2. **DuckDuckGo render** — render `html.duckduckgo.com/html/?q=<name city state>`
   via Cloudflare's `links` endpoint → the real organic results (url + title),
   `uddg=` redirects decoded. **All** results are passed through — no directory
   pre-filter.
3. **GPT pick** — **gpt-5-mini** chooses the official homepage from those real
   results (its own domain OR its parent health system, e.g. Parma →
   `uhhospitals.org`). The prompt tells it to skip news/directory/social/jobs/gov
   pages; it reasons over the result **titles** ("…| IU Health") to do so. We
   **fully trust the pick** (no directory blocklist on this path). The pick is
   **grounded** — GPT can only effectively choose a URL the search returned, so no
   hallucinated domains.
4. **Confirm** — a **grounded high/medium** pick is confirmed immediately, WITHOUT
   a verify render (big hospital sites bot-block / JS-render, so an on-page check is
   unreliable and would wrongly reject them). A low-confidence or ungrounded pick
   must pass a render-verify (name tokens + city, or host-acronym) on the homepage
   or the deep DDG URL behind it before it's written; otherwise it's noted, blank.

**Cost:** ~$0.0003/row GPT (~$0.30 for 1,000) + near-free Cloudflare (billed by
browser-time, 10 hrs/mo free). **Proven: 96% (976/1,017) on a real US hospital
list at ~$0.50 total**, recovering health-system parents (`iuhealth.org`, `dmc.org`,
`nuvancehealth.org`, `bannerhealth.com`, `carondelet.org`) that pure name-matching
can't see.

## Commands
```bash
F=~/.claude/skills/avenfield-find-websites/find_websites.py

# 0. trace — run ONE hospital and PRINT every step's raw output. The ONLY
#    command that writes NOTHING. Verify the DDG→GPT→grounding→verify→decision flow.
python3 $F trace --name "INDIANA UNIVERSITY HEALTH FRANKFORT INC" --city FRANKFORT --state IN

# 1. estimate — rows + projected renders/browser-hours + GPT $ (NO API calls)
python3 $F estimate --sheet <ID> --tab VA_Worklist

# 2. test — run the pipeline on a SAMPLE of N rows and WRITE them to the sheet
#    (same as run, just capped to N). --n sizes the sample; --start begins partway down.
python3 $F test --sheet <ID> --tab VA_Worklist --n 25 [--start 100]

# 3. run — full pass: writes confirmed_url + va_notes, idempotent, concurrent
python3 $F run --sheet <ID> --tab VA_Worklist [--start N] [--limit N] [--overwrite] \
      [--concurrency 10] [--flush-every 10] [--status-cell T1]
```
- **Speed:** `--concurrency` default 10; grounded high/medium GPT picks confirm
  WITHOUT a verify render (the slow part), so a ~1,000-row run is ~10–20 min, ~$0.30.
- **Real-time:** `--flush-every` (default 10) writes the sheet every 10 rows in one
  batched request — the sheet fills live and stays under Google's write quota.

`test`/`run` print real cost from the `X-Browser-Ms-Used` header + summed GPT
tokens, so the bill is measured, not guessed.

### Column mapping (defaults match the VA_Worklist layout)
`--name-col hospital_name --city-col city --state-col state --guess-col auto_best_guess --confirmed-col confirmed_url --notes-col va_notes`
— each accepts a **letter** (`Q`) or a **header name**.

- **Idempotent:** `run`/`test` skip rows that already have a `confirmed_url` unless `--overwrite`.
- `--start N` skips the first N data rows (0-based; `--start 100` = row 101+).
  `--limit N`/`--n N` cap rows processed (handy for partial runs).
- `--status-cell` writes a live `N/total (k confirmed)` ticker to one cell.

## The verify guard (how a URL gets confirmed)
After rendering the candidate to markdown, accept it if EITHER:
- **Host acronym** — the domain label starts with the org's initials
  (`dwmmh.org` = D W McMillan Memorial Hospital, `sarhcare.org` = South Arkansas
  Regional Hospital, `mlkch.org` = MLK Community Hospital). Very specific; catches
  sites branded under an abbreviation where the full name isn't on the page.
- **Page tokens** — significant name tokens appear on the page: 2+ tokens → a
  majority (or ≥1 token + the city); a lone generic token (e.g. "Mercy") → that
  token **and** the city, because one common word can't stand alone.

Statuses written to `va_notes`:
| status | confirmed_url | note |
|--------|---------------|------|
| `confirmed` | the verified homepage | `confirmed; gpt-pick <conf> (grounded); matches/differs from guess; <why>; src=gpt` (or `src=guess` via guess-first) |
| `found_unverified` | **blank** | `candidate=<url> gpt-pick <conf> (ungrounded/low: <why>); src=gpt` |
| `not_found` | **blank** | `no official site found (gpt: <why>); src=gpt` |

## Hard-won lessons (baked in)
- **DuckDuckGo HTML renders cleanly; Bing/Google don't.** `html.duckduckgo.com/html/`
  returns plain organic links (wrapped in `/l/?uddg=` redirects — decode them) and
  its #1 result is usually the official site. Bing returned only JS junk via the
  `links` endpoint. So the search targets DuckDuckGo.
- **Verify the deep result URL, write the homepage.** A health-system hospital's
  DDG result is often a deep link (`phhealthcare.org/locations/huntingdon`) whose
  page carries the specific name — so it verifies where the bare system homepage
  wouldn't. Render the full URL, confirm, then store `homepage()` as confirmed.
- **Fully trust GPT on directories — no blocklist on the search path.** Directory
  aggregators (`opennpi.com`, `healthgrades.com`, `pa211.org`, `.edu` lookalikes)
  share the hospital's name and would *pass* a name-on-page check, but we pass **all**
  DDG results to GPT and trust its pick: the prompt's "skip directory/news/social/
  jobs/gov" rule is GPT's directory defense (tune it there if one ever slips
  through). A small `DIRECTORY_HOSTS` blocklist survives ONLY for the guess-first
  short-circuit + the estimate count (so a directory guess isn't render-verified).
- **`X-Browser-Ms-Used` is a float string.** Parse it with `float()` then round —
  `int()` throws on `'1384.10'` and silently fails every render.
- **Grounding is the anti-hallucination guard.** A GPT pick is only acted on when
  its homepage appears in the real DDG results, so GPT can't invent a domain. Never
  write a URL the search didn't return (or that a render didn't prove).
- **Acronym domains are common in healthcare.** Many hospitals brand under
  initials, so name tokens aren't on the page — the host-acronym check recovers
  these without loosening the token rule.
- **Single generic tokens are traps.** "Mercy", "Memorial", "Regional" match
  half the internet; a lone token must be backed by the city to confirm.
- **Search is non-deterministic.** The same hospital can return a different (or
  no) candidate run to run. `run`/`test` are idempotent so a re-run only fills the
  gaps; use `--overwrite` to redo confirmed rows. Proxy/OpenAI blips mark a row
  `error` (blank+noted) without killing the batch — a later run retries it.
- **Expect ~90–96% confirmed** on a real US hospital list (96% measured on 1,017);
  the remaining tail is tiny/CAH or closed facilities that only have directory
  listings — safely blank as `not_found`/`found_unverified`, with the candidate noted.

## Reuses
`avenfield-openai/ai.py` (`call()` → gpt-5-mini pick) · `avenfield-browser-render/cf_render.py`
(`_creds`/`API_BASE`/`TRANSIENT` → `cf_render_ms` DDG render + verify) ·
`avenfield-sheets/sheets.py` (`_api`/`SHEETS`/`_sheet_id` → read/write).

## Does NOT
Verify email deliverability (`avenfield-verify`) · scrape page data
(`avenfield-browser-render`) · qualify against an ICP (`avenfield-qualify`).
It finds and verifies one thing: the official website.
