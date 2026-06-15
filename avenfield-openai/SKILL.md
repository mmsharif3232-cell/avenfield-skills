---
name: avenfield-openai
description: "Full access to the OpenAI API — do anything the OpenAI key can do. Use ANY TIME Momin wants to run an LLM task with OpenAI specifically — 'extract these fields from the content', 'pull the founder/city/blurb from these pages', 'classify these leads', 'score these', 'summarize with gpt', 'generate embeddings', 'call gpt-5 with this prompt', 'use the openai key to…', or any bulk text task over rendered website content / lead data where OpenAI (cost/scale) is wanted instead of doing it inline. Has a raw passthrough to ANY /v1 endpoint (chat, responses, embeddings, images, moderations, …) plus convenience commands for chat and structured extraction (single + batch). Pairs with avenfield-browser-render: render → extract."
---

# Avenfield OpenAI

Everything the OpenAI key can do. `ai.py` in this skill dir; `OPENAI_API_KEY` loads from `~/.avenfield/credentials.env`.

Use this (not inline reasoning) when the task is **bulk** (hundreds/thousands of leads — keeps it off Claude's context and cheap on gpt-5-nano/mini) or when Momin explicitly says "use the OpenAI key".

## Raw passthrough — any endpoint, any body

```bash
A=~/.claude/skills/avenfield-openai/ai.py
python3 $A request /chat/completions --body '{"model":"gpt-5-mini","messages":[{"role":"user","content":"hi"}]}'
python3 $A request /embeddings       --body '{"model":"text-embedding-3-small","input":"hello"}'
python3 $A request /models --method GET
```
This is the "anything I want" surface — images, moderations, audio, files, responses API, etc.

## Convenience: chat

```bash
python3 $A chat --model gpt-5-mini --user "Summarise in one line: ..." \
  --system "You are terse." --body '{"reasoning_effort":"low"}'
```
Prints the reply text; `--raw` prints the full JSON. `--body` merges any params (temperature, reasoning_effort, max_tokens…).

## Convenience: structured extraction (the render → extract workflow)

```bash
# single page
python3 $A extract --model gpt-5-nano --content-file page.md \
  --vars '[{"name":"founder","description":"founder name"},
           {"name":"city","type":"string","description":"HQ city"},
           {"name":"is_agency","type":"boolean","description":"marketing agency?"}]'

# bulk — JSONL on stdin, one object per lead with a "content" field
cat pages.jsonl | python3 $A extract --batch --model gpt-5-nano --vars '[...]'
# each input line {"url":"x.com","content":"<markdown>"} → output adds the extracted fields,
# carrying url through, so results line up with leads.
```
`--vars` becomes a strict JSON schema, so output is always valid JSON with exactly those keys.

## Typical pipeline
`avenfield-browser-render markdown --batch` → produces `{url, content}` JSONL →
pipe into `avenfield-openai extract --batch --vars '[...]'` → write results back with
`avenfield-sheets`. Models: gpt-5-nano (cheapest, great for extraction), gpt-5-mini (default chat). Mention cost before very large bulk runs.
