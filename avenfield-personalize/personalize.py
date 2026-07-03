#!/usr/bin/env python3
"""Avenfield personalize — GPT personalization over scraped website data.

Turn rendered website markdown (from avenfield-browser-render) into campaign
merge variables ({{serviceLine}}, etc.) with OpenAI, write them to the sheet,
and map them back onto the main lead list. Built for cold-email personalization.

Reuses the sibling skills:
  • avenfield-openai/ai.py     — OpenAI call + strict-JSON schema builder
  • avenfield-sheets/sheets.py — Sheets auth + read/write

WORKFLOW IT ENFORCES (so you never torch a key by accident):
  1. TEST first (default): run on the first N rows for real, write them, print
     each result + the ACTUAL test cost, then EXTRAPOLATE the full-sheet cost.
  2. Review. Only when you pass --run does it process the whole sheet (with live
     progress + running cost in a status cell), then optionally map a variable
     back onto another tab.
  --estimate prints a no-API cost estimate and exits.

USAGE
  P=~/.claude/skills/avenfield-personalize/personalize.py

  # TEST the saved service-line preset on the first 15 unique sites:
  python3 $P --sheet "<ID>" --tab "browser render" --content-col F --key-col A \
      --preset service_line --out-col G --test 15

  # Pure cost estimate for the full sheet, no API calls:
  python3 $P --sheet <ID> --tab "browser render" --content-col F --preset service_line --out-col G --estimate

  # FULL run + map the result back into the main tab (matched by website):
  python3 $P --sheet <ID> --tab "browser render" --content-col F --key-col A \
      --preset service_line --out-col G --run \
      --map-tab "Goodfirms-verified" --map-key-col H --map-out-col J --status-cell I1

Presets live in presets/<name>.json (prompt + vars + model). Override any of it
with --prompt-file / --vars / --model / --reasoning-effort / --max-chars.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

_HERE = Path(__file__).resolve().parent

_OAI = _HERE.parent / "avenfield-openai"
if not (_OAI / "ai.py").exists():
    _OAI = Path.home() / ".claude" / "skills" / "avenfield-openai"
_SH = _HERE.parent / "avenfield-sheets"
if not (_SH / "sheets.py").exists():
    _SH = Path.home() / ".claude" / "skills" / "avenfield-sheets"
_SG = _HERE.parent / "avenfield-spamguard"
if not (_SG / "spamguard.py").exists():
    _SG = Path.home() / ".claude" / "skills" / "avenfield-spamguard"
sys.path.insert(0, str(_OAI))
sys.path.insert(0, str(_SH))
sys.path.insert(0, str(_SG))
import ai       # noqa: E402
import sheets   # noqa: E402
try:
    import spamguard  # noqa: E402  — deliverability guardrails (optional)
except Exception:
    spamguard = None

# common banned-word → clean equivalents for personalization outputs (never "growth")
SPAM_SYNONYMS = {"marketing": "advertising", "performance": "advertising", "sales": "revenue",
                 "medical": "healthcare", "financial": "finance-sector", "finance": "finance-sector",
                 "home": "residential", "life": "wellness", "insurance": "risk", "investment": "capital"}

# Approximate list prices, USD per 1M tokens (input, output). Token counts in the
# reports are exact (from the API usage field); the $ uses this table — override
# with --price-in / --price-out if OpenAI's prices have moved.
PRICES = {
    "gpt-5-nano":  (0.05, 0.40),
    "gpt-5-mini":  (0.25, 2.00),
    "gpt-5":       (1.25, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o":      (2.50, 10.00),
}


def col_to_idx(col: str) -> int:
    idx = 0
    for ch in col.strip().upper():
        idx = idx * 26 + (ord(ch) - 64)
    return idx


def idx_to_col(idx: int) -> str:
    out = ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        out = chr(65 + rem) + out
    return out


def a1(tab, col, row):
    cell = f"{col}{row}"
    if not tab:
        return cell
    safe = re.fullmatch(r"[A-Za-z0-9_]+", tab)
    return (tab if safe else "'" + tab.replace("'", "''") + "'") + f"!{cell}"


def norm_url(u: str) -> str:
    x = (u or "").strip().lower()
    for p in ("https://", "http://"):
        if x.startswith(p):
            x = x[len(p):]
    if x.startswith("www."):
        x = x[4:]
    return x.rstrip("/")


def normalize_case(s: str) -> str:
    """Lowercase, but keep marketing acronyms uppercase — copy-ready."""
    s = (s or "").strip().lower()
    return re.sub(r"\b(seo|ppc|pr|ppc|roi|ux|ui|crm)\b", lambda m: m.group(1).upper(), s)


def spam_guidance() -> str:
    """Banned-word guidance injected into the prompt so outputs are cold-email safe."""
    if not spamguard:
        return ""
    words = ", ".join(spamguard.RULES["banned_words"])
    return ("\n\nDELIVERABILITY (must be cold-email safe): NEVER output any of these banned "
            "words or obvious variants: " + words + ". If the natural answer would be a banned "
            "word, name the concrete clean discipline instead (e.g. marketing→paid ads / SEO / "
            "social media, sales→revenue, performance→advertising). Do NOT use vague filler like "
            "'growth', 'solutions', or 'services'. Keep it within the length rules above.")


def spam_clean(v: str) -> str:
    """Deterministic safety net: strip/replace any banned token the model still emitted."""
    if not (spamguard and isinstance(v, str) and spamguard.word_hits(v)):
        return v
    low = v.strip().lower()
    if low in SPAM_SYNONYMS:
        return SPAM_SYNONYMS[low]
    toks = [SPAM_SYNONYMS.get(t, t) for t in low.split()
            if re.sub(r"[^a-z]", "", t) not in spamguard._BANNED]
    return normalize_case(" ".join(toks).strip() or "advertising")


def _get(sid, rng):
    return sheets._api("GET", f"{sheets.SHEETS}/{sid}/values/"
                       f"{urllib.parse.quote(rng)}").get("values", [])


def _put(sid, rng, values):
    sheets._api("PUT", f"{sheets.SHEETS}/{sid}/values/{urllib.parse.quote(rng)}"
                "?valueInputOption=RAW", {"values": values})


def _batch(sid, data):
    if data:
        sheets._api("POST", f"{sheets.SHEETS}/{sid}/values:batchUpdate",
                    {"valueInputOption": "RAW", "data": data})


def extract_one(content, schema, model, prompt, extra, retries=3):
    """Strict-JSON extraction that also returns token usage. (status, result, usage).

    Retries transient 429/5xx with backoff so concurrent runs don't mark a
    rate-limited row as a failure (which would trigger the low-confidence fallback)."""
    body = {
        "model": model,
        "messages": [{"role": "system", "content": prompt},
                     {"role": "user", "content": content}],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "personalize", "strict": True, "schema": schema}},
    }
    body.update(extra)
    for attempt in range(retries + 1):
        status, data = ai.call("/chat/completions", body=body)
        if status == 200:
            try:
                return status, json.loads(data["choices"][0]["message"]["content"]), data.get("usage", {})
            except Exception:
                return status, {"_error": "unparseable"}, data.get("usage", {})
        if status in (429, 500, 502, 503, 504) and attempt < retries:
            time.sleep(1.5 * (attempt + 1))
            continue
        return status, {"_error": data}, {}


def cost_of(model, pin, pout, prompt_tok, comp_tok):
    cin, cout = (pin, pout) if pin is not None else PRICES.get(model, (0.0, 0.0))
    return prompt_tok / 1e6 * cin + comp_tok / 1e6 * cout


def main():
    ap = argparse.ArgumentParser(description="GPT personalization over scraped data.")
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--tab", help="Source tab holding the scraped content.")
    ap.add_argument("--content-col", required=True, help="Column letter with the markdown/content.")
    ap.add_argument("--key-col", help="Column letter for the match key (e.g. Website) — needed for --map-*.")
    ap.add_argument("--start-row", type=int, default=2)
    ap.add_argument("--preset", help="Load presets/<name>.json (prompt + vars + model).")
    ap.add_argument("--prompt-file", help="Override the system prompt with this file's text.")
    ap.add_argument("--vars", help='Override vars JSON: [{"name","description","type","header"}]')
    ap.add_argument("--out-col", required=True, help="First column to write variables into (one col per var).")
    ap.add_argument("--model", help="Override the model (default from preset, else gpt-5-nano).")
    ap.add_argument("--reasoning-effort", help="For gpt-5* models: minimal|low|medium|high.")
    ap.add_argument("--max-chars", type=int, help="Truncate content fed to the model (default 3500).")
    ap.add_argument("--no-normalize", action="store_true", help="Skip case-normalizing string outputs.")
    ap.add_argument("--default", help="Value for rows with empty content (no API call). Default from preset.")
    ap.add_argument("--low-conf-fallback", help='Override low-confidence fallback: a literal value or "most_common".')
    ap.add_argument("--spamguard", action="store_true", help="Inject deliverability rules into the prompt + clean banned words from outputs.")
    ap.add_argument("--no-spamguard", action="store_true", help="Disable spamguard even if the preset enables it.")
    ap.add_argument("--no-retry", action="store_true", help="Don't auto-retry rows that hit an API error (default: retry them sequentially before any fallback).")
    ap.add_argument("--filter-col", help="Only process rows where this column equals --filter-value (e.g. reprocess just confidence=low rows).")
    ap.add_argument("--filter-value", help="Value --filter-col must equal (case-insensitive).")
    ap.add_argument("--test", type=int, default=15, help="Rows to process in TEST mode (default 15).")
    ap.add_argument("--run", action="store_true", help="Process the WHOLE sheet (not just --test).")
    ap.add_argument("--estimate", action="store_true", help="Print a no-API cost estimate and exit.")
    ap.add_argument("--flush-every", type=int, default=25)
    ap.add_argument("--concurrency", type=int, default=1,
                    help="Parallel API calls (default 1 = sequential). 8 is ~8x faster and still gentle.")
    ap.add_argument("--status-cell", help="Cell to write live progress/cost into (e.g. I1).")
    ap.add_argument("--price-in", type=float, help="Override input $/1M tokens.")
    ap.add_argument("--price-out", type=float, help="Override output $/1M tokens.")
    # map-back
    ap.add_argument("--map-tab")
    ap.add_argument("--map-key-col", help="Key column in the map tab (e.g. Website = H).")
    ap.add_argument("--map-out-col", help="Column in the map tab to write the variable into.")
    ap.add_argument("--map-var", help="Which variable to map back (default: first var).")
    args = ap.parse_args()

    # --- resolve config (preset < explicit flags) ---
    cfg = {}
    if args.preset:
        cfg = json.loads((_HERE / "presets" / f"{args.preset}.json").read_text())
    prompt = (Path(args.prompt_file).read_text() if args.prompt_file
              else cfg.get("prompt", "Extract the requested fields from the content."))
    vars_spec = json.loads(args.vars) if args.vars else cfg.get("vars", [])
    if not vars_spec:
        sys.exit("No vars — pass --vars or a --preset that defines them.")
    model = args.model or cfg.get("model", "gpt-5-nano")
    max_chars = args.max_chars or cfg.get("max_chars", 3500)
    normalize = (not args.no_normalize) and cfg.get("normalize_case", True)
    extra = {}
    eff = args.reasoning_effort or cfg.get("reasoning_effort")
    if eff and model.startswith("gpt-5"):
        extra["reasoning_effort"] = eff
    schema = ai._schema_from_vars(vars_spec)
    headers = [v.get("header", v["name"]) for v in vars_spec]
    names = [v["name"] for v in vars_spec]

    # low-confidence handling (preset-driven): the model self-reports confidence;
    # low-confidence / empty rows get a safe fallback instead of a confident guess.
    spam_on = (spamguard is not None) and (not args.no_spamguard) \
        and (args.spamguard or cfg.get("spamguard", False))
    if spam_on:
        prompt = prompt + spam_guidance()

    conf_var = cfg.get("confidence_var")                       # e.g. "confidence"
    low_vals = cfg.get("confidence_low_values", ["low"])
    fb_var = cfg.get("low_conf_fallback_var") or names[0]      # which var to overwrite
    fb_spec = args.low_conf_fallback or cfg.get("low_conf_fallback")  # literal | "most_common" | None
    generic_fb = cfg.get("generic_fallback", "marketing")

    sid = sheets._sheet_id(args.sheet)
    ccol = args.content_col.strip().upper()
    out0 = col_to_idx(args.out_col.strip().upper())

    # --- read source rows ---
    content_vals = _get(sid, a1(args.tab, ccol, args.start_row) + f":{ccol}")
    key_vals = _get(sid, a1(args.tab, args.key_col.strip().upper(), args.start_row)
                    + f":{args.key_col.strip().upper()}") if args.key_col else []
    empty_default = args.default if args.default is not None else cfg.get("empty_default")
    # optional filter: only reprocess rows whose --filter-col equals --filter-value
    filt_vals = []
    if args.filter_col:
        fc = args.filter_col.strip().upper()
        filt_vals = _get(sid, a1(args.tab, fc, args.start_row) + f":{fc}")
    fval = (args.filter_value or "").strip().lower()
    # include empty-content rows when we have any way to fill them (a default,
    # or the low-confidence fallback) so the sheet ends up complete.
    include_empty = (empty_default is not None) or bool(conf_var and fb_spec)
    jobs = []  # (row_no, key, content)  — content None means "empty source, no API call"
    span = max(len(content_vals), len(key_vals))
    for i in range(span):
        if args.filter_col:
            cell_v = (filt_vals[i][0].strip().lower() if i < len(filt_vals) and filt_vals[i] else "")
            if cell_v != fval:
                continue
        c = content_vals[i][0] if (i < len(content_vals) and content_vals[i]) else ""
        key = key_vals[i][0] if (i < len(key_vals) and key_vals[i]) else ""
        if c and c.strip():
            jobs.append((args.start_row + i, key, c[:max_chars]))
        elif key and key.strip() and include_empty:
            jobs.append((args.start_row + i, key, None))
    if not jobs:
        sys.exit("No content rows found — check --tab / --content-col / --start-row.")

    pin, pout = args.price_in, args.price_out
    disp_in, disp_out = (pin if pin is not None else PRICES.get(model, (0, 0))[0],
                         pout if pout is not None else PRICES.get(model, (0, 0))[1])

    # --- ESTIMATE (no API) ---
    if args.estimate:
        approx_in = sum((len(prompt) + len(c)) for _, _, c in jobs if c) / 4
        approx_out = len(jobs) * 12
        est = cost_of(model, pin, pout, approx_in, approx_out)
        print(json.dumps({"mode": "estimate", "rows": len(jobs), "model": model,
                          "price_per_1M": [disp_in, disp_out],
                          "est_input_tokens": int(approx_in),
                          "est_cost_usd": round(est, 4)}, indent=2))
        return

    n = len(jobs) if args.run else min(args.test, len(jobs))
    todo = jobs[:n]
    mode = "RUN (full sheet)" if args.run else f"TEST (first {n})"
    print(f"{mode}: {n} rows · model={model}{' · '+str(extra) if extra else ''}")

    results = {}      # key -> {var: value}
    rows_data = []    # [{row, key, **vars}] — kept so we can apply the fallback pass
    row_index = {}    # row_no -> index in rows_data
    failed = []       # row_nos that hit an API error (retried before any fallback)
    pt = ct = done = 0
    fail = spam_cleaned = recovered = 0
    pending = []
    start = time.time()
    job_by_row = {j[0]: j for j in todo}

    def scrub(row_res):
        nonlocal spam_cleaned
        if not spam_on:
            return
        for nm in names:
            if nm == conf_var:
                continue
            cleaned = spam_clean(row_res.get(nm))
            if cleaned != row_res.get(nm):
                row_res[nm] = cleaned
                spam_cleaned += 1

    def flush():
        nonlocal pending
        _batch(sid, pending)
        pending = []

    def work(job):
        """Render one row → (row_no, key, row_res, prompt_tok, comp_tok, ok). Thread-safe."""
        row_no, key, content = job
        if content is None:                       # empty source → mark low, no API call
            rr = {nm: "" for nm in names}
            if conf_var:
                rr[conf_var] = low_vals[0]
            return row_no, key, rr, 0, 0, True
        status, res, usage = extract_one(content, schema, model, prompt, extra)
        ok = "_error" not in res
        rr = {}
        for nm in names:
            v = res.get(nm, "") if ok else ""
            if normalize and isinstance(v, str):
                v = normalize_case(v)
            rr[nm] = v
        if not ok and conf_var:                   # API failure → treat as low confidence
            rr[conf_var] = low_vals[0]
        return (row_no, key, rr, usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0), ok)

    def absorb(row_no, key, row_res, p, c, ok):
        nonlocal pt, ct, done, fail
        pt += p
        ct += c
        done += 1
        if not ok:
            fail += 1
            failed.append(row_no)
        scrub(row_res)                            # safety net: scrub any banned word
        vals = [row_res[nm] for nm in names]
        row_index[row_no] = len(rows_data)
        rows_data.append({"row": row_no, "key": key, **row_res})
        if key:
            results[norm_url(key)] = dict(row_res)
        for j, v in enumerate(vals):
            pending.append({"range": a1(args.tab, idx_to_col(out0 + j), row_no),
                            "values": [[v]]})
        if not args.run and n <= 30:
            print(f"  row {row_no}: {key or ''} -> {dict(zip(headers, vals))}")
        if len(pending) >= args.flush_every:
            flush()
            if args.status_cell:
                cost = cost_of(model, pin, pout, pt, ct)
                _put(sid, a1(args.tab, *re.match(r"([A-Za-z]+)(\d+)", args.status_cell).groups()),
                     [[f"{done}/{n} · ${cost:.4f} · {done/max(1,time.time()-start)*60:.0f}/min"]])

    conc = max(1, args.concurrency)
    if conc == 1:
        for job in todo:
            absorb(*work(job))
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=conc) as ex:
            for fut in as_completed([ex.submit(work, j) for j in todo]):
                absorb(*fut.result())

    flush()

    # --- auto-retry rows that hit an API error (sequential + gentle) so a rate-limit
    #     blip never silently becomes the fallback. Runs BEFORE the fallback pass. ---
    if failed and not args.no_retry:
        print(f"retrying {len(failed)} failed row(s) sequentially...", file=sys.stderr)
        retry_fix = []
        for rn in list(failed):
            job = job_by_row.get(rn)
            if not job:
                continue
            rno, key, rr, p, c, ok = work(job)
            pt += p
            ct += c
            if ok:
                recovered += 1
                fail -= 1
            scrub(rr)
            rows_data[row_index[rno]] = {"row": rno, "key": key, **rr}
            if key:
                results[norm_url(key)] = dict(rr)
            for j, v in enumerate([rr[nm] for nm in names]):
                retry_fix.append({"range": a1(args.tab, idx_to_col(out0 + j), rno),
                                  "values": [[v]]})
        _batch(sid, retry_fix)

    # --- low-confidence fallback pass: replace unsure/empty guesses with a safe value ---
    low_n = 0
    fb_value = None
    if conf_var and fb_spec:
        from collections import Counter
        highs = [r[fb_var] for r in rows_data
                 if r.get(conf_var) not in low_vals and r.get(fb_var)]
        if fb_spec == "most_common":
            fb_value = Counter(highs).most_common(1)[0][0] if highs else generic_fb
        else:
            fb_value = fb_spec
        if spam_on:                               # the fallback itself must be clean
            fb_value = spam_clean(fb_value)
        fix = []
        for r in rows_data:
            if r.get(conf_var) in low_vals:
                low_n += 1
                if r.get(fb_var) != fb_value:
                    r[fb_var] = fb_value
                    fix.append({"range": a1(args.tab, idx_to_col(out0 + names.index(fb_var)),
                                            r["row"]), "values": [[fb_value]]})
                    if r["key"]:
                        results[norm_url(r["key"])][fb_var] = fb_value
        _batch(sid, fix)
    # write headers above the out-cols (if there's a header row)
    if args.start_row > 1:
        _batch(sid, [{"range": a1(args.tab, idx_to_col(out0 + j), args.start_row - 1),
                      "values": [[headers[j]]]} for j in range(len(headers))])

    actual = cost_of(model, pin, pout, pt, ct)
    summary = {"mode": mode, "rows": done, "failed": fail, "model": model,
               "prompt_tokens": pt, "completion_tokens": ct,
               "cost_usd": round(actual, 4), "price_per_1M": [disp_in, disp_out]}
    if failed:
        summary["api_failures"] = len(failed)
        summary["recovered_on_retry"] = recovered
    if spam_on:
        summary["spamguard"] = True
        summary["spam_cleaned"] = spam_cleaned
    if conf_var and fb_spec:
        summary["low_confidence_rows"] = low_n
        summary["low_conf_fallback"] = fb_value
        summary["confident_rows"] = done - low_n

    # TEST → extrapolate the full-sheet cost
    if not args.run:
        per_row = actual / max(1, done)
        summary["full_sheet_rows"] = len(jobs)
        summary["full_sheet_est_cost_usd"] = round(per_row * len(jobs), 4)
        summary["next"] = "re-run with --run to process the whole sheet"

    # map-back (full run)
    if args.run and args.map_tab and args.map_key_col and args.map_out_col:
        mvar = args.map_var or names[0]
        mkey = args.map_key_col.strip().upper()
        mout = args.map_out_col.strip().upper()
        keycol = _get(sid, a1(args.map_tab, mkey, args.start_row) + f":{mkey}")
        upd = []
        for i, row in enumerate(keycol):
            k = norm_url(row[0]) if row else ""
            if k and k in results:
                upd.append({"range": a1(args.map_tab, mout, args.start_row + i),
                            "values": [[results[k].get(mvar, "")]]})
        # header for the mapped column
        if args.start_row > 1:
            upd.append({"range": a1(args.map_tab, mout, args.start_row - 1),
                        "values": [[next((v.get("header", v["name"]) for v in vars_spec
                                          if v["name"] == mvar), mvar)]]})
        _batch(sid, upd)
        summary["mapped_back"] = {"tab": args.map_tab, "col": mout,
                                  "var": mvar, "rows": len(upd)}

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
