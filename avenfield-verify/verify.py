#!/usr/bin/env python3
"""Avenfield verify — email verification via OmniVerifier. Stdlib only.

OmniVerifier is list-based: create a deliverable list, add emails, start,
poll status, page through results. This wraps that whole flow into one call.

Auth: OMNIVERIFIER_API_KEY (x-api-key header), resolved from the process env,
~/.avenfield/credentials.env, then the console .env.

USAGE
  python verify.py a@x.com b@y.com           # a few emails as args
  cat emails.txt | python verify.py --stdin   # one email per line
  python verify.py --file emails.csv          # pulls the email column / any email-looking cells

Output: JSON {"results": {email: status}, "summary": {status: count}, "balance": N}
Statuses: valid · invalid · catch-all · disposable · role · unknown
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

API_BASE = "https://api.omniverifier.com/v1/validate"
ADD_CHUNK = 9000          # API caps /add at 10k; stay under
RESULT_CODE = {0: "invalid", 1: "valid", 2: "catch-all", 3: "disposable",
               4: "role", 5: "unknown"}
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


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


def _api_key() -> str:
    k = os.environ.get("OMNIVERIFIER_API_KEY")
    if k:
        return k
    for p in (Path.home() / ".avenfield" / "credentials.env",
              Path.home() / "avenfield" / "apps" / "console" / ".env"):
        k = _load_env_file(p).get("OMNIVERIFIER_API_KEY")
        if k:
            return k
    sys.exit("Missing OMNIVERIFIER_API_KEY (env or ~/.avenfield/credentials.env).")


def _request(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API_BASE}{path}", data=data, method=method)
    req.add_header("x-api-key", _api_key())
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or "{}")
    except urllib.error.HTTPError as e:
        sys.exit(f"OmniVerifier HTTP {e.code} on {method} {path}: {e.read().decode()[:300]}")


def verify(emails: list[str], title: str = "avenfield-skill") -> dict:
    emails = [e.strip().lower() for e in emails if e and "@" in e]
    emails = list(dict.fromkeys(emails))          # dedupe, keep order
    if not emails:
        sys.exit("No valid emails to verify.")

    created = _request("POST", "/deliverable/new",
                       {"emails": len(emails), "title": title})
    list_id = created["id"]
    balance = created.get("current_balance")
    print(f"[verify] list {list_id} · {len(emails)} emails · balance {balance}",
          file=sys.stderr)

    for i in range(0, len(emails), ADD_CHUNK):
        _request("POST", f"/deliverable/{list_id}/add",
                 {"emails": emails[i:i + ADD_CHUNK]})
    _request("POST", f"/deliverable/{list_id}/start", {})

    # Poll until done (cap ~20 min)
    for _ in range(240):
        st = _request("GET", f"/deliverable/{list_id}/status")
        s = str(st.get("status", "")).lower()
        if s in {"completed", "complete", "done", "finished"}:
            break
        print(f"[verify]   status={s}", file=sys.stderr)
        time.sleep(5)

    out: dict[str, str] = {}
    page = 1
    while True:
        pg = _request("GET", f"/deliverable/{list_id}/results?page={page}&limit=500")
        rows = pg.get("results", [])
        if not rows:
            break
        for r in rows:
            email, code = r.get("email"), r.get("result")
            if email is not None and code is not None:
                out[email.lower()] = RESULT_CODE.get(code, f"code_{code}")
        page += 1

    summary: dict[str, int] = {}
    for s in out.values():
        summary[s] = summary.get(s, 0) + 1
    return {"results": out, "summary": summary, "balance": balance,
            "list_id": list_id}


def _emails_from_text(text: str) -> list[str]:
    return EMAIL_RE.findall(text or "")


def main():
    ap = argparse.ArgumentParser(description="Verify emails via OmniVerifier.")
    ap.add_argument("emails", nargs="*", help="Emails as args.")
    ap.add_argument("--stdin", action="store_true", help="Read emails from stdin.")
    ap.add_argument("--file", help="Read emails from a file (any email-looking cells).")
    ap.add_argument("--title", default="avenfield-skill")
    args = ap.parse_args()

    emails = list(args.emails)
    if args.stdin:
        emails += _emails_from_text(sys.stdin.read())
    if args.file:
        emails += _emails_from_text(Path(args.file).read_text(errors="replace"))
    if not emails:
        sys.exit("Provide emails as args, --stdin, or --file.")

    print(json.dumps(verify(emails, args.title), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
