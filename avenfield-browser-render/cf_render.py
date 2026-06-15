#!/usr/bin/env python3
"""Avenfield browser-render — raw access to Cloudflare Browser Rendering.

Every Cloudflare Browser Rendering REST endpoint, with full pass-through of
options. Claude builds the JSON body; this script signs + sends it.

Endpoints (https://developers.cloudflare.com/browser-rendering/rest-api/):
  content     rendered HTML after JS executes
  markdown    page as markdown (best for LLM extraction)
  snapshot    HTML + a base64 screenshot in one call
  screenshot  PNG/JPEG of the page (binary → --out)
  pdf         PDF of the page (binary → --out)
  scrape      extract specific elements by CSS selector
  json        structured extraction via a prompt + JSON schema
  links       all links on the page

Auth comes from CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN, resolved from
(in order): the process env, ~/.avenfield/credentials.env, then the console
.env at ~/avenfield/apps/console/.env.

USAGE
  # convenience: just a url
  python cf_render.py markdown --url https://example.com

  # full control: pass any Cloudflare body options as JSON (merged with --url)
  python cf_render.py content --url https://x.com \
      --body '{"gotoOptions":{"waitUntil":"networkidle0","timeout":45000},
               "waitForSelector":{"selector":"#main"},
               "rejectResourceTypes":["image","font"]}'

  # scrape specific elements
  python cf_render.py scrape --url https://x.com \
      --body '{"elements":[{"selector":"h1"},{"selector":".price"}]}'

  # structured extraction (LLM, server-side at Cloudflare)
  python cf_render.py json --url https://x.com \
      --body '{"prompt":"Extract the founder name and tagline",
               "response_format":{"type":"json_schema","json_schema":{
                 "type":"object","properties":{"founder":{"type":"string"},
                 "tagline":{"type":"string"}}}}}'

  # binary output
  python cf_render.py screenshot --url https://x.com --out shot.png
  python cf_render.py pdf        --url https://x.com --out page.pdf

  # batch: one url per line on stdin, markdown each → JSONL on stdout
  cat urls.txt | python cf_render.py markdown --batch
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

import urllib.request
import urllib.error

API_BASE = "https://api.cloudflare.com/client/v4/accounts"
BINARY_ENDPOINTS = {"screenshot", "pdf"}
ALL_ENDPOINTS = {"content", "markdown", "snapshot", "screenshot", "pdf",
                 "scrape", "json", "links"}


def _load_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    return out


def _creds() -> tuple[str, str]:
    acct = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    tok = os.environ.get("CLOUDFLARE_API_TOKEN")
    if acct and tok:
        return acct, tok
    for p in (Path.home() / ".avenfield" / "credentials.env",
              Path.home() / "avenfield" / "apps" / "console" / ".env"):
        env = _load_env_file(p)
        acct = acct or env.get("CLOUDFLARE_ACCOUNT_ID")
        tok = tok or env.get("CLOUDFLARE_API_TOKEN")
        if acct and tok:
            return acct, tok
    sys.exit("Missing CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN. "
             "Set them in env or ~/.avenfield/credentials.env.")


def render(endpoint: str, payload: dict, timeout: float = 90.0) -> tuple[int, bytes, str]:
    acct, tok = _creds()
    url = f"{API_BASE}/{acct}/browser-rendering/{endpoint}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", "")


def _emit(endpoint: str, status: int, body: bytes, ctype: str, out: str | None):
    if endpoint in BINARY_ENDPOINTS:
        # Cloudflare may return raw bytes or a JSON envelope with base64.
        if "application/json" in ctype:
            j = json.loads(body)
            b64 = (j.get("result") or "") if isinstance(j.get("result"), str) else ""
            raw = base64.b64decode(b64) if b64 else body
        else:
            raw = body
        if out:
            Path(out).write_bytes(raw)
            print(json.dumps({"ok": status == 200, "status": status,
                              "saved": out, "bytes": len(raw)}))
        else:
            sys.stdout.buffer.write(raw)
        return
    # Text/JSON endpoints — Cloudflare wraps results in {"success","result"}.
    text = body.decode("utf-8", "replace")
    try:
        j = json.loads(text)
        result = j.get("result", j)
        print(result if isinstance(result, str)
              else json.dumps(result, ensure_ascii=False, indent=2))
    except json.JSONDecodeError:
        print(text)


def main():
    ap = argparse.ArgumentParser(description="Cloudflare Browser Rendering — raw access.")
    ap.add_argument("endpoint", choices=sorted(ALL_ENDPOINTS))
    ap.add_argument("--url", help="Target URL (merged into the body).")
    ap.add_argument("--body", default="{}",
                    help="JSON of any Cloudflare options, merged with --url.")
    ap.add_argument("--out", help="For screenshot/pdf: write binary here.")
    ap.add_argument("--batch", action="store_true",
                    help="Read URLs from stdin (one per line); JSONL out.")
    ap.add_argument("--timeout", type=float, default=90.0)
    args = ap.parse_args()

    try:
        base_body = json.loads(args.body)
    except json.JSONDecodeError as e:
        sys.exit(f"--body is not valid JSON: {e}")

    if args.batch:
        for line in sys.stdin:
            u = line.strip()
            if not u:
                continue
            payload = {**base_body, "url": u}
            status, body, ctype = render(args.endpoint, payload, args.timeout)
            text = body.decode("utf-8", "replace")
            try:
                res = json.loads(text).get("result")
            except json.JSONDecodeError:
                res = text
            print(json.dumps({"url": u, "status": status, "result": res},
                             ensure_ascii=False))
        return

    payload = dict(base_body)
    if args.url:
        payload["url"] = args.url
    if "url" not in payload:
        sys.exit("Provide --url or include 'url' in --body.")
    status, body, ctype = render(args.endpoint, payload, args.timeout)
    _emit(args.endpoint, status, body, ctype, args.out)


if __name__ == "__main__":
    main()
