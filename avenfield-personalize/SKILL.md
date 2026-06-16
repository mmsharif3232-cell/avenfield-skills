---
name: avenfield-personalize
description: "Generate cold-email merge variables from scraped website data with OpenAI, write them to the sheet, and map them back onto the main lead list. Use ANY TIME Momin wants to PERSONALIZE leads from rendered content — 'fill the service line', 'get the {{serviceLine}} / merge variables out of the scraped markdown', 'personalize these prospects', 'extract a personalization field for the campaign', 'classify each company for the copy'. Wraps avenfield-openai with a campaign-personalization workflow: load a saved prompt PRESET, ALWAYS test on 10-20 prospects first, print the ESTIMATED cost before the full run, run the whole sheet only on --run with live progress + running cost, then map the variable into the main tab. Saved preset: service_line (RaiseView ppr-002). Pairs with avenfield-browser-render (render → personalize → map back)."
---

# Avenfield Personalize

GPT personalization over scraped website content. `personalize.py` reuses
`avenfield-openai/ai.py` (OpenAI + strict-JSON) and `avenfield-sheets/sheets.py`
(read/write). Keys load from `~/.avenfield/credentials.env`.

The job: take the rendered markdown for each company, ask OpenAI for the campaign
variable(s) (e.g. `{{serviceLine}}`), write them to a column, and map them onto
the main lead list — matched by website so duplicates line up.

## The guardrails (built in, on purpose)

1. **Test first.** With no `--run`, it processes only `--test N` (default 15)
   rows for real, writes them, prints each result, and reports the **actual test
   cost** plus an **extrapolated full-sheet cost**. Review before committing.
2. **Estimate before spend.** `--estimate` prints a no-API token/cost estimate
   for the whole sheet and exits.
3. **Full run is explicit.** Only `--run` processes the whole sheet — with live
   progress + running cost in `--status-cell`, then the map-back.

Token counts in reports are exact (from the API `usage`); the `$` uses an
approximate price table — override with `--price-in/--price-out` if needed.

## Run it

```bash
P=~/.claude/skills/avenfield-personalize/personalize.py

# 1) cost estimate for the whole sheet (no API calls)
python3 $P --sheet "<ID>" --tab "browser render" --content-col F --key-col A \
  --preset service_line --out-col G --estimate

# 2) TEST on the first 15 unique sites (writes col G, prints results + costs)
python3 $P --sheet "<ID>" --tab "browser render" --content-col F --key-col A \
  --preset service_line --out-col G --test 15

# 3) FULL run + map the service line into the main tab (matched by website)
#    --concurrency 8 ≈ 8x faster (parallel calls, with 429/5xx retries); 1 = sequential
python3 $P --sheet "<ID>" --tab "browser render" --content-col F --key-col A \
  --preset service_line --out-col G --run --concurrency 8 --status-cell K1 \
  --map-tab "Goodfirms-verified" --map-key-col H --map-out-col J
```

- `--content-col` = where the markdown is; `--key-col` = the match key (Website).
- Variables are written one-per-column starting at `--out-col`; the header row
  gets each var's `header` (or name).
- **Low-confidence handling.** The model self-reports `confidence` (high/low) and
  it's written to its own column (marked). Thin / nav-only / blocked / empty pages
  are flagged `low` and their service line is REPLACED by a safe fallback:
  `low_conf_fallback` = `most_common` (the most frequent service line across the
  confident rows) or a literal like `marketing`. Empty-content rows (failed
  renders) are treated as low-confidence too — no API call. Override per run with
  `--low-conf-fallback marketing` (or `--default`).
- `--map-*` writes one variable (`--map-var`, default the first) onto another tab,
  matched by normalized website — the dedupe→render→personalize→main flow.

## Presets

`presets/<name>.json` = `{ prompt, vars, model, reasoning_effort, max_chars,
normalize_case, empty_default }`. Saved:

- **`service_line`** — RaiseView `ppr-002` (marketing/creative agencies).
  `{{serviceLine}}` = the service the agency SELLS (what *their* prospects shop
  for), 1-3 words, reads in "companies shopping for ___ help". Model
  `gpt-5-nano`, case-normalized (SEO/PPC/PR uppercase), fallback "digital
  marketing". This prompt is tuned and gives good results — reuse it.

Override any field per-run with `--prompt-file`, `--vars`, `--model`,
`--reasoning-effort`, `--max-chars`, `--default`. Add new campaigns by dropping a
new JSON in `presets/`.

## Notes
- Models: `gpt-5-nano` (cheapest, default), `gpt-5-mini`, `gpt-4o-mini`. Full
  agency list (~1,300 rows) ≈ **$0.08–0.09** on nano.
- Calls are sequential — gentle on a fresh key's rate limits.
- Always render first with `avenfield-browser-render` (use its unique sidecar
  tab so you personalize each site once), then map back here.
