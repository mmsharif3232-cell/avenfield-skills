---
name: avenfield-gmaps-scraper
description: "Scrape Google Maps business leads via a RapidAPI scraper and populate a Google Sheet. Use ANY TIME Momin wants local-business lead data — 'scrape Google Maps', 'find plumbers in Dallas', 'pull local businesses into the sheet', 'run the RapidAPI scraper', 'populate the leads sheet from Maps'. Takes search queries (single, repeated, or a file of them), returns normalized lead rows (name, address, phone, website, email, rating, place_id…), and appends them idempotently into a sheet tab (deduped on place_id). It only scrapes and writes rows — cleaning, verifying, personalizing, and pushing to Instantly are the downstream skills."
---

# Avenfield GMaps Scraper (RapidAPI)

Google Maps business data → normalized lead rows → Google Sheet. Wraps a
Google Maps scraper hosted on RapidAPI; sheet writes reuse the
`avenfield-sheets` service account.

Capability: `gmaps_scraper.py` in this skill dir. Keys (`RAPIDAPI_KEY`,
optional `RAPIDAPI_HOST`) load from `~/.avenfield/credentials.env`.
Default listing: **Local Business Data** (letscrape),
host `local-business-data.p.rapidapi.com` — override with `RAPIDAPI_HOST`
or `--host` for a different scraper.

## Run it (test → estimate → run)

```bash
# 1. dry run — 1 query, ≤3 rows, never writes
python3 ~/.claude/skills/avenfield-gmaps-scraper/gmaps_scraper.py \
    test --query "plumbers in Dallas, TX"

# 2. quota check — 1 RapidAPI call per query
python3 .../gmaps_scraper.py estimate --queries-file queries.txt --limit 20

# 3. full run into a sheet (tab auto-created, deduped on place_id)
python3 .../gmaps_scraper.py search --queries-file queries.txt --limit 20 \
    --sheet "https://docs.google.com/spreadsheets/d/<ID>/edit" --tab leads

# generic passthrough to any other endpoint of the listing
python3 .../gmaps_scraper.py raw --path business-details --param business_id=<id>
```

Sheet output columns:
`query | name | category | full_address | city | state | zip | country | phone |
website | email | rating | review_count | place_id | google_id | lat | lng |
business_status | verified`

## Idempotency & safety
- Re-running the same queries appends **zero duplicates** — rows are deduped on
  `place_id` against what's already in the tab (and within the batch).
- `test` never writes; `search` without `--sheet` just prints JSON.
- Each query = 1 call against the RapidAPI plan quota. Run `estimate` and
  mention the call count before large batches.
- Emails scraped here are raw — always run `avenfield-clean-emails` then
  `avenfield-verify` before anything ships.

## Downstream flow
scrape (this) → `avenfield-clean-emails` → `avenfield-verify` →
`avenfield-personalize` / `avenfield-qualify` → `avenfield-instantly-upload`.
New campaign? Log the sheet in the Campaign Log per CLAUDE.md.

## About RapidAPI + MCP (for reference)

RapidAPI now has **official MCP support at the platform level** — individual
scrapers do not ship their own MCP servers. If a listing has the feature
enabled, RapidAPI exposes it at `mcp.rapidapi.com` with one MCP tool per
endpoint, authenticated with the same `x-rapidapi-key`. Parts of the feature
were still "coming soon" as of mid-2026 (docs:
https://docs.rapidapi.com/docs/consume-apis-using-ai).

To check availability: open the listing's **Playground** on rapidapi.com and
look for an MCP option/panel — it shows the exact MCP URL and per-client
connect instructions. To connect Claude Code without committing the key:

```bash
claude mcp add --transport http gmaps-scraper <MCP-URL-from-playground> \
    --header "x-rapidapi-key: ${RAPIDAPI_KEY}"
```

**When to use which:** MCP is fine for ad-hoc one-off lookups in chat. For
campaign work — batches, pagination, retries, dedupe, sheet write-back — use
this script; MCP tool calls are one-at-a-time and can't do any of that.
