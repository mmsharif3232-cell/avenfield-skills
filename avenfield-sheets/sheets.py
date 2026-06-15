#!/usr/bin/env python3
"""Avenfield sheets — Google Sheets via your own Google account (OAuth). Stdlib only.

Because it logs in AS YOU, it can read/write any spreadsheet you can already
open — no sharing-to-a-service-account step. One interactive `auth` per device,
then it runs headless using a stored refresh token.

ONE-TIME SETUP (per Google project, done once):
  1. console.cloud.google.com → APIs & Services → Enable "Google Sheets API".
  2. Credentials → Create Credentials → OAuth client ID → type "Desktop app".
  3. Put the client id + secret in ~/.avenfield/credentials.env:
         GOOGLE_OAUTH_CLIENT_ID=...
         GOOGLE_OAUTH_CLIENT_SECRET=...
  4. Per device, once:  python sheets.py auth   (opens a browser, you approve)

USAGE
  python sheets.py auth
  python sheets.py tabs   --sheet <URL|ID>
  python sheets.py read   --sheet <URL|ID> --range "Sheet1!A1:F"
  python sheets.py write  --sheet <URL|ID> --range "Sheet1!A1" --values '[["a","b"],["c","d"]]'
  python sheets.py append --sheet <URL|ID> --range "Sheet1!A1" --values '[["x","y"]]'
  python sheets.py add-tab    --sheet <URL|ID> --title leads
  python sheets.py delete-tab --sheet <URL|ID> --title scraped
  python sheets.py create --title "My new sheet"     # prints the new id+url
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import urllib.error
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
SCOPE = "https://www.googleapis.com/auth/spreadsheets"
TOKEN_FILE = Path.home() / ".avenfield" / "google-token.json"


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


def _cfg(name: str) -> str | None:
    v = os.environ.get(name)
    if v:
        return v
    for p in (Path.home() / ".avenfield" / "credentials.env",
              Path.home() / "avenfield" / "apps" / "console" / ".env"):
        v = _load_env_file(p).get(name)
        if v:
            return v
    return None


def _client() -> tuple[str, str]:
    cid, sec = _cfg("GOOGLE_OAUTH_CLIENT_ID"), _cfg("GOOGLE_OAUTH_CLIENT_SECRET")
    if not cid or not sec:
        sys.exit("Missing GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET. "
                 "See setup at the top of sheets.py.")
    return cid, sec


def _post_form(url: str, fields: dict) -> dict:
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"OAuth token error {e.code}: {e.read().decode()[:300]}")


def cmd_auth(args):
    cid, sec = _client()
    # Loopback OAuth (Desktop app): catch the redirect on a local port.
    holder = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.urlparse(self.path).query
            holder.update(urllib.parse.parse_qs(q))
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>Avenfield: Google connected. You can close this tab.</h2>")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    redirect = f"http://127.0.0.1:{port}"
    params = urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code",
        "scope": SCOPE, "access_type": "offline", "prompt": "consent",
    })
    url = f"{AUTH_URL}?{params}"
    print(f"Opening browser to authorize…\nIf it doesn't open, visit:\n{url}\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    srv.handle_request()  # blocks until Google redirects back
    code = (holder.get("code") or [None])[0]
    if not code:
        sys.exit(f"No auth code received (got: {holder}).")
    tok = _post_form(TOKEN_URL, {
        "code": code, "client_id": cid, "client_secret": sec,
        "redirect_uri": redirect, "grant_type": "authorization_code",
    })
    refresh = tok.get("refresh_token")
    if not refresh:
        sys.exit("No refresh_token returned. Revoke prior access at "
                 "myaccount.google.com/permissions and re-run `auth`.")
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps({"refresh_token": refresh}))
    TOKEN_FILE.chmod(0o600)
    print(f"✓ Connected. Token saved to {TOKEN_FILE}. You're set on this device.")


def _access_token() -> str:
    if not TOKEN_FILE.exists():
        sys.exit("Not authorized on this device. Run: python sheets.py auth")
    refresh = json.loads(TOKEN_FILE.read_text()).get("refresh_token")
    cid, sec = _client()
    tok = _post_form(TOKEN_URL, {
        "refresh_token": refresh, "client_id": cid, "client_secret": sec,
        "grant_type": "refresh_token",
    })
    if "access_token" not in tok:
        sys.exit(f"Token refresh failed: {tok}")
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


def cmd_tabs(args):
    sid = _sheet_id(args.sheet)
    data = _api("GET", f"{SHEETS}/{sid}?fields=sheets.properties")
    tabs = [{"title": s["properties"]["title"], "sheetId": s["properties"]["sheetId"]}
            for s in data.get("sheets", [])]
    print(json.dumps(tabs, ensure_ascii=False, indent=2))


def cmd_read(args):
    sid = _sheet_id(args.sheet)
    rng = urllib.parse.quote(args.range)
    data = _api("GET", f"{SHEETS}/{sid}/values/{rng}")
    print(json.dumps(data.get("values", []), ensure_ascii=False, indent=2))


def cmd_write(args):
    sid = _sheet_id(args.sheet)
    rng = urllib.parse.quote(args.range)
    vals = json.loads(args.values)
    data = _api("PUT", f"{SHEETS}/{sid}/values/{rng}?valueInputOption=RAW",
                {"values": vals})
    print(json.dumps({"updated": data}, ensure_ascii=False, indent=2))


def cmd_append(args):
    sid = _sheet_id(args.sheet)
    rng = urllib.parse.quote(args.range)
    vals = json.loads(args.values)
    data = _api("POST",
                f"{SHEETS}/{sid}/values/{rng}:append?valueInputOption=RAW&insertDataOption=INSERT_ROWS",
                {"values": vals})
    print(json.dumps({"appended": data.get("updates", data)}, ensure_ascii=False, indent=2))


def cmd_add_tab(args):
    sid = _sheet_id(args.sheet)
    data = _api("POST", f"{SHEETS}/{sid}:batchUpdate",
                {"requests": [{"addSheet": {"properties": {"title": args.title}}}]})
    print(json.dumps({"added": args.title, "result": data}, ensure_ascii=False))


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
    ap = argparse.ArgumentParser(description="Google Sheets via your Google account (OAuth).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("auth", help="One-time browser login on this device.").set_defaults(fn=cmd_auth)

    def with_sheet(p):
        p.add_argument("--sheet", required=True, help="Spreadsheet URL or ID.")
        return p

    p = with_sheet(sub.add_parser("tabs", help="List tab names + ids.")); p.set_defaults(fn=cmd_tabs)
    p = with_sheet(sub.add_parser("read", help="Read a range.")); p.add_argument("--range", required=True); p.set_defaults(fn=cmd_read)
    p = with_sheet(sub.add_parser("write", help="Overwrite a range.")); p.add_argument("--range", required=True); p.add_argument("--values", required=True, help="JSON 2D array."); p.set_defaults(fn=cmd_write)
    p = with_sheet(sub.add_parser("append", help="Append rows.")); p.add_argument("--range", required=True); p.add_argument("--values", required=True, help="JSON 2D array."); p.set_defaults(fn=cmd_append)
    p = with_sheet(sub.add_parser("add-tab", help="Add a tab.")); p.add_argument("--title", required=True); p.set_defaults(fn=cmd_add_tab)
    p = with_sheet(sub.add_parser("delete-tab", help="Delete a tab by name.")); p.add_argument("--title", required=True); p.set_defaults(fn=cmd_delete_tab)
    p = sub.add_parser("create", help="Create a new spreadsheet."); p.add_argument("--title", required=True); p.set_defaults(fn=cmd_create)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
