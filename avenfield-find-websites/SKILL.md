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

## Commands
```bash
F=~/.claude/skills/avenfield-find-websites/find_websites.py

# 1. estimate — row count + projected web-search/render calls + $ (NO API calls)
python3 $F estimate --sheet <ID> --tab VA_Worklist

# 2. test — run the full pipeline on N rows, print a results table, WRITE NOTHING
python3 $F test --sheet <ID> --tab VA_Worklist --n 15

# 3. run — full pass: writes confirmed_url + va_notes, idempotent, concurrent
python3 $F run --sheet <ID> --tab VA_Worklist [--limit N] [--overwrite] \
      [--status-cell T1]
```

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
