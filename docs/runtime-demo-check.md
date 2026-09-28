# Runtime demo check

Labeled live text check for the Rally process on port 8770. This file records what was actually run. It does not mean the product is fully ready.

## Rules for this check

- Send only to the HackGT group identified from BlueBubbles chat metadata.
- Do not print secrets, webhook tokens, or private message text.
- Start the server with `RALLY_PORTAL_PUBLISH_APPROVED=0` so portal publication stays off.
- Do not place phone calls and do not deploy to Vercel.
- One labeled probe. If delivery is uncertain, inspect before any retry.

## Outbound text

Rally sends the original body text with no `Rally:` prefix. Case is preserved, including confirmation codes. `add_rally_signature` and `send_message` remove a legacy prefix and do not add one.

Echo handling:

- An owner `isFromMe` text that starts with `Rally:` is accepted unless its guid or temp guid is a known bot send.
- A confirmed guid or temp guid Rally sent is ignored for six hours.
- Identical text is ignored only until the send response returns a message id, and for at most 60 seconds when that id is missing. After the id is known, the owner can send the same words again.
- Another self-sent text, such as the labeled probe, is still a human message.

Remembered send ids are stored in `outbound-echo.json` next to the Rally database as hashes and guids only.

## Steps

1. Query BlueBubbles chats read-only and match a group display name containing HackGT. Add that GUID to `RALLY_ALLOWED_CHAT_GUIDS` only when exactly one group matches and it is absent.
2. Listen on `127.0.0.1:8770` with portal publish forced off. `GET /health` must return `{"status":"ok"}`.
3. Post one unique `Hey Rally, ...` probe to that group through BlueBubbles.
4. Record health, server pid, outbox kind/status, whether the sent body starts with `Rally:`, and whether a second reply was queued. Do not record message text.

## Results

Recorded 2026-09-27. One labeled HackGT13 text was sent after the user clarified that BlueBubbles texting is allowed and phone calls are not.

| Check | Result |
| --- | --- |
| Focused tests | `159 passed, 1 warning, 2 subtests passed` in 2.70s. Files: `tests/test_bluebubbles.py`, `tests/test_message_text.py`, `tests/test_config.py`, `tests/test_planning_bot_acceptance.py`, `tests/test_browser_integration.py`, `tests/test_service.py`, `tests/test_relationship_http.py`. |
| Port 8770 before start | Nothing listening (`lsof` exit 1). No server to reuse. |
| HackGT metadata | BlueBubbles chat query status 200, 500 chats scanned, one group display name `HackGT13`, guid `any;+;chat536074477903103142`. It was absent from the allowlist. Only that GUID was appended. Allowlist count is now 4. |
| Server | Pid `68946` later exited. A replacement pid `71119` was used for the labeled text below, then that process was replaced. |
| Chat before send | Latest messages had no `runtime prefix check` probe. |
| Labeled send | Same BlueBubbles text POST, status 200. Probe guid `937809A1-C35A-4575-A0E2-0DCD0FD8B9AD`. |
| Reply | Outbox row 194, `direct_reply`, `sent`, `prefixed` 0, 4 characters. Later history message `16A4E3A8-792C-4569-936B-67E91CF97794` is `isFromMe`, `prefixed` 0, and exactly `pong`. Decision `elapsed_ms=1246`, send `elapsed_ms=721`. |
| Echo | One outbox row after the probe. One decision and one send in the server log, then a webhook of `0.015` seconds with no second decision. |

No phone call was placed and nothing was deployed.

## Previous process

Checked after the restaurant worker finished. Pid `76871` was confirmed listening on `127.0.0.1:8770` and was stopped. The replacement was detached uvicorn pid `80000`, session leader, with stdout and stderr appended to `data/runtime-8770.log`. It was started with `RALLY_PORTAL_PUBLISH_APPROVED=0`. `GET /health` returned `{"status":"ok"}` HTTP 200. The `.env` file still contains `1`.

`/browser/status` was 403 without a token and 200 with the browser admin token: `running` false, `installed` true, `channel` chrome, `backend` browser-use. All three allowlisted group pages returned HTTP 200 HTML, including HackGT13 `C3JgCmCfInFygNDeMdKM3rHBFFr8kERN`.

`python -m scripts.browser_verify` used the configured Browser Use backend and printed `backend=browser-use title=Example Domain ok=true`. No BlueBubbles text and no phone call were sent for that check. Those network checks were not repeated in the final verification below.

## Current process

Final verification 2026-09-27. Pid `80000` was the only listener on `127.0.0.1:8770`. Its command was `.venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8770 --no-access-log`, cwd `/Users/tarun/workspace/recents/Rally`, and `RALLY_PORTAL_PUBLISH_APPROVED=0`. SIGTERM stopped only that process; it exited in about 2 seconds and the port was free. The replacement is detached uvicorn pid **82576**, PPID 1, PGID 82576, session leader (`Ss`). Stdout and stderr append to `data/runtime-8770.log`. It was started with `RALLY_PORTAL_PUBLISH_APPROVED=0` and `--no-access-log`. The log shows process `80000` shutdown and process `82576` startup complete.

`GET /health` returned HTTP 200 `{"status":"ok"}`.

`Settings.from_env()` loaded in Python with the same publish override, without printing keys: `portal_publish_approved` False. The `.env` value is still `1`. Allowlist count is 4, of which 3 are groups. HackGT13 guid `any;+;chat536074477903103142` is present. Its local page is `C3JgCmCfInFygNDeMdKM3rHBFFr8kERN`.

`/browser/status` returned 403 without a token. With the browser admin token it returned HTTP 200: `running` false, `installed` true, `profile` configured, `channel` chrome, `backend` browser-use.

All three allowlisted group pages returned HTTP 200 `text/html` and begin with `<!doctype html>`:

| Group | Public id | HTTP |
| --- | --- | --- |
| HackGT13 | `C3JgCmCfInFygNDeMdKM3rHBFFr8kERN` | 200 |
| other allowlisted group | `NTWi6v0vn-0eEj5qjFbX2X6b8pg8ktaP` | 200 |
| other allowlisted group | `t2aw0RjkAHme8l3kX-HudmKjLxw0Kox3` | 200 |

Full suite this run: `760 passed`, `57 subtests passed`, one Starlette deprecation warning, 9.59s. `.venv/bin/python -m compileall -q app tests scripts` exit 0. `git diff --check` exit 0. No product or fixture files were edited.

Two approvals are still outstanding:

- Reviewed Vercel public history snapshot upload. This process keeps `RALLY_PORTAL_PUBLISH_APPROVED=0`.
- Extra live read-only web-search test text. It was not sent.

No phone call was placed, no BlueBubbles text was sent, and nothing was deployed or committed.
