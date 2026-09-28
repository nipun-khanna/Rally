# Live web-text check

Authorized read-only web-search text in HackGT13. This file is the evidence log. It does not include private chat text or secrets.

## Preflight

Checked 2026-09-27 before the send.

| Check | Result |
| --- | --- |
| Listener | Pid 440 only, PPID 1, PGID 440, state `Ss`, started Sun Sep 27 05:59:27 2026 local. Argv `uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8770 --no-access-log`. Cwd this repo. |
| Publish | Process env `RALLY_PORTAL_PUBLISH_APPROVED=0`. `Settings.from_env()` `portal_publish_approved` false. |
| Health | `GET /health` HTTP 200 `{"status":"ok"}`. |
| Allowlist | 4 chats, 3 groups. Exact guid `any;+;chat536074477903103142` present. |
| HackGT13 | BlueBubbles chat query 200, 500 chats, one display name `HackGT13`, same guid. |
| BlueBubbles | Server info 200, version 1.9.9, `private_api` false, `helper_connected` false. |
| Webhook | One `new-message` row to `127.0.0.1:8770/webhooks/bluebubbles`. Token present, not printed. |
| Web settings | Enabled, daily limit 0, max tool calls 3, xAI key present. |
| Code age | `app/web.py`, `app/orchestrator.py`, `app/main.py`, `app/bluebubbles.py`, and `app/config.py` are older than pid 440. `.env` mtime 05:51:15 local is also older. |
| Queue | Outbox 196 `sent`. Pending human rows 0. This chat's replies in the last minute 0. Restaurant snapshots 0. Voice attempts 0. |
| Address form | Bracket-first label is not a direct Rally call. The probe starts with `Rally,` and includes `[Rally web test]`. `should_search_web` true. Browser, restaurant, and call matchers false. |
| Messages | `Messages` process is running. |

## Send

One BlueBubbles `POST /api/v1/message/text` at 2026-09-27 12:34:59 UTC. The helper did not call `send_message`, so the probe temp guid was not written into the echo file. Auto-review allowed that POST. There was no second send.

| Check | Result |
| --- | --- |
| BlueBubbles | Status 200 in 0.854s. `isFromMe` true. Chat guid matched. Body matched the probe (115 characters). |
| Probe guid | `B890F64B-FF5B-43DE-9994-98DC91ADFCA1` |
| Temp guid | Echoed by BlueBubbles. Absent from `outbound-echo.json`. |
| App row | Human message, `processed` 1, `is_from_rally` 0. |
| Outbox | One `direct_reply`, `sent`, empty error, 706 characters, `prefixed` false. |
| Reply guid | `51A56A11-1EB3-4DC0-AC41-959B47A9A3BF`, `isFromMe` true in history, text equal to the outbox body. That guid is in `outbound-echo.json`. |
| Public fact | Body contains `3.14.7` and `https://www.python.org/downloads/release/python-3147/`. |
| Sources | 4 URL occurrences, all host `www.python.org`. Official release page, the downloads index, and one downloads URL that also carried unrelated query parameters. No chat guid and no phone number in the body. |
| Counts | Outbox 196 `sent` before, 197 `sent` after. No other status. |

## Latency

Wall time from the send POST until the outbox row was `sent` was 38.987s, including a 2-second poll. The webhook that did the work logged `receive_total` 36.711s and `stage=send` 868ms. BlueBubbles delivery of the reply was 0.853s. There was no `stage=decision` line, which is the conversation-model path. This request went through the web-answer branch.

## Echo

A second webhook for this chat waited on the chat lock for 36.698s and then returned. Its `receive_total` was 36.701s, so the work after the lock was a few milliseconds and it did not send. The probe guid is not an echo id. A later webhook of 0.075s matches the remembered reply guid and did not create an outbox row. One send stage, one reply.

## After

Pid 440 was still the only listener. `GET /health` was HTTP 200. Process env `RALLY_PORTAL_PUBLISH_APPROVED=0`. No phone POST, no provider-account update, no deploy, no commit, no archive upload.

## Bookkeeping

Rechecked 2026-09-27 12:38 UTC. No second text. Pid 440 was still the only listener, health HTTP 200, publish 0. The probe still has exactly one `direct_reply` with status `sent`. Outbox is 197 `sent`.

`scripts.export_portal --output data/portal_build` wrote 3 groups, 135 pages, and 970 media. The production database stayed 6479872 bytes with mtime 2026-09-27 08:37:38 local. The snapshot is gitignored. It has no `.env`, no SQLite file, and no direct-chat directory. HackGT pages include the test label, `3.14.7`, and the official release URL. Counts and import lines are in [docs/final-demo-audit.md](final-demo-audit.md). Nothing was uploaded.
