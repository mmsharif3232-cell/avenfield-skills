#!/usr/bin/env python3
"""Avenfield browser-render — dedupe a URL column → sidecar tab → map a field back.

The full lead-list workflow Momin runs: take a sheet's Website column, render the
UNIQUE sites once each (in parallel), drop everything into a sidecar tab
(Website + ok + status + char_count + scrape_error + the rendered field), then
map just the rendered field back onto every matching row of the source tab.

Builds on the two skills it sits next to:
  • cf_render.py        (same dir)              — Cloudflare rendering + retries
  • avenfield-sheets/sheets.py (sibling skill)  — Sheets auth + read/write

USAGE
  C=~/.claude/skills/avenfield-browser-render/render_column.py

  # Render unique Websites (col H, header row 1) into a 'browser render' tab,
  # then map the markdown back into main col K — live, with row heights reset:
  python3 $C --sheet "<URL or ID>" --tab Goodfirms-verified --url-col H \
      --start-row 2 --sidecar-tab "browser render" --map-col K \
      --live --reset-row-height

  # Just build the sidecar tab, no map-back:
  python3 $C --sheet <ID> --tab Leads --url-col C --sidecar-tab scraped

  # Preview the unique count + first rows without spending renders:
  python3 $C --sheet <ID> --tab Leads --url-col C --dry-run

Notes
  • Dedupe normalizes scheme + www + trailing slash; the first original spelling
    is kept. Use --no-dedupe to render every row as-is.
  • --map-col writes the rendered field onto ROWS THAT HAVE A URL only; blank-URL
    rows are left untouched. Point it at a column you're happy to overwrite.
  • --reset-row-height collapses the source + sidecar tabs back to 21px (big
    markdown cells otherwise balloon the rows).
  • Cost ≈ $0.005/page on Cloudflare. Failures get a [render failed ...] marker.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import cf_render  # noqa: E402
from render_sheet import a1, col_to_idx, idx_to_col  # noqa: E402

_SHEETS_DIR = _HERE.parent / "avenfield-sheets"
if not (_SHEETS_DIR / "sheets.py").exists():
    _SHEETS_DIR = Path.home() / ".claude" / "skills" / "avenfield-sheets"
sys.path.insert(0, str(_SHEETS_DIR))
import sheets  # noqa: E402

HEADER = ["Website", "ok", "status", "char_count", "scrape_error", "result"]


def norm(u: str) -> str:
    x = (u or "").strip().lower()
    for p in ("https://", "http://"):
        if x.startswith(p):
            x = x[len(p):]
    if x.startswith("www."):
        x = x[4:]
    return x.rstrip("/")


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


def _ensure_tab(sid, title):
    meta = sheets._api("GET", f"{sheets.SHEETS}/{sid}?fields=sheets.properties")
    if not any(s["properties"]["title"] == title for s in meta.get("sheets", [])):
        sheets._api("POST", f"{sheets.SHEETS}/{sid}:batchUpdate",
                    {"requests": [{"addSheet": {"properties": {"title": title}}}]})


def _tidy(sid, title, px=21, clip=True):
    """Reset rows to default height and (optionally) set CLIP so big markdown
    cells stay inside their own cell instead of overflowing / ballooning rows."""
    meta = sheets._api("GET", f"{sheets.SHEETS}/{sid}?fields=sheets.properties")
    prop = next((s["properties"] for s in meta.get("sheets", [])
                 if s["properties"]["title"] == title), None)
    if not prop:
        return
    sheet_id = prop["sheetId"]
    nrows = prop.get("gridProperties", {}).get("rowCount", 1000)
    reqs = [{"updateDimensionProperties": {
        "range": {"sheetId": sheet_id, "dimension": "ROWS",
                  "startIndex": 0, "endIndex": nrows},
        "properties": {"pixelSize": px}, "fields": "pixelSize"}}]
    if clip:
        reqs.append({"repeatCell": {
            "range": {"sheetId": sheet_id},
            "cell": {"userEnteredFormat": {"wrapStrategy": "CLIP"}},
            "fields": "userEnteredFormat.wrapStrategy"}})
    sheets._api("POST", f"{sheets.SHEETS}/{sid}:batchUpdate", {"requests": reqs})


def main():
    ap = argparse.ArgumentParser(
        description="Dedupe a URL column, render uniques, build a sidecar tab, map a field back.")
    ap.add_argument("--sheet", required=True)
    ap.add_argument("--tab", help="Source tab with the URLs (default: first tab).")
    ap.add_argument("--url-col", required=True, help="Column letter holding the URLs.")
    ap.add_argument("--start-row", type=int, default=2, help="First data row (default 2).")
    ap.add_argument("--sidecar-tab", default="browser render", help="Tab to write results into.")
    ap.add_argument("--map-col", help="Column letter in the SOURCE tab to write the rendered field back to.")
    ap.add_argument("--endpoint", default="markdown",
                    choices=sorted(cf_render.ALL_ENDPOINTS - cf_render.BINARY_ENDPOINTS))
    ap.add_argument("--body", default="{}")
    ap.add_argument("--no-dedupe", action="store_true", help="Render every row, not just uniques.")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--max-chars", type=int, default=45000)
    ap.add_argument("--live", action="store_true", help="Stream rows + a status ticker into the sidecar as they finish.")
    ap.add_argument("--flush-every", type=int, default=25)
    ap.add_argument("--reset-row-height", action="store_true",
                    help="When done, tidy source + sidecar tabs: rows → 21px and wrap → CLIP (no overflow).")
    ap.add_argument("--no-clip", action="store_true",
                    help="With --reset-row-height, skip the CLIP wrap (only reset row height).")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        base_body = json.loads(args.body)
    except json.JSONDecodeError as e:
        sys.exit(f"--body is not valid JSON: {e}")

    sid = sheets._sheet_id(args.sheet)
    url_col = args.url_col.strip().upper()

    # 1. read + dedupe the URL column
    col_vals = _get(sid, a1(args.tab, url_col, args.start_row) + f":{url_col}")
    seen = {}
    for row in col_vals:
        u = row[0].strip() if (row and row[0]) else ""
        if not u:
            continue
        key = u if args.no_dedupe else norm(u)
        if key and key not in seen:
            seen[key] = u
    uniq = list(seen.values())
    if not uniq:
        sys.exit("No URLs found — check --tab / --url-col / --start-row.")
    print(f"{len(col_vals)} cells → {len(uniq)} {'rows' if args.no_dedupe else 'unique URLs'}")

    if args.dry_run:
        print(json.dumps({"unique": len(uniq), "sample": uniq[:5]}, indent=2))
        return

    # 2. render uniques in parallel
    def one(site):
        ok, status, res = cf_render.render_text(
            args.endpoint, {**base_body, "url": site}, args.timeout)
        if len(res) > args.max_chars:
            res = res[:args.max_chars] + "\n…[truncated]"
        return site, ok, status, res

    _ensure_tab(sid, args.sidecar_tab)
    _put(sid, f"'{args.sidecar_tab}'!A1", [HEADER])
    row_of = {s: i + 2 for i, s in enumerate(uniq)}  # sidecar row per site
    results = {}
    done = ok_n = 0
    start = time.time()
    pending = []

    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as ex:
        for site, ok, status, res in (f.result() for f in
                                      as_completed([ex.submit(one, s) for s in uniq])):
            results[site] = res if ok else ""
            done += 1
            ok_n += 1 if ok else 0
            r = row_of[site]
            pending.append({"range": f"'{args.sidecar_tab}'!A{r}:F{r}",
                            "values": [[site, "TRUE" if ok else "FALSE", status,
                                        len(res) if ok else 0,
                                        "" if ok else res, res if ok else ""]]})
            if args.live and len(pending) >= max(1, args.flush_every):
                _batch(sid, pending)
                pending = []
                rate = done / max(1, time.time() - start) * 60
                _put(sid, f"'{args.sidecar_tab}'!H1",
                     [[f"{done}/{len(uniq)} done · ok={ok_n} · {rate:.0f}/min"]])
    _batch(sid, pending)
    print(f"sidecar '{args.sidecar_tab}': {ok_n} ok / {len(uniq)-ok_n} failed")

    # 3. map the rendered field back onto the source tab
    if args.map_col:
        mc = args.map_col.strip().upper()
        keymap = {(s if args.no_dedupe else norm(s)): results[s] for s in uniq}
        src = _get(sid, a1(args.tab, url_col, args.start_row) + f":{url_col}")
        updates = []
        for i, row in enumerate(src):
            u = row[0].strip() if (row and row[0]) else ""
            if not u:
                continue
            k = u if args.no_dedupe else norm(u)
            if k in keymap:
                updates.append({"range": a1(args.tab, mc, args.start_row + i),
                                "values": [[keymap[k]]]})
        _batch(sid, updates)
        print(f"mapped '{args.endpoint}' into {args.tab or '(first)'}!{mc} ({len(updates)} rows)")

    # 4. tidy: default row height + CLIP wrap (so big cells don't overflow/balloon)
    if args.reset_row_height:
        clip = not args.no_clip
        _tidy(sid, args.sidecar_tab, clip=clip)
        if args.tab:
            _tidy(sid, args.tab, clip=clip)
        print(f"tidied: rows→21px{' + wrap→CLIP' if clip else ''}")


if __name__ == "__main__":
    main()
