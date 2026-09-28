---
name: rally-live-iteration
description: Use when a coding agent will send real iMessages through BlueBubbles to measure Rally reply quality, then patch and reload. Also use for HackGT13 / tarun devi live loops, webhook 8770 checks, or when tempted to paste admin tokens or .env secrets into a group.
---

# Rally live iteration

Durable loop for coding agents: send a real iMessage via BlueBubbles, measure speed/usefulness/context, patch, reload, repeat.

This document describes the **process**. Do not freeze `decide_conversation` prompt text from `app/agent.py` — another agent may be live-editing that prompt. Read the current functions and payload shape; improve routing, context assembly, and latency. Do not fight uncommitted prompt edits.

**Do not send live messages unless you own the live loop.** Documentation and code agents write this workflow; a separate live-iterate agent sends.

## When to use

- Owner asked to live-iterate Rally in HackGT13 or another configured allowlisted chat.
- You need to know whether a reply was fast, useful, and grounded in thread + memory + plan.
- You are about to curl BlueBubbles, restart uvicorn on 8770, or judge a group reply.

**Do not use** this to message chats outside `RALLY_ALLOWED_CHAT_GUIDS`, to flip SIP / Private API, or to paste secrets into iMessage.

## Constraints (fail closed)

| Rule | Reality |
| --- | --- |
| Allowlisted chats only | Send only to GUIDs in `RALLY_ALLOWED_CHAT_GUIDS`. Resolve **HackGT13** or **tarun devi** by display name, then confirm the GUID is allowlisted. Empty allowlist means Rally will not ingest or reply. |
| Never print `.env` secrets | Source `.env` into the shell. Use `$RALLY_BLUEBUBBLES_PASSWORD`, `$RALLY_WEBHOOK_TOKEN`, `$RALLY_ADMIN_TOKEN` in commands. Do not `echo`, log, commit, or paste URL query strings that contain the BlueBubbles password. |
| Never put `RALLY_ADMIN_TOKEN` in a group | Admin desk is local HTTP. Group replies must not include `?token=`. |
| Do not flip SIP / Private API | This Mac has SIP on and BlueBubbles `private_api=false`. Text send/receive does not need the helper. Do not disable SIP or enable Private API. |
| Flood cap | Rally sends at most **3 replies per chat per rolling minute** (`app/group_turns.py`). Safety/portal/approval paths may bypass. Your probes still count. |
| Coalesce | Same inbound text within **15 seconds** is coalesced — no second reply. Change the probe text each send. |
| Do not spam | Cap live sends (default **6 per session**). Wait until you have a reply or a clear timeout before the next send. Space probes by **≥20 seconds**. |
| No `Rally:` prefix / lowercase | Outbound Rally texts are formatted at the BlueBubbles boundary as lowercase body text with no `Rally:` prefix (`add_rally_signature`). Inbound `isFromMe` echoes are dropped by confirmed guid or temp guid. Identical text is a fallback only until that id is known, and for at most 60 seconds. Older `isFromMe` texts that still start with `Rally:` are also dropped. |

Illegal-assistance probes: local `illegal_assistance_request` and `safety=refuse` fail closed (`I can't help with that.`). Do not keep sending crime-facilitation texts after one refusal check.

## How to send

BlueBubbles HTTP uses `RALLY_BLUEBUBBLES_URL` and `RALLY_BLUEBUBBLES_PASSWORD` from ignored `.env` (see `.env.example`). Password is a query param on BlueBubbles URLs — never print the full URL.

```sh
set -a
. ./.env
set +a
# vars are in the environment; do not echo them
```

### 1. Resolve the chat

`POST {RALLY_BLUEBUBBLES_URL}/api/v1/chat/query?password=...` with JSON `{"limit":50,"sort":"lastmessage"}`.

Match `displayName` case-insensitively to **HackGT13** or **tarun devi**. If `displayName` is empty, fall back to participant `displayName` / `address` (same rule as `app/voice/tools.py`). Group GUIDs contain `;+;`.

Confirm `guid` is in `RALLY_ALLOWED_CHAT_GUIDS`. If it is not, **stop** — do not send, do not add GUIDs yourself.

### 2. POST text Rally will process

`POST {RALLY_BLUEBUBBLES_URL}/api/v1/message/text?password=...`

```json
{"chatGuid": "<allowlisted-guid>", "message": "Hey Rally, <unique probe>", "tempGuid": "<uuid4>"}
```

BlueBubbles timeout on Rally's adapter is 45 seconds. A `status` other than 200, or a dropped connection, is **uncertain** — inspect the thread before any retry. Do not automatically resend.

Address Rally so `explicitly_addresses_rally` matches: start with `Rally` / `@Rally` or a short greeting plus Rally (`Hey Rally, …`). Mid-message mentions stay silent.

**`isFromMe` / `is_from_rally`:**

- Your BlueBubbles send uses the signed-in Apple account, so the webhook usually has `isFromMe: true` and `sender_id` `local-imessage-account`. That is a **human** probe when the text was not just sent by Rally.
- `normalize_webhook` drops `isFromMe` texts that match `^\s*Rally\s*:` and `isFromMe` echoes of texts Rally itself sent. Do not prefix probes with `Rally:`.
- Stored inbound rows have `is_from_rally=false`. Rally's own reply is queued, sent without a `Rally:` prefix, and recorded as `is_from_rally=true` (`rally-out:{inbound-id}`).

## How to know Rally ingested

| Signal | What success looks like |
| --- | --- |
| Health | `GET http://127.0.0.1:8770/health` → `{"status":"ok"}`. If this fails, do not send. |
| Webhook | BlueBubbles `new-message` → `POST /webhooks/bluebubbles?token=<RALLY_WEBHOOK_TOKEN>` on **8770** (not 8000). Rally returns `{"accepted": true}` when the chat is allowlisted and the event is a usable group message. `accepted: false` means ignored (echo, empty, non-group, duplicate processed). **503** means processing threw (often provider). |
| SQLite | `RALLY_DATABASE_PATH` (default `data/rally.sqlite3`): inbound row for your text; later an `outbox` row `kind=direct_reply` with `status=sent` (or `uncertain` / `failed`). |
| Logs | Server stdout (access log is off). Look for `group_conversation stage=decision elapsed_ms=…` then `stage=send elapsed_ms=…`. Do not log message text or credentials. |
| BlueBubbles history | `GET /api/v1/chat/{guid}/message` — a later `isFromMe` text that does not start with `Rally:` can be the bot reply. Confirm it with the outbox row rather than by printing the text. |

**Reload after code changes.** The README start command is factory uvicorn **without** `--reload`. Stop the 8770 process (Ctrl-C in that terminal) and start it again with the same `set -a; . ./.env; set +a` + uvicorn line so `app/agent.py` / `app/orchestrator.py` load. Confirm `/health` before the next send.

## Quality bar

Score the **visible reply**, not extract completeness.

**(a) Fast** — Reply is not blocked on plan extract. Live wiring sets `defer_heavy_work=True`: `_handle_addressed_message` runs first; `_extract_and_learn` is submitted after the webhook returns. A reply that waits on extract is a regression. Decision HTTP timeout is 10s (`GrokClient._call`); extract is separate (default 60s, low effort).

**(b) Useful** — Recommend one option the thread already named (one-line why), **or** ask exactly one missing decision (time vs venue vs who). Fail: shrug, “I don't know”, generic filler, restating the question when the thread has signal.

**(c) Knowledge** — `decide_conversation` must receive recent thread (`_conversation_messages`, last 12, humans + Rally), group memory (`prompt_context`, up to 12 facts), and current plan facts (may be empty/stale; chat wins). If the model asks for a detail already in those three, fix **context assembly** in orchestrator/agent — do not paste a frozen prompt.

## Loop

```
health → resolve allowlisted chat → send unique addressed probe
     → poll reply + latency (webhook / outbox / history / logs)
     → score fast / useful / knowledge
     → patch agent.py or orchestrator context (not a prompt snapshot war)
     → .venv/bin/python -m pytest -q <focused tests>
     → restart uvicorn 8770 → health → next send
```

1. **Send** one unique `Hey Rally, …` into HackGT13 or tarun devi only.
2. **Poll** up to ~45s for `outbox` `direct_reply` `sent`. Record decision `elapsed_ms` and wall time from send POST to sent. Do not print message text. `uncertain` → inspect chat; no auto-retry.
3. **Patch** payload/routing/latency in `app/agent.py` and `app/orchestrator.py`. Leave a live-iterate agent's uncommitted prompt wording alone unless it is the bug.
4. **Focused pytest** (pick what you touched), e.g. `tests/test_group_conversation_agent.py`, `tests/test_group_conversation_service.py`, `tests/test_agent.py`, `tests/test_service.py`. Automated tests must not send live iMessages.
5. **Reload** uvicorn; `/health`; next probe with **different** text.

**Cap sends.** Default 6 live probes per session. Stop early on allowlist miss, health down, illegal/safety fail-closed, or repeated uncertain delivery.

**Fail closed:** disallowed GUID, missing health, illegal facilitation, malformed model decision, empty allowlist — no send, no “just this once”.

## Admin desk vs public archive

| Surface | What it is | Where |
| --- | --- | --- |
| Admin desk | Local operator UI: allowlisted groups, recent messages, plan, memory, outbox. Secrets masked (`configured` / `missing`). | `http://127.0.0.1:8770/admin/groups?token=<RALLY_ADMIN_TOKEN>` on the Rally Mac. **Not** something to paste in group chat. |
| Public archive | Group page / Vercel snapshot. | In-thread: `Hey Rally, send our page link` → `Our group page: {RALLY_APP_URL}/{public_id}`. Distinct from the admin desk. |

If a member asks for the dashboard in-group, Rally may say the desk is on the Mac and **will not** post the sign-in token in that group (`app/group_admin_commands.py`). You already have the local URL — open it in a browser; do not iMessage the token.

## Common mistakes

| Mistake | Fix |
| --- | --- |
| Echoing `.env` or BlueBubbles URLs with `password=` | Source env; redact in notes. |
| Sending to a name match whose GUID is not allowlisted | Resolve, then check `RALLY_ALLOWED_CHAT_GUIDS`. |
| Probe prefixed `Rally:` | Echo dropped; Rally never “ingests” it. |
| Repeating the same sentence within 15s | Coalesced; change the probe. |
| Fourth reply in one minute | Flood cap; wait. |
| Pasting `/admin/groups?token=…` into iMessage | Local browser only. |
| Asking for the page link when you meant the desk | Page link is the public archive. |
| Enabling Private API / disabling SIP for tapbacks | Out of scope; text path works without it. |
| Claiming extract finished before the reply | Reply first; extract is background. |
| Rewriting a teammate's uncommitted prompt | Measure and patch process/context, not a frozen prompt. |

## Bottlenecks

See [rally-profiling.md](rally-profiling.md). Short version: extract does **not** block the webhook. Grok `decide_conversation` does (10s timeout; a live miss was 26s at the old 25s budget). BlueBubbles send is ~0.6–1.1s after a local recap/dashboard. Same-chat `receive` lock is held across decision+send. `helper_status` is cached (15s) but live `any;+;` GUIDs fail GUID checks before that GET. Prompt size (~7KB) is not the cost.

## Related

- Run/start: [README.md](../README.md)
- Group turns, memory, flood, reactions: [group-conversation.md](group-conversation.md)
- Receive-path profile: [rally-profiling.md](rally-profiling.md)
- BlueBubbles setup: [demo.md](demo.md)
- Conversation design: [superpowers/specs/2026-09-26-rally-group-conversation.md](superpowers/specs/2026-09-26-rally-group-conversation.md)
