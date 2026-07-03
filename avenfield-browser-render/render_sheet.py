#!/usr/bin/env python3
"""Avenfield browser-render — Sheet → render → next column, in parallel.

The fast path for Momin's usual ask: "here's a sheet of URLs, render them and
put the markdown in the next column." Reads a URL column, renders every URL
through Cloudflare Browser Rendering CONCURRENTLY (not one-by-one), and writes
each result back to an output column in a single Sheets write.

Reuses the two existing skills:
  • cf_render.py        (same dir)              — Cloudflare rendering + retries
  • avenfield-sheets/sheets.py (sibling skill)  — Sheets auth + read/write

USAGE
  R=~/.claude/skills/avenfield-browser-render/render_sheet.py

  # Simplest: URLs in column A (row 1 is a header), markdown into column B
  python3 $R --sheet "<sheet URL or ID>" --url-col A --start-row 2

  # Pick the tab, the output column, the endpoint, and parallelism
  python3 $R --sheet <ID> --tab Leads --url-col C --out-col D \
      --endpoint markdown --concurrency 8 --start-row 2 --out-header "Markdown"

  # Structured JSON extraction instead of markdown (CF runs the LLM server-side)
  python3 $R --sheet <ID> --url-col A --start-row 2 --endpoint json \
      --body '{"prompt":"founder, city, one-line value prop",
               "response_format":{"type":"json_schema","json_schema":{"type":"object",
               "properties":{"founder":{"type":"string"},"city":{"type":"string"},
               "value_prop":{"type":"string"}}}}}'

  # See exactly what WOULD be written, without touching the sheet
  python3 $R --sheet <ID> --url-col A --start-row 2 --dry-run

Notes
  • --out-col defaults to the column immediately to the right of --url-col.
  • Row 1 is usually a header → use --start-row 2 (default is 1).
  • Google caps a cell at 50,000 chars; results are truncated to --max-chars
    (default 45000) with a "…[truncated]" marker.
  • Writes are surgical (per-cell batch) — only the output column cells we
    computed are touched, so nothing else in the sheet is clobbered.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# --- import the two sibling capabilities ---------------------------------
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import cf_render  # noqa: E402

_SHEETS_DIR = _HERE.parent / "avenfield-sheets"
if not (_SHEETS_DIR / "sheets.py").exists():
    _SHEETS_DIR = Path.home() / ".claude" / "skills" / "avenfield-sheets"
sys.path.insert(0, str(_SHEETS_DIR))
import sheets  # noqa: E402


def col_to_idx(col: str) -> int:
    """'A' -> 1, 'Z' -> 26, 'AA' -> 27."""
    idx = 0
    for ch in col.strip().upper():
        if not ("A" <= ch <= "Z"):
            sys.exit(f"Bad column letter: {col!r}")
        idx = idx * 26 + (ord(ch) - 64)
    if idx == 0:
        sys.exit(f"Bad column letter: {col!r}")
    return idx


def idx_to_col(idx: int) -> str:
    out = ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        out = chr(65 + rem) + out
    return out


def a1(tab: str | None, col: str, row: int) -> str:
    """Build an A1 range, quoting the tab name when it needs it."""
    cell = f"{col}{row}"
    if not tab:
        return cell
    safe = re.fullmatch(r"[A-Za-z0-9_]+", tab)
    tab_ref = tab if safe else "'" + tab.replace("'", "''") + "'"
    return f"{tab_ref}!{cell}"


def main():
    ap = argparse.ArgumentParser(
        description="Render a sheet's URL column and write results to the next column.")
    ap.add_argument("--sheet", required=True, help="Spreadsheet URL or ID.")
    ap.add_argument("--tab", help="Tab/worksheet name (default: first tab).")
    ap.add_argument("--url-col", required=True, help="Column letter holding the URLs (e.g. A).")
    ap.add_argument("--out-col", help="Column to write into (default: column right of --url-col).")
    ap.add_argument("--start-row", type=int, default=1,
                    help="First data row (use 2 if row 1 is a header). Default 1.")
    ap.add_argument("--endpoint", default="markdown",
                    choices=sorted(cf_render.ALL_ENDPOINTS - cf_render.BINARY_ENDPOINTS),
                    help="Cloudflare endpoint (default markdown).")
    ap.add_argument("--body", default="{}", help="Extra Cloudflare options as JSON (merged per URL).")
    ap.add_argument("--concurrency", type=int, default=8, help="Parallel renders (default 8).")
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--max-chars", type=int, default=45000, help="Truncate each cell to N chars.")
    ap.add_argument("--out-header", help="Write this header above the output column (needs --start-row > 1).")
    ap.add_argument("--dry-run", action="store_true", help="Render but DON'T write; print a preview.")
    ap.add_argument("--live", action="store_true",
                    help="Flush results to the sheet as they complete (watch it fill row-by-row).")
    ap.add_argument("--flush-every", type=int, default=25,
                    help="In --live mode, push to the sheet every N completed renders (default 25).")
    ap.add_argument("--status-cell",
                    help="In --live mode, write progress/rate to this cell (e.g. H1) in the same tab.")
    args = ap.parse_args()

    try:
        base_body = json.loads(args.body)
    except json.JSONDecodeError as e:
        sys.exit(f"--body is not valid JSON: {e}")

    url_col = args.url_col.strip().upper()
    out_col = (args.out_col or idx_to_col(col_to_idx(url_col) + 1)).strip().upper()
    sid = sheets._sheet_id(args.sheet)

    # 1. read the URL column from start_row down  (e.g. "Leads!A2:A")
    import urllib.parse
    rng = a1(args.tab, url_col, args.start_row) + f":{url_col}"
    data = sheets._api("GET", f"{sheets.SHEETS}/{sid}/values/{urllib.parse.quote(rng)}")
    rows = data.get("values", [])

    jobs = []  # (row_number, url)
    for i, row in enumerate(rows):
        url = (row[0].strip() if row and row[0] else "")
        if url:
            jobs.append((args.start_row + i, url))

    if not jobs:
        sys.exit(f"No URLs found in {rng}. Check --tab / --url-col / --start-row.")

    # 2. render all URLs in parallel (order preserved)
    def render_job(job):
        row_no, url = job
        ok, status, res = cf_render.render_text(
            args.endpoint, {**base_body, "url": url}, args.timeout)
        if len(res) > args.max_chars:
            res = res[:args.max_chars] + "\n…[truncated]"
        return row_no, url, ok, status, res

    # --- LIVE mode: stream results into the sheet as they finish ---------
    if args.live and not args.dry_run:
        import time
        from concurrent.futures import as_completed

        def push(cells):
            if cells:
                sheets._api("POST", f"{sheets.SHEETS}/{sid}/values:batchUpdate",
                            {"valueInputOption": "RAW", "data": cells})

        if args.out_header and args.start_row > 1:
            push([{"range": a1(args.tab, out_col, args.start_row - 1),
                   "values": [[args.out_header]]}])

        pending, done, ok_n, start = [], 0, 0, time.time()
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as ex:
            for fut in as_completed([ex.submit(render_job, j) for j in jobs]):
                row_no, url, ok, status, res = fut.result()
                ok_n += 1 if ok else 0
                done += 1
                pending.append({"range": a1(args.tab, out_col, row_no), "values": [[res]]})
                if len(pending) >= max(1, args.flush_every):
                    push(pending)
                    pending = []
                    if args.status_cell:
                        rate = done / max(1, time.time() - start) * 60
                        push([{"range": a1(args.tab, args.status_cell.rstrip("0123456789"),
                                           int("".join(filter(str.isdigit, args.status_cell)))),
                               "values": [[f"{done}/{len(jobs)} done · ok={ok_n} · "
                                           f"{rate:.0f}/min"]]}])
            push(pending)
        summary = {"sheet": sid, "tab": args.tab or "(first)", "url_col": url_col,
                   "out_col": out_col, "rendered": done, "ok": ok_n,
                   "failed": done - ok_n, "endpoint": args.endpoint, "live": True}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as ex:
        for row_no, url, ok, status, res in ex.map(render_job, jobs):
            results.append((row_no, url, ok, status, res))

    ok_n = sum(1 for r in results if r[2])
    fail_n = len(results) - ok_n

    # 3. write back — surgical per-cell batch into the output column
    batch = []
    if args.out_header and args.start_row > 1:
        batch.append({"range": a1(args.tab, out_col, args.start_row - 1),
                      "values": [[args.out_header]]})
    for row_no, _url, _ok, _status, res in results:
        batch.append({"range": a1(args.tab, out_col, row_no), "values": [[res]]})

    summary = {
        "sheet": sid, "tab": args.tab or "(first)",
        "url_col": url_col, "out_col": out_col,
        "rendered": len(results), "ok": ok_n, "failed": fail_n,
        "endpoint": args.endpoint,
    }

    if args.dry_run:
        summary["dry_run"] = True
        summary["preview"] = [
            {"row": r[0], "url": r[1], "ok": r[2], "status": r[3],
             "result_head": (r[4][:200] + "…") if len(r[4]) > 200 else r[4]}
            for r in results[:5]
        ]
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    sheets._api("POST", f"{sheets.SHEETS}/{sid}/values:batchUpdate",
                {"valueInputOption": "RAW", "data": batch})
    summary["wrote_cells"] = len(batch)
    if fail_n:
        summary["failed_rows"] = [{"row": r[0], "url": r[1], "status": r[3]}
                                  for r in results if not r[2]]
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
