#!/usr/bin/env python3
"""Avenfield openai — full access to the OpenAI API. Stdlib only.

Anything the OpenAI key can do. A raw passthrough to ANY /v1/* endpoint
(chat, responses, embeddings, images, moderations, audio, files, …) plus
convenience commands for the two most common jobs: `chat` and `extract`.

Auth: OPENAI_API_KEY (Bearer), from process env → ~/.avenfield/credentials.env
→ console .env.

USAGE
  # raw passthrough — hit ANY endpoint with ANY body
  python ai.py request /chat/completions \
      --body '{"model":"gpt-5-mini","messages":[{"role":"user","content":"hi"}]}'
  python ai.py request /embeddings \
      --body '{"model":"text-embedding-3-small","input":"hello"}'
  python ai.py request /models --method GET

  # convenience: chat (prints the assistant text; --raw for full JSON)
  python ai.py chat --model gpt-5-mini --user "Summarise this in 1 line: ..." \
      --system "You are terse." --body '{"reasoning_effort":"low"}'

  # convenience: structured extraction from text (returns JSON of your fields)
  python ai.py extract --content-file page.md --model gpt-5-nano \
      --vars '[{"name":"founder","description":"founder name"},
               {"name":"city","type":"string","description":"HQ city"},
               {"name":"is_agency","type":"boolean","description":"is it a marketing agency"}]'

  # bulk extraction: JSONL on stdin (each line {"content": "...", ...passthrough})
  cat pages.jsonl | python ai.py extract --batch --model gpt-5-nano --vars '[...]'
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

BASE = "https://api.openai.com/v1"
_TYPES = {"string": "string", "number": "number", "integer": "integer",
          "boolean": "boolean", "list": "array", "array": "array"}


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
    k = os.environ.get("OPENAI_API_KEY")
    if k:
        return k
    for p in (Path.home() / ".avenfield" / "credentials.env",
              Path.home() / "avenfield" / "apps" / "console" / ".env"):
        k = _load_env_file(p).get("OPENAI_API_KEY")
        if k:
            return k
    sys.exit("Missing OPENAI_API_KEY (env or ~/.avenfield/credentials.env).")


def call(path: str, body: dict | None = None, method: str = "POST",
         timeout: float = 120.0) -> tuple[int, dict]:
    if not path.startswith("/"):
        path = "/" + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, method=method.upper())
    req.add_header("Authorization", f"Bearer {_key()}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:600], "status": e.code}


def _chat_text(data: dict) -> str:
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        return json.dumps(data, ensure_ascii=False)


def cmd_request(args):
    body = json.loads(args.body) if args.body else None
    status, data = call(args.path, body=body, method=args.method)
    print(json.dumps({"status": status, "result": data}, ensure_ascii=False, indent=2))


def cmd_chat(args):
    messages = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    messages.append({"role": "user", "content": args.user})
    body = {"model": args.model, "messages": messages}
    if args.body:
        body.update(json.loads(args.body))
    status, data = call("/chat/completions", body=body)
    if status != 200:
        sys.exit(json.dumps(data, indent=2))
    print(json.dumps(data, ensure_ascii=False, indent=2) if args.raw else _chat_text(data))


def _schema_from_vars(vars_spec: list[dict]) -> dict:
    props, required = {}, []
    for v in vars_spec:
        name = v["name"]
        t = _TYPES.get(str(v.get("type", "string")).lower(), "string")
        prop = {"type": t}
        if v.get("description"):
            prop["description"] = v["description"]
        if t == "array":
            prop["items"] = {"type": "string"}
        props[name] = prop
        required.append(name)
    return {"type": "object", "properties": props, "required": required,
            "additionalProperties": False}


def _extract_one(content: str, schema: dict, model: str, prompt: str | None,
                 extra: dict) -> dict:
    sys_msg = (prompt or "Extract the requested fields from the content. "
               "If a field isn't present, use an empty string/least-committal value.")
    body = {
        "model": model,
        "messages": [{"role": "system", "content": sys_msg},
                     {"role": "user", "content": content}],
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "extraction", "strict": True,
                                            "schema": schema}},
    }
    body.update(extra)
    status, data = call("/chat/completions", body=body)
    if status != 200:
        return {"_error": data}
    try:
        return json.loads(data["choices"][0]["message"]["content"])
    except Exception:
        return {"_error": "unparseable", "_raw": data}


def cmd_extract(args):
    schema = _schema_from_vars(json.loads(args.vars))
    extra = json.loads(args.body) if args.body else {}
    if args.batch:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            content = item.get("content", "")
            result = _extract_one(content, schema, args.model, args.prompt, extra)
            passthrough = {k: v for k, v in item.items() if k != "content"}
            print(json.dumps({**passthrough, **result}, ensure_ascii=False))
        return
    if args.content_file:
        content = Path(args.content_file).read_text(errors="replace")
    elif args.content:
        content = args.content
    else:
        content = sys.stdin.read()
    print(json.dumps(_extract_one(content, schema, args.model, args.prompt, extra),
                     ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description="Full OpenAI API access.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("request", help="Raw passthrough to any /v1 endpoint.")
    p.add_argument("path", help="e.g. /chat/completions or /embeddings or /models")
    p.add_argument("--body", help="JSON request body.")
    p.add_argument("--method", default="POST")
    p.set_defaults(fn=cmd_request)

    p = sub.add_parser("chat", help="One-shot chat; prints the reply text.")
    p.add_argument("--model", default="gpt-5-mini")
    p.add_argument("--user", required=True)
    p.add_argument("--system")
    p.add_argument("--body", help="Extra JSON merged into the request (temperature, reasoning_effort, …).")
    p.add_argument("--raw", action="store_true", help="Print full JSON response.")
    p.set_defaults(fn=cmd_chat)

    p = sub.add_parser("extract", help="Structured extraction → JSON of your fields.")
    p.add_argument("--vars", required=True, help='JSON [{"name","description","type"}]')
    p.add_argument("--model", default="gpt-5-nano")
    p.add_argument("--content", help="Inline content.")
    p.add_argument("--content-file", help="Read content from a file.")
    p.add_argument("--prompt", help="Override the extraction instruction.")
    p.add_argument("--body", help="Extra JSON merged into each request.")
    p.add_argument("--batch", action="store_true",
                   help="Read JSONL from stdin ({content,...}); emit JSONL with fields added.")
    p.set_defaults(fn=cmd_extract)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
