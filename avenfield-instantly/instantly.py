#!/usr/bin/env python3
"""Avenfield instantly — Instantly v2 API. Stdlib only.

Two layers:
  • generic passthrough  → call ANY endpoint with ANY method/body (full power)
  • convenience commands  → campaigns, add-lead, push-sequence (the common 80%)

Auth: INSTANTLY_API_KEY (Bearer), from process env → ~/.avenfield/credentials.env
→ console .env.

USAGE
  # list campaigns (read-only, safe)
  python instantly.py campaigns

  # add one lead to a campaign (idempotent; skips if already in campaign)
  python instantly.py add-lead --campaign <ID> --email a@x.com \
      --body '{"first_name":"Ana","company_name":"Acme","website":"acme.com",
               "custom_variables":{"city":"Leeds"}}'

  # raw passthrough — anything the v2 API supports
  python instantly.py request GET  /campaigns --query 'limit=50'
  python instantly.py request POST /leads --body '{"campaign":"<ID>","email":"a@x.com"}'
  python instantly.py request PATCH /campaigns/<ID> --body '{"sequences":[...]}'

Docs: https://developer.instantly.ai/
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

BASE = "https://api.instantly.ai/api/v2"
STATUS = {0: "draft", 1: "active", 2: "paused", 3: "completed",
          4: "running subsequences", -99: "suspended", -1: "accounts unhealthy",
          -2: "bounce protect"}


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


def _key() -> str:
    k = os.environ.get("INSTANTLY_API_KEY")
    if k:
        return k
    for p in (Path.home() / ".avenfield" / "credentials.env",
              Path.home() / "avenfield" / "apps" / "console" / ".env"):
        k = _load_env_file(p).get("INSTANTLY_API_KEY")
        if k:
            return k
    sys.exit("Missing INSTANTLY_API_KEY (env or ~/.avenfield/credentials.env).")


def call(method: str, path: str, body: dict | None = None,
         query: str | None = None) -> tuple[int, dict]:
    url = f"{BASE}{path}"
    if query:
        url += ("&" if "?" in url else "?") + query
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method.upper())
    req.add_header("Authorization", f"Bearer {_key()}")
    # Instantly is behind Cloudflare, which 403s urllib's default UA (err 1010).
    req.add_header("User-Agent", "avenfield-skill/1.0")
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:500], "status": e.code}


def cmd_campaigns(args):
    status, data = call("GET", "/campaigns", query=f"limit={args.limit}")
    items = data.get("items", data if isinstance(data, list) else [])
    out = [{"id": c.get("id"), "name": c.get("name"),
            "status": STATUS.get(c.get("status"), c.get("status"))}
           for c in items]
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_add_lead(args):
    body = json.loads(args.body) if args.body else {}
    body.update({"campaign": args.campaign, "email": args.email,
                 "skip_if_in_campaign": not args.allow_dupes})
    status, data = call("POST", "/leads", body=body)
    print(json.dumps({"status": status, "result": data}, ensure_ascii=False, indent=2))


def cmd_push_sequence(args):
    steps = json.loads(args.steps)
    status, data = call("PATCH", f"/campaigns/{args.campaign}",
                        body={"sequences": [{"steps": steps}]})
    print(json.dumps({"status": status, "result": data}, ensure_ascii=False, indent=2))


def _add_one(campaign, lead, allow_dupes, retries=3):
    import time
    body = dict(lead)
    body.update({"campaign": campaign, "skip_if_in_campaign": not allow_dupes})
    for attempt in range(retries + 1):
        status, data = call("POST", "/leads", body=body)
        if status in (200, 201):
            return True, status, data
        if status in (429, 500, 502, 503, 504) and attempt < retries:
            time.sleep(1.5 * (attempt + 1))
            continue
        return False, status, data
    return False, status, data


def cmd_push_leads(args):
    """Bulk-add a JSONL of leads to a campaign, in parallel, idempotently."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    src = open(args.file) if args.file else sys.stdin
    leads = [json.loads(ln) for ln in src if ln.strip()]
    total = len(leads)
    ok = fail = 0
    errors = []
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as ex:
        futs = [ex.submit(_add_one, args.campaign, ld, args.allow_dupes) for ld in leads]
        for i, f in enumerate(as_completed(futs), 1):
            good, status, data = f.result()
            if good:
                ok += 1
            else:
                fail += 1
                if len(errors) < 10:
                    errors.append({"status": status, "error": str(data)[:160]})
            if i % 250 == 0 or i == total:
                print(f"  {i}/{total} pushed · ok={ok} fail={fail}", file=sys.stderr)
    print(json.dumps({"campaign": args.campaign, "total": total,
                      "ok": ok, "failed": fail, "errors": errors},
                     ensure_ascii=False, indent=2))


def cmd_request(args):
    body = json.loads(args.body) if args.body else None
    status, data = call(args.method, args.path, body=body, query=args.query)
    print(json.dumps({"status": status, "result": data}, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description="Instantly v2 API.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("campaigns", help="List campaigns.")
    p.add_argument("--limit", type=int, default=100)
    p.set_defaults(fn=cmd_campaigns)

    p = sub.add_parser("add-lead", help="Add one lead to a campaign.")
    p.add_argument("--campaign", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--body", help="JSON of extra lead fields.")
    p.add_argument("--allow-dupes", action="store_true",
                   help="Don't skip if already in the campaign.")
    p.set_defaults(fn=cmd_add_lead)

    p = sub.add_parser("push-sequence", help="Overwrite a campaign's sequence.")
    p.add_argument("--campaign", required=True)
    p.add_argument("--steps", required=True,
                   help='JSON array of steps, e.g. [{"type":"email","delay":0,'
                        '"variants":[{"subject":"..","body":"<div>..</div>"}]}]')
    p.set_defaults(fn=cmd_push_sequence)

    p = sub.add_parser("push-leads", help="Bulk-add a JSONL of leads to a campaign (parallel, idempotent).")
    p.add_argument("--campaign", required=True)
    p.add_argument("--file", help="JSONL file of leads (default: stdin). Each line a lead object with 'email'.")
    p.add_argument("--concurrency", type=int, default=5)
    p.add_argument("--allow-dupes", action="store_true", help="Don't skip leads already in the campaign.")
    p.set_defaults(fn=cmd_push_leads)

    p = sub.add_parser("request", help="Raw passthrough to any endpoint.")
    p.add_argument("method")
    p.add_argument("path", help="e.g. /campaigns or /leads/<id>")
    p.add_argument("--body", help="JSON body.")
    p.add_argument("--query", help="Raw query string, e.g. 'limit=50&search=x'.")
    p.set_defaults(fn=cmd_request)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
