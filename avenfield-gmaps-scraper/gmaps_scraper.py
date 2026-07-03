#!/usr/bin/env python3
"""Avenfield gmaps-scraper — Google Maps lead scraping via a RapidAPI scraper.

Calls a Google Maps scraper hosted on RapidAPI (default: letscrape's
"Local Business Data", host local-business-data.p.rapidapi.com) and turns the
results into normalized lead rows, optionally appended straight into a Google
Sheet tab (service-account auth reused from avenfield-sheets). Idempotent:
rows are deduped on place_id against what's already in the tab.

Key (`RAPIDAPI_KEY`, optional `RAPIDAPI_HOST`) loads from
~/.avenfield/credentials.env.

USAGE
  python gmaps_scraper.py test --query "plumbers in Dallas, TX"
  python gmaps_scraper.py estimate --queries-file queries.txt --limit 20
  python gmaps_scraper.py search --query "roofers in Austin, TX" --limit 20
  python gmaps_scraper.py search --queries-file queries.txt --limit 20 \
      --sheet <URL|ID> --tab leads
  python gmaps_scraper.py raw --path business-details --param business_id=0x89c25...

Notes
  • --query is repeatable; --queries-file is one query per line (# comments ok).
  • Sheet write creates the tab (with header) if it doesn't exist.
  • Any listing-specific extra params: --param key=value (repeatable).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Reuse the service-account Sheets plumbing from the sibling skill.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "avenfield-sheets"))
try:
    from sheets import _api as sheets_api, _sheet_id, SHEETS as SHEETS_URL, _load_env_file
except ImportError:
    sheets_api = None
    def _load_env_file(path: Path) -> dict:
        out = {}
        try:
            for line in path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip().strip('"').strip("'")
        except FileNotFoundError:
            pass
        return out

DEFAULT_HOST = "local-business-data.p.rapidapi.com"
DEFAULT_ENDPOINT = "search"

COLUMNS = ["query", "name", "category", "full_address", "city", "state", "zip",
           "country", "phone", "website", "email", "rating", "review_count",
           "place_id", "google_id", "lat", "lng", "business_status", "verified"]


def _creds() -> tuple[str, str]:
    env = _load_env_file(Path.home() / ".avenfield" / "credentials.env")
    key = os.environ.get("RAPIDAPI_KEY") or env.get("RAPIDAPI_KEY")
    host = os.environ.get("RAPIDAPI_HOST") or env.get("RAPIDAPI_HOST") or DEFAULT_HOST
    if not key:
        sys.exit("Missing RAPIDAPI_KEY in ~/.avenfield/credentials.env.")
    return key, host


def _call(path: str, params: dict, host_override: str | None = None) -> dict:
    key, host = _creds()
    host = host_override or host
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")})
    url = f"https://{host}/{path.lstrip('/')}" + (f"?{qs}" if qs else "")
    req = urllib.request.Request(url)
    req.add_header("x-rapidapi-key", key)
    req.add_header("x-rapidapi-host", host)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:300]
            if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                wait = 2 ** (attempt + 1)
                print(f"  {e.code} on {path}, retrying in {wait}s…", file=sys.stderr)
                time.sleep(wait)
                continue
            if e.code == 403:
                sys.exit(f"403 from RapidAPI — key invalid or not subscribed to {host}: {body}")
            sys.exit(f"RapidAPI {e.code} on {path}: {body}")
        except urllib.error.URLError as e:
            if attempt < 4:
                time.sleep(2 ** (attempt + 1))
                continue
            sys.exit(f"Network error calling {host}: {e}")
    return {}


def _first(item: dict, *keys, default=""):
    for k in keys:
        v = item.get(k)
        if v not in (None, "", []):
            return v
    return default


def _normalize(item: dict, query: str) -> dict:
    cat = _first(item, "type", "category")
    if not cat:
        types = item.get("types") or item.get("subtypes") or []
        cat = types[0] if isinstance(types, list) and types else ""
    email = _first(item, "email")
    if not email:
        ec = item.get("emails_and_contacts") or {}
        emails = ec.get("emails") if isinstance(ec, dict) else None
        email = emails[0] if emails else ""
    return {
        "query": query,
        "name": _first(item, "name", "title", "business_name"),
        "category": cat,
        "full_address": _first(item, "full_address", "address", "formatted_address"),
        "city": _first(item, "city"),
        "state": _first(item, "state", "region"),
        "zip": _first(item, "zipcode", "zip", "postal_code"),
        "country": _first(item, "country", "country_code"),
        "phone": _first(item, "phone_number", "phone", "international_phone_number"),
        "website": _first(item, "website", "url", "site"),
        "email": email,
        "rating": _first(item, "rating"),
        "review_count": _first(item, "review_count", "reviews", "user_ratings_total"),
        "place_id": _first(item, "place_id", "business_id", "cid"),
        "google_id": _first(item, "google_id"),
        "lat": _first(item, "latitude", "lat"),
        "lng": _first(item, "longitude", "lng", "lon"),
        "business_status": _first(item, "business_status"),
        "verified": _first(item, "verified", "is_claimed"),
    }


def _extract_items(resp: dict) -> list[dict]:
    if isinstance(resp, list):
        return resp
    for k in ("data", "results", "businesses", "items", "places"):
        v = resp.get(k)
        if isinstance(v, list):
            return v
        if isinstance(v, dict):  # some listings nest one level deeper
            for kk in ("results", "businesses", "items"):
                if isinstance(v.get(kk), list):
                    return v[kk]
    return []


def _load_queries(args) -> list[str]:
    queries = list(args.query or [])
    if args.queries_file:
        for line in Path(args.queries_file).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                queries.append(line)
    if not queries:
        sys.exit("No queries — pass --query (repeatable) or --queries-file.")
    return queries


def _run_queries(args, queries: list[str]) -> list[dict]:
    rows, seen = [], set()
    params_extra = dict(p.split("=", 1) for p in (args.param or []))
    for i, q in enumerate(queries, 1):
        params = {"query": q, "limit": args.limit,
                  "region": args.region, "language": args.lang, **params_extra}
        resp = _call(args.endpoint, params, args.host)
        items = _extract_items(resp)
        fresh = 0
        for item in items:
            row = _normalize(item, q)
            pid = row["place_id"] or (row["name"], row["full_address"])
            if pid in seen:
                continue
            seen.add(pid)
            rows.append(row)
            fresh += 1
        print(f"[{i}/{len(queries)}] {q!r}: {len(items)} results, {fresh} new",
              file=sys.stderr)
    return rows


# ── Sheet write-back (idempotent on place_id) ─────────────────────────

def _append_to_sheet(rows: list[dict], sheet: str, tab: str) -> dict:
    if sheets_api is None:
        sys.exit("avenfield-sheets not found next to this skill — needed for --sheet.")
    sid = _sheet_id(sheet)
    meta = sheets_api("GET", f"{SHEETS_URL}/{sid}?fields=sheets.properties")
    titles = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if tab not in titles:
        sheets_api("POST", f"{SHEETS_URL}/{sid}:batchUpdate",
                   {"requests": [{"addSheet": {"properties": {"title": tab}}}]})
        existing_ids, header_needed = set(), True
    else:
        rng = urllib.parse.quote(f"{tab}!A1:S")
        data = sheets_api("GET", f"{SHEETS_URL}/{sid}/values/{rng}")
        values = data.get("values", [])
        header_needed = not values
        pid_col = COLUMNS.index("place_id")
        if values and values[0] and values[0][0] == COLUMNS[0]:
            try:
                pid_col = values[0].index("place_id")
            except ValueError:
                pass
        existing_ids = {r[pid_col] for r in values[1:] if len(r) > pid_col and r[pid_col]}
    new = [r for r in rows if str(r["place_id"]) not in existing_ids]
    payload = ([COLUMNS] if header_needed else []) + \
              [[str(r[c]) for c in COLUMNS] for r in new]
    if payload:
        rng = urllib.parse.quote(f"{tab}!A1")
        sheets_api("POST",
                   f"{SHEETS_URL}/{sid}/values/{rng}:append"
                   "?valueInputOption=RAW&insertDataOption=INSERT_ROWS",
                   {"values": payload})
    return {"scraped": len(rows), "already_in_sheet": len(rows) - len(new),
            "appended": len(new), "tab": tab}


# ── Commands ──────────────────────────────────────────────────────────

def cmd_search(args):
    queries = _load_queries(args)
    rows = _run_queries(args, queries)
    if args.sheet:
        result = _append_to_sheet(rows, args.sheet, args.tab)
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps({"rows": rows, "count": len(rows)}, ensure_ascii=False, indent=2))


def cmd_test(args):
    args.limit = min(args.limit, 3)
    args.sheet = None
    rows = _run_queries(args, _load_queries(args))
    print(json.dumps({"rows": rows, "count": len(rows),
                      "note": "test mode — nothing written"}, ensure_ascii=False, indent=2))


def cmd_estimate(args):
    queries = _load_queries(args)
    print(json.dumps({"queries": len(queries), "api_calls": len(queries),
                      "max_rows": len(queries) * args.limit,
                      "note": "1 API call per query against your RapidAPI quota"}, indent=2))


def cmd_raw(args):
    params = dict(p.split("=", 1) for p in (args.param or []))
    print(json.dumps(_call(args.path, params, args.host), ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description="Google Maps leads via a RapidAPI scraper.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--query", action="append", help="Search query, repeatable — e.g. 'plumbers in Dallas, TX'.")
        p.add_argument("--queries-file", help="File with one query per line.")
        p.add_argument("--limit", type=int, default=20, help="Max results per query (default 20).")
        p.add_argument("--region", default="us")
        p.add_argument("--lang", default="en")
        p.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help=f"API path (default '{DEFAULT_ENDPOINT}').")
        p.add_argument("--host", help="Override RAPIDAPI_HOST for a different listing.")
        p.add_argument("--param", action="append", help="Extra query param key=value, repeatable.")
        return p

    p = common(sub.add_parser("search", help="Scrape queries; print rows or append to a sheet."))
    p.add_argument("--sheet", help="Spreadsheet URL or ID to append into.")
    p.add_argument("--tab", default="leads", help="Tab name (default 'leads'; created if missing).")
    p.set_defaults(fn=cmd_search)

    p = common(sub.add_parser("test", help="One small dry run (limit ≤3, never writes)."))
    p.set_defaults(fn=cmd_test)

    p = common(sub.add_parser("estimate", help="Count the API calls a batch will burn."))
    p.set_defaults(fn=cmd_estimate)

    p = sub.add_parser("raw", help="Generic passthrough to any endpoint of the listing.")
    p.add_argument("--path", required=True)
    p.add_argument("--host")
    p.add_argument("--param", action="append")
    p.set_defaults(fn=cmd_raw)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
