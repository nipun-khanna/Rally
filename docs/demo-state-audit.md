# Demo state audit

Read-only check on 2026-09-27. No text was sent, no call was placed, and nothing was published. SQLite was opened with `mode=ro`. Keys, chat GUIDs, and message text are omitted.

The full suite was not rerun. No Python file under `app`, `tests`, or `scripts` is newer than this server process. The last recorded result remains `760 passed`, `57 subtests passed`.

## Process

Pid **82576**, PPID 1, PGID 82576, state `Ss`, started Sun Sep 27 05:24:42 local. At the check it had been up 6h36m. It is the only listener on `127.0.0.1:8770`.

Command: `.venv/bin/python .venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8770 --no-access-log`.

`GET /health` returned HTTP 200 `{"status":"ok"}`.

The process environment has `RALLY_PORTAL_PUBLISH_APPROVED=0`. That value overrides the ignored `.env` entry, which is still `1`. A later start that does not set the same override would load publication as approved. This process does not.

`data/runtime-8770.log` contains only Uvicorn lifecycle lines: process 80000 shutdown, then process 82576 startup through `Uvicorn running on http://127.0.0.1:8770`. After 82576 started there are no latency lines, failure warnings, tracebacks, import failures, or publication lines.

## Settings

`Settings.from_env()` was loaded without printing secrets.

| Item | Value |
| --- | --- |
| Allowlist | 4 chats: 3 groups, 1 direct |
| HackGT13 | Present. Public page `C3JgCmCfInFygNDeMdKM3rHBFFr8kERN` |
| History, browser, web search, adaptive | Enabled |
| Voice page | Disabled (`RALLY_VOICE_ENABLED` off) |
| Vapi key, assistant, and phone-number id | All present |
| xAI key | Present |
| Geoapify key | Absent |
| BlueBubbles URL and password | Both present |
| App URL | `https://rallyplans.vercel.app` |
| Demo mode and demo venues | Off |

## Browser

`GET /browser/status` without a token returned 403. With the browser admin token it returned 200: `running` false, `installed` true, `profile` configured, `channel` chrome, `backend` browser-use. The browser was not started.

## Outbox

Allowed chats have no `pending`, `failed`, or `uncertain` rows, and no outbox error text.

| Chat | `direct_reply` sent | `nudge` sent |
| --- | --- | --- |
| HackGT13 | 48 | 2 |
| `NTWi6v0vn-0eEj5qjFbX2X6b8pg8ktaP` | 51 | 3 |
| `t2aw0RjkAHme8l3kX-HudmKjLxw0Kox3` | 67 | 3 |
| Allowlisted direct chat | 18 | 3 |

## Webhook processing

These are stored human rows with `processed=0`. This process has not logged a processing error. Newer human rows in each group are already processed, so these are residual unprocessed rows.

| Chat | Pending | Recorded error | Pending sent_at span (UTC) |
| --- | --- | --- | --- |
| HackGT13 | 63 | none (`not_recorded`, 0 attempts) | 2026-09-26 05:17:23 through 2026-09-27 02:12:57 |
| `NTWi6v0vn-0eEj5qjFbX2X6b8pg8ktaP` | 2 | 1 `extract` / `validation`, no HTTP status; 1 `not_recorded` | 2026-09-27 00:46:58 through 01:02:27 |
| `t2aw0RjkAHme8l3kX-HudmKjLxw0Kox3` | 6 | none (`not_recorded`, 0 attempts) | 2026-09-27 01:39:52 through 01:55:08 |
| Allowlisted direct chat | 0 | none |  |

## Portals

Database mtime is 2026-09-27 05:30:44 local. Static snapshot `data/portal_build` mtime is 2026-09-27 05:08:58 local. The database is newer. The snapshot has the three group directories, `index.html`, `vercel.json`, and `.vercelignore`. It has no direct-chat directory.

The running importer still advances group history while publication is off. A complete import is set back to `pending` once its timestamp is at least one hour old. `t2aw0RjkAHme8l3kX-HudmKjLxw0Kox3` was updated at 2026-09-27 09:30:44 UTC, during this process, with status `pending`, count 2134, and no import error.

| Group | DB status | DB import count | Archive rows | Local page | Snapshot | Vercel |
| --- | --- | --- | --- | --- | --- | --- |
| HackGT13 `C3JgCmCfInFygNDeMdKM3rHBFFr8kERN` | complete, no error, updated 08:57:38 UTC | 375 | 378 | 200, History imported · 375 | History imported · 375 | 200, History imported · 165 |
| `NTWi6v0vn-0eEj5qjFbX2X6b8pg8ktaP` | complete, no error, updated 09:07:26 UTC | 10833 | 10833 | 200, History imported · 10833 | History imported · 10833 | 404 |
| `t2aw0RjkAHme8l3kX-HudmKjLxw0Kox3` | pending, no error, updated 09:30:44 UTC | 2134 | 2134 | 200, History import pending · 2134 | History imported · 2134 | 404 |

Local and snapshot pages are `text/html`, start with `<!doctype html>`, use `<h1>Group chat</h1>`, and show History, Media, Plans, Analytics, Members, and Activity. All six controls say Shown. The same headings and controls are on the one live Vercel group page.

`GET https://rallyplans.vercel.app/` returned 200 and the landing phrase `Ask Rally in your group chat`. The HackGT response was cache `HIT` with age about 7.7 hours. A follow-up GET with `Cache-Control: no-cache` stayed `HIT` and still said 165 messages.

The allowlisted direct chat returns HTTP 404 on the local portal path and on Vercel. Its public id is omitted here.

HackGT's status line says 375 while `portal_messages` has 378. The newest archived row is 2026-09-27 09:14:39 UTC, after the import was marked complete at 08:57:38 UTC and before this process started.

## Doc gaps that are still true in source

- `docs/demo.md` tells BlueBubbles to post to port 8000. `README.md` and this server use port 8770.
- `docs/demo.md` now points the live BlueBubbles webhook at port 8770 and documents the no-prefix echo rules: remembered send ids for six hours, identical text for at most 60 seconds until that id is known, and a later owner message with a new id is accepted. The offline replay server on port 8792 is unchanged.
- `docs/voice.md` now opens the voice page on port 8770 and documents Vapi-first dialing. Twilio stays a closed fallback while `audio_bridge_ready()` is false. Continuity remains after that. The voice page stays disabled until `RALLY_VOICE_ENABLED=1`.
- `docs/restaurant-demo-check.md` and the Vapi section of `docs/voice.md` match the current dial order, the pinned test CLI, and the rule that `ended` alone is not a booking.
- `docs/runtime-demo-check.md` matches this process, the publish override, and the three local group pages. It does not yet include the backlog or the Vercel count of 165.

## Unresolved approvals

- Public history upload. An earlier automatic review rejected it. This process keeps publication off. The Vercel HackGT page is an older 165-message snapshot, and the other two group pages are 404 there.
- One more live read-only web-search text in an allowed group. An earlier automatic review rejected it. It was not sent. Web search is enabled in settings.
- Geoapify is unset and `RALLY_DEMO_VENUES` is off, so the old planner venue lookup in `search()` raises `PlacesError` before it can call Geoapify. The restaurant phone workflow does not use that lookup. `PublicRestaurantLookup` fetches a public page, then Browser Use, then the local browser reader, and an authorized brief dials Vapi. A missing Geoapify key does not block that path. The browser runtime is currently not running, so the local reader is idle until it is started; the public-page fetch does not require it.

## Unprocessed rows — 2026-09-27 follow-up

Read-only. No row was marked processed, and no message text or raw id was copied out. Ids below are SHA-256 prefixes (12 hex digits). Set digests are the first 16 hex digits of SHA-256 over the sorted raw ids.

Live `build_service` sets `defer_heavy_work=True`. `receive` stores the human row first. A direct reply can be sent. Plan extraction then runs on a thread pool. `mark_processed` runs after extraction succeeds. On extraction failure, a row that already has a `direct_reply` is marked processed; a row without one records the diagnostic and stays pending. The scheduler does not call `receive` again. Every pending `sent_at` is before this process started at 09:24 UTC, and this process has no extraction log line. Newer human rows in the same groups are already processed: 54, 72, and 82 after the newest pending row.

| Group | Pending | Window since oldest pending | Default 75 | Max 200 | Processed human inside the span | Plan |
| --- | --- | --- | --- | --- | --- | --- |
| HackGT13 | 63 | 237 | exceeds | exceeds | 49 | ALIGNMENT v19, no proposal |
| `NTWi6v0vn-0eEj5qjFbX2X6b8pg8ktaP` | 2 | 218 | exceeds | exceeds | 96 | SPARK v13, no proposal |
| `t2aw0RjkAHme8l3kX-HudmKjLxw0Kox3` | 6 | 237 | exceeds | exceeds | 5 | ABANDONED v20, no proposal |

Set digests: HackGT13 `5fda3cde6e5f48db`, second group `5da4acc0c551a2cc`, third group `21d78f0a8b1918a7`.

70 rows are `attempts=0`, stage `unknown`, kind `not_recorded`. The failure recorder never ran. 13 of those already have a `direct_reply` outbox row with status `sent` and an empty error: HackGT13 hashes `0a6b4f75d4fc`, `1f9f411ca153`, `2b84846d3f1a`, `34e9f1c2edde`, `3da549ec4971`, `ade1bf7a4359`, `c8b4ca904dba`, `f54087d1de92`, `fecc61160b52`; third group hashes `99f89c09cc32`, `9bfafe8d6a4c`, `aa49f268d373`, `e6266328f445`. Four of the 13 also have a processed `rally-out:{id}` row (3 HackGT13, 1 in the third group). The other 9 were sent and the local echo row was not written. No adaptive request is tied to any of the 71. No current group turn points at them. Reaction rows exist for 2 HackGT13 pending ids and 1 in the third group.

The remaining row is hash `1ad1911b4d5b` in the second group, sent_at 2026-09-27 00:46:58 UTC, text length 16, `attempts=1`, stage `extract`, kind `validation`, HTTP status empty, no outbox row. `validation` is the diagnostic for `ValueError` or `TypeError` from extraction. Deferred work left it pending because it had no direct reply.

`has_unprocessed_prior` would ignore a later `Book it` while any older pending human row remains. None of these plans is `READY` or holding a proposal, so no approval is being dropped today.

`recover_pending` loads every stored message from the oldest pending row forward, sends that window to the extractor, updates the plan when the extracted activity changes, and marks only the pending human ids in the window. It does not send iMessages. The snapshot limit is 1 through 200, and `run` without `--apply` refuses to call the model. All three windows are over 200, so today's command raises `Pending conversation exceeds bounded recovery window` before the extractor and before any `processed` write.

Smallest safe fix, not applied: recover one ordered prefix of at most 200 messages starting at the oldest pending row, call the extractor only for that prefix on an explicit `--apply`, and mark processed only pending human ids inside the prefix. Later pending rows stay for the next explicit run. Do not mark the 13 replied rows processed on their own; their plan extract never finished. Do not run `--apply` until that prefix exists and a person accepts the model call, because it sends stored group text to the extractor.

The production demo goal stays open.
