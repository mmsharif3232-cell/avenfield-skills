---
name: avenfield-find-websites
description: "Find an organization's REAL official website from its name + location, using OpenAI web search and a render-verify guard. Use ANY TIME a sheet has org/company/hospital names but missing, weak, or unconfirmed website URLs: 'find these hospitals' websites', 'confirm the official sites for this list', 'fill in the confirmed_url column', 'which of these guessed URLs are actually right'. Pipeline per row: (1) OpenAI web search for the official homepage (real URLs from a live search, not a hallucinated guess); (2) drop directories/social (facebook, yelp, healthgrades, google maps, wikipedia…); (3) render the best candidate via Cloudflare and VERIFY the org's name/city actually appear on the page (or the domain is the org's acronym) before accepting; (4) compare to any existing best-guess column; (5) write the verified URL to confirmed_url + a status note to va_notes. Only verified URLs are written — unverifiable candidates are recorded in notes, never as confirmed. Commands: estimate / test / run. Does NOT verify email deliverability (avenfield-verify) or scrape page content for data (avenfield-browser-render)."
---

# Avenfield Find-Websites

The job a VA does by hand — Google an org by name + city + state, find their real
official website, confirm it's actually them — done at scale and **safely**.

## Why not just ask GPT?
A plain chat model invents official-looking URLs (we learned this on
email-finding). So this skill never trusts a generated URL:
1. **Web search** (OpenAI Responses API `web_search` tool) supplies candidate
   URLs from a *live* search.
2. **Render-verify** (Cloudflare) fetches the candidate and only accepts it if
   the org is provably on the page. A URL that can't be verified is written to
   `va_notes` as a candidate for a human — **never** into `confirmed_url`.

Blank beats wrong. A false positive (wrong URL marked confirmed) is worse than a
false negative (right URL left in notes).

## Pipeline position
`(list of org names) → find-websites → [render/qualify/verify/upload]`

## Search backends (`--search-backend`)
- **`gpt`** (default, recommended) — render the **DuckDuckGo HTML** results page
  via Cloudflare, then a reasoning model (**gpt-5-mini**) PICKS the official site
  from those *real* results (its own domain or its parent health system). **All**
  DDG results are passed to GPT — no directory/aggregator pre-filter — and GPT's
  pick is trusted as-is (no post-pick directory guard); the prompt instructs GPT to
  skip news/directory/social/jobs/gov pages, and it reasons over the result titles
  to do so ("fully trust GPT"). The pick is still **grounded** (GPT may only
  effectively choose URLs the search returned, so no hallucinated domains). Confirms
  a grounded high/medium-confidence pick even when
  Cloudflare can't render it (big hospital sites bot-block / JS-render, which
  wrongly fails a name-on-page check); an actual on-page name match confirms at any
  confidence. **~$0.0003/row GPT** (~$0.28 for 1,000) + near-free Cloudflare.
  Test: 21/25 confirmed, recovering health-system parents (`iuhealth.org`,
  `dmc.org`, `nuvancehealth.org`, `balladhealth.org`) that pure matching misses.
- **`cloudflare`** — DuckDuckGo render, confirm only on a name/acronym-matched
  domain (no GPT, near-$0, but ~45% confirmed; misses differently-named systems).
- **`openai`** / **`hybrid`** — OpenAI `web_search` tool variants ($0.012/row);
  superseded by `gpt` (cheaper and more accurate here).

The **guess-first short-circuit** verifies an existing `auto_best_guess` before any
search — a correct guess costs one render.

### Why GPT-pick beats pure matching
A hospital is often part of a differently-named system (Manchester Memorial →
`echn.org`, Parma → `uhhospitals.org`). A domain name-match can't see that, and a
name-on-page render fails when the site bot-blocks. GPT reasons over the real
result **titles** ("…| IU Health") to choose correctly, and grounding + the
directory blocklist keep it from inventing or picking news/directory sites.

## Commands
```bash
F=~/.claude/skills/avenfield-find-websites/find_websites.py

# 0. trace — run ONE hospital and PRINT every step's raw output (no write).
#    Verify the DDG→GPT→grounding→verify→decision flow before a full run.
python3 $F trace --name "INDIANA UNIVERSITY HEALTH FRANKFORT INC" --city FRANKFORT --state IN

# 1. estimate — rows + projected renders/browser-hours + $ (NO API calls)
python3 $F estimate --sheet <ID> --tab VA_Worklist [--search-backend cloudflare]

# 2. test — run the full pipeline on N rows, print results + MEASURED browser-ms,
#    WRITE NOTHING
python3 $F test --sheet <ID> --tab VA_Worklist --n 25 [--search-backend cloudflare]

# 3. run — full pass: writes confirmed_url + va_notes, idempotent, concurrent
python3 $F run --sheet <ID> --tab VA_Worklist [--limit N] [--overwrite] \
      [--search-backend gpt] [--concurrency 10] [--flush-every 10] [--status-cell T1]
```
- **Speed:** `--concurrency` default 10; grounded high/medium GPT picks confirm
  WITHOUT a verify render (the slow part), so a ~1,000-row run is ~30 min, ~$0.27.
- **Real-time:** `--flush-every` (default 10) writes the sheet every 10 rows in one
  batched request — the sheet fills live and stays under Google's write quota.

`test`/`run` print real cost from the `X-Browser-Ms-Used` header (browser-hours +
projected full-run hours), so the bill is measured, not guessed.

### Column mapping (defaults match the VA_Worklist layout)
`--name-col hospital_name --city-col city --state-col state --guess-col auto_best_guess --confirmed-col confirmed_url --notes-col va_notes`
— each accepts a **letter** (`Q`) or a **header name**.

- **Idempotent:** `run` skips rows that already have a `confirmed_url` unless `--overwrite`.
- `--concurrency` default 8. `--limit` caps rows processed (handy for partial runs).
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
| `confirmed` | the verified homepage | `confirmed; matches/differs from guess; <reason>; src=web-search` |
| `found_unverified` | **blank** | `candidate=<url> unverified (<why>); src=web-search` |
| `not_found` | **blank** | `no official site found; src=web-search` |

## Hard-won lessons (baked in)
- **DuckDuckGo HTML renders cleanly; Bing/Google don't.** `html.duckduckgo.com/html/`
  returns plain organic links (wrapped in `/l/?uddg=` redirects — decode them) and
  its #1 result is usually the official site. Bing returned only JS junk via the
  `links` endpoint. So the Cloudflare backend targets DuckDuckGo.
- **Verify the deep result URL, write the homepage.** A health-system hospital's
  DDG result is often a deep link (`phhealthcare.org/locations/huntingdon`) whose
  page carries the specific name — so it verifies where the bare system homepage
  wouldn't. Render the full URL, confirm, then store `homepage()` as confirmed.
- **Directory aggregators are the main false-positive risk.** Sites like
  `hospitalsandclinics.net`, `opennpi.com`, `pa211.org`, and `.edu` colleges that
  share the hospital's name will *pass* a name-on-page check. The **`gpt` backend
  no longer pre-filters these** — it passes all DDG results to GPT and trusts the
  pick, leaning on the prompt's "skip directory/news/social/gov" rule (that prompt
  rule is now GPT's only directory defense — tune it there if one ever slips
  through). The legacy `cloudflare`/`openai` backends and the guess-first
  short-circuit still use the `DIRECTORY_HOSTS` blocklist (incl. all `.edu`/`.gov`),
  since they have no GPT reasoning step; add new aggregators there if needed.
- **`X-Browser-Ms-Used` is a float string.** Parse it with `float()` then round —
  `int()` throws on `'1384.10'` and silently fails every render.
- **Web search ≠ official site.** Searches love to return Google Maps, Facebook,
  Healthgrades. The directory/social blocklist + "their own domain" prompt strip
  those; the render-verify proves what's left.
- **Render-verify is the real guard, not citations.** Citation annotations are
  inconsistent across models, so URLs are parsed from the answer text too and
  every one is proven by rendering. Never write a URL you didn't fetch.
- **Acronym domains are common in healthcare.** Many hospitals brand under
  initials, so name tokens aren't on the page — the host-acronym check recovers
  these without loosening the token rule.
- **Single generic tokens are traps.** "Mercy", "Memorial", "Regional" match
  half the internet; a lone token must be backed by the city to confirm.
- **Search is non-deterministic.** The same hospital can return a different (or
  no) candidate run to run. `run` is idempotent so a re-run only fills the gaps;
  use `--overwrite` to redo confirmed rows.
- **Expect ~75–85% confirmed** on a real US hospital list; tiny/CAH facilities
  that only have directory listings land as `not_found`/`found_unverified` —
  safely blank, with the candidate noted.

## Reuses
`avenfield-openai/ai.py` (`call()` → web search) · `avenfield-browser-render/cf_render.py`
(`render_text()` → verify) · `avenfield-sheets/sheets.py` (`_api`/`SHEETS` → read/write).

## Does NOT
Verify email deliverability (`avenfield-verify`) · scrape page data
(`avenfield-browser-render`) · qualify against an ICP (`avenfield-qualify`).
It finds and verifies one thing: the official website.
