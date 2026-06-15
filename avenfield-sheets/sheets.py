#!/usr/bin/env python3
"""Avenfield sheets — Google Sheets via a service-account JSON. Stdlib + openssl.

Uses the service-account key you already have (GOOGLE_APPLICATION_CREDENTIALS).
No GCP OAuth client, no interactive login: the script mints a bearer token by
signing a JWT with `openssl` (present on every Mac/Linux), so it stays
dependency-free. The service account can touch any sheet SHARED WITH ITS EMAIL
(share the sheet with the client_email from the JSON — the easy path).

SETUP (per device)
  • Copy the service-account JSON to the device.
  • Point GOOGLE_APPLICATION_CREDENTIALS at it in ~/.avenfield/credentials.env.
  • Share each target sheet with the service account's email (Editor).

USAGE
  python sheets.py whoami                                  # prints the SA email to share with
  python sheets.py tabs   --sheet <URL|ID>
  python sheets.py read   --sheet <URL|ID> --range "Sheet1!A1:F"
  python sheets.py write  --sheet <URL|ID> --range "Sheet1!A1" --values '[["a","b"],["c","d"]]'
  python sheets.py append --sheet <URL|ID> --range "Sheet1!A1" --values '[["x","y"]]'
  python sheets.py add-tab    --sheet <URL|ID> --title leads
  python sheets.py delete-tab --sheet <URL|ID> --title scraped
  python sheets.py create --title "My new sheet"          # SA owns it; share/transfer as needed
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

TOKEN_URL = "https://oauth2.googleapis.com/token"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
SCOPE = "https://www.googleapis.com/auth/spreadsheets"


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


def _sa_path() -> str:
    p = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not p:
        for f in (Path.home() / ".avenfield" / "credentials.env",
                  Path.home() / "avenfield" / "apps" / "console" / ".env"):
            p = _load_env_file(f).get("GOOGLE_APPLICATION_CREDENTIALS")
            if p:
                break
    if not p:
        sys.exit("Missing GOOGLE_APPLICATION_CREDENTIALS (path to the SA JSON).")
    p = os.path.expanduser(p)
    if not Path(p).exists():
        sys.exit(f"Service-account JSON not found at {p}.")
    return p


def _sa() -> dict:
    return json.loads(Path(_sa_path()).read_text())


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _sign_rs256(signing_input: str, private_key_pem: str) -> str:
    fd, keypath = tempfile.mkstemp(suffix=".pem")
    try:
        os.write(fd, private_key_pem.encode())
        os.close(fd)
        os.chmod(keypath, 0o600)
        proc = subprocess.run(["openssl", "dgst", "-sha256", "-sign", keypath],
                              input=signing_input.encode(),
                              capture_output=True)
        if proc.returncode != 0:
            sys.exit(f"openssl signing failed: {proc.stderr.decode()[:200]}")
        return _b64u(proc.stdout)
    finally:
        try:
            os.unlink(keypath)
        except OSError:
            pass


_token_cache: dict = {}


def _access_token() -> str:
    if _token_cache.get("exp", 0) > time.time() + 60:
        return _token_cache["tok"]
    sa = _sa()
    now = int(time.time())
    header = _b64u(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    claim = _b64u(json.dumps({
        "iss": sa["client_email"], "scope": SCOPE,
        "aud": TOKEN_URL, "iat": now, "exp": now + 3600,
    }).encode())
    assertion = f"{header}.{claim}." + _sign_rs256(f"{header}.{claim}", sa["private_key"])
    data = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            tok = json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"Token mint failed {e.code}: {e.read().decode()[:300]}")
    _token_cache.update(tok=tok["access_token"], exp=now + 3600)
    return tok["access_token"]


def _api(method: str, url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {_access_token()}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"Sheets API {e.code} on {method}: {e.read().decode()[:400]}")


def _sheet_id(s: str) -> str:
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]+)", s)
    return m.group(1) if m else s


def cmd_whoami(args):
    print(json.dumps({"service_account_email": _sa().get("client_email"),
                      "share_sheets_with_this": _sa().get("client_email")}, indent=2))


def cmd_tabs(args):
    data = _api("GET", f"{SHEETS}/{_sheet_id(args.sheet)}?fields=sheets.properties")
    print(json.dumps([{"title": s["properties"]["title"],
                       "sheetId": s["properties"]["sheetId"]}
                      for s in data.get("sheets", [])], ensure_ascii=False, indent=2))


def cmd_read(args):
    rng = urllib.parse.quote(args.range)
    data = _api("GET", f"{SHEETS}/{_sheet_id(args.sheet)}/values/{rng}")
    print(json.dumps(data.get("values", []), ensure_ascii=False, indent=2))


def cmd_write(args):
    rng = urllib.parse.quote(args.range)
    data = _api("PUT", f"{SHEETS}/{_sheet_id(args.sheet)}/values/{rng}?valueInputOption=RAW",
                {"values": json.loads(args.values)})
    print(json.dumps({"updated": data}, ensure_ascii=False, indent=2))


def cmd_append(args):
    rng = urllib.parse.quote(args.range)
    data = _api("POST",
                f"{SHEETS}/{_sheet_id(args.sheet)}/values/{rng}:append"
                "?valueInputOption=RAW&insertDataOption=INSERT_ROWS",
                {"values": json.loads(args.values)})
    print(json.dumps({"appended": data.get("updates", data)}, ensure_ascii=False, indent=2))


def cmd_add_tab(args):
    data = _api("POST", f"{SHEETS}/{_sheet_id(args.sheet)}:batchUpdate",
                {"requests": [{"addSheet": {"properties": {"title": args.title}}}]})
    print(json.dumps({"added": args.title}, ensure_ascii=False))


def cmd_delete_tab(args):
    sid = _sheet_id(args.sheet)
    meta = _api("GET", f"{SHEETS}/{sid}?fields=sheets.properties")
    target = next((s["properties"]["sheetId"] for s in meta.get("sheets", [])
                   if s["properties"]["title"] == args.title), None)
    if target is None:
        sys.exit(f"No tab named '{args.title}'.")
    _api("POST", f"{SHEETS}/{sid}:batchUpdate",
         {"requests": [{"deleteSheet": {"sheetId": target}}]})
    print(json.dumps({"deleted": args.title}))


def cmd_create(args):
    data = _api("POST", SHEETS, {"properties": {"title": args.title}})
    print(json.dumps({"id": data.get("spreadsheetId"),
                      "url": data.get("spreadsheetUrl")}, indent=2))


def main():
    ap = argparse.ArgumentParser(description="Google Sheets via service-account JSON.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("whoami", help="Print the SA email to share sheets with.").set_defaults(fn=cmd_whoami)

    def ws(p):
        p.add_argument("--sheet", required=True, help="Spreadsheet URL or ID.")
        return p

    p = ws(sub.add_parser("tabs")); p.set_defaults(fn=cmd_tabs)
    p = ws(sub.add_parser("read")); p.add_argument("--range", required=True); p.set_defaults(fn=cmd_read)
    p = ws(sub.add_parser("write")); p.add_argument("--range", required=True); p.add_argument("--values", required=True); p.set_defaults(fn=cmd_write)
    p = ws(sub.add_parser("append")); p.add_argument("--range", required=True); p.add_argument("--values", required=True); p.set_defaults(fn=cmd_append)
    p = ws(sub.add_parser("add-tab")); p.add_argument("--title", required=True); p.set_defaults(fn=cmd_add_tab)
    p = ws(sub.add_parser("delete-tab")); p.add_argument("--title", required=True); p.set_defaults(fn=cmd_delete_tab)
    p = sub.add_parser("create"); p.add_argument("--title", required=True); p.set_defaults(fn=cmd_create)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
