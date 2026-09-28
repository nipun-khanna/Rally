# Integration demo check

Checked 2026-09-27. This file records the live process on port 8770, the scheduler and BlueBubbles webhook metadata, Vapi readiness, and one logged-out browser open of `https://example.com/`.

No BlueBubbles text was sent. No Vapi call was placed. Nothing was deployed. No SQL write was issued from this check. The full suite was not rerun. `docs/demo-readiness-audit.md` records the browser-fix suite as 770 passed. There is no `AGENTS.md` in this repo. Recovery and the old venue planner were left to their owners.

## Process

Pid **82576** was revalidated before it was stopped. It was the only listener on `127.0.0.1:8770`, PPID 1, PGID 82576, state `Ss`, command path `.venv/bin/python`, cwd `/Users/tarun/workspace/recents/Rally`, started Sun Sep 27 05:24:42 2026 local. Its argv matched `uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8770 --no-access-log`. Its environment had `RALLY_PORTAL_PUBLISH_APPROVED=0`. `app/browser/agent.py` and `app/browser/runtime.py` were both modified at 05:38:32 local, after that process started.

SIGTERM stopped only pid 82576. The port was free. No other process was signaled.

The replacement is pid **92478**, PPID 1, PGID 92478, state `Ss`, started Sun Sep 27 05:45:20 2026 local. At the confirmation snapshot it had been up 2m28s and was still the only listener on `127.0.0.1:8770`. The argv match, cwd, and publish override are the same as 82576. Stdin is `/dev/null`. Stdout and stderr append to `data/runtime-8770.log`. Those descriptors are the log file. Pid 82576 was gone.

`GET /health` returned HTTP 200 `{"status":"ok"}`.

The log gained the 82576 shutdown lines and the 92478 startup lines through `Uvicorn running on http://127.0.0.1:8770`. The file was 896 bytes and 20 lines at the confirmation snapshot, with no traceback, failure, or publication line.

`.env` now has `RALLY_PORTAL_PUBLISH_APPROVED=0`. That was the only line changed: line 26, from `1` to `0`, in a 51-line file. Every other line is unchanged. The file was not printed. With `RALLY_PORTAL_PUBLISH_APPROVED` unset in the process, `Settings.from_env()` loads `portal_publish_approved` false. Pid 92478 still has its own process value `0` and was left running.

The browser modules above are older than pid 92478, so this process loaded them.

## Scheduler and reconcile

`create_app` defaults `schedule=True`. The factory command does not pass `schedule=False`, so the lifespan starts `periodic` and an initial history import. Each tick waits `tick_seconds` (60 in the loaded settings), runs the scheduled checks, then `ReservationCallInbound.reconcile_calls`. `deliver_pending` runs only when that reconcile count is nonzero.

Read-only SQLite at the start of this check had 0 pending Vapi calls and 0 unidentified dialing claims. The outbox had 195 `sent` rows and no other status. A reconcile tick would not send a text from those tables.

The restarted process did run its own importer. `t2aw0RjkAHme8l3kX-HudmKjLxw0Kox3` stayed `pending`, count 2134, error empty, and its `updated_at` moved to 2026-09-27 09:47:46 UTC. The other two group import rows stayed `complete` at their earlier timestamps (08:57:38 UTC and 09:07:26 UTC) with counts 375 and 10833 and empty errors.

## BlueBubbles webhook

BlueBubbles base URL is `http://127.0.0.1:1234/`. Password is present and was not printed. `GET /api/v1/server/info` returned status 200. Server version 1.9.9, `private_api` false, `helper_connected` false. The info payload has no webhook URL.

`~/Library/Application Support/bluebubbles-server/config.db` is the same file as the `BlueBubbles-Server` path. The `webhook` table has one row, created 2026-09-26 04:53:13, events `["new-message"]`. The URL is `http://127.0.0.1:8770/webhooks/bluebubbles` with a nonempty `token` query parameter. The token was not printed.

## Vapi and caller

Loaded settings, with no secret values printed:

| Item | Result |
| --- | --- |
| Vapi key, assistant id, phone-number id | All present. `VapiDialer.ready()` is true |
| `GET /assistant/{id}` | HTTP 200, model provider `xai`, model `grok-4.3` |
| `GET /phone-number/{id}` | HTTP 200, provider `twilio`, number present |
| Factory `ReservationCaller.dry_run` | False. This check did not call `place_call` |
| Twilio dialer | Not ready |
| `audio_bridge_ready()` | False |
| Continuity dialer on this Mac | Ready. Restaurant dialing uses Vapi |
| `RALLY_CALLBACK_NUMBER` | Absent |
| `RALLY_VOICE_ENABLED` | Off |
| xAI key | Present |
| Geoapify key | Absent |
| Demo mode and demo venues | Off |
| Allowlist | 4 chats, 3 groups |
| History, browser, web search, adaptive | Enabled |
| App URL host | `rallyplans.vercel.app` |

## Browser

`GET /browser/status` without a token returned 403. With the browser admin token it returned 200: `running` false, `installed` true, `profile` configured, `channel` chrome, `backend` browser-use. The server browser was not started. `installed: true` on that route means the Playwright package imports. It does not mean the browser binary is present.

Google Chrome is installed. Playwright's bundled Chromium was missing. `BrowserRuntime.start(headed=False)` raised `Chromium is not installed` before any navigation. Logged-out browsing uses `chromium.launch()` with no Chrome channel, and `start()` requires the bundled binary before that launch. The owner profile path can use the Chrome channel. It was not opened.

Chromium was then downloaded for this session's Playwright cache. A separate headless process, using the current `BrowserRuntime`, opened the public page:

| Check | Result |
| --- | --- |
| `start(headed=False)` | `running` true, backend `local` |
| Navigate `https://example.com/` with `authenticated=False` | `status` ok, title `Example Domain`, final URL `https://example.com/`, body contains Example Domain |
| Owner context | `_open_owner_context` was not called. Owner context and owner page stayed unset |
| Second logged-out chat | Separate page and context, title `Example Domain` |
| Isolation | Cookie `rally_iso` set on the first context was absent from the second |
| Browser Use | Not called |
| Server `/browser/start` | Not called |

## Durable Chromium

Playwright resolves the browser directory in this order: `PLAYWRIGHT_BROWSERS_PATH=0` uses the package `.local-browsers` directory; any other set value is used as the directory; an unset variable uses `~/Library/Caches/ms-playwright`. This check did not set the variable to `0` and did not add an app config key.

The three paths differ:

| Environment | `PLAYWRIGHT_BROWSERS_PATH` |
| --- | --- |
| Pid 92478 | `/var/folders/7c/fqz723l90xq_4qtsl037j6s40000gn/T/cursor-sandbox-cache/7dd87d83b4f15acc7c113ca20c2364e3/playwright` |
| This shell | `/var/folders/7c/fqz723l90xq_4qtsl037j6s40000gn/T/cursor-sandbox-cache/766ddbe20c7857ab012587b2baf41c8f/playwright` |
| Variable unset | `/Users/tarun/Library/Caches/ms-playwright` |

```text
env -u PLAYWRIGHT_BROWSERS_PATH .venv/bin/python -m playwright install chromium
```

The child reported the variable unset and the command exited 0. Chromium 1243 was already in the default cache, so this run did not download another copy. The executable is a Mach-O 64-bit arm64 binary at `chromium-1243/chrome-mac-arm64/Google Chrome for Testing.app`, and that app bundle is 621686512 bytes. The cache also contains `chromium-1187`, `chromium-1194`, `chromium_headless_shell-1187`, `chromium_headless_shell-1194`, and `chromium_headless_shell-1243`.

A second process was started with `PLAYWRIGHT_BROWSERS_PATH` and `RALLY_PORTAL_PUBLISH_APPROVED` both unset. `BrowserRuntime.start(headed=False)` used the default-cache executable (`runtime_exe_under_default_cache` true, `runtime_exe_in_sandbox` false). Logged-out navigation of `https://example.com/` returned title `Example Domain` and URL `https://example.com/`. The owner opener was not called. A second ephemeral context did not receive cookie `rally_iso`. The browser process was stopped afterward.

Pid 92478 was not restarted. It still points at its sandbox cache. A normal start that leaves `PLAYWRIGHT_BROWSERS_PATH` unset uses the durable cache above. At the follow-up snapshot that process was still the only listener, PPID 1, state `Ss`, up 6m16s, and `GET /health` was HTTP 200 `{"status":"ok"}`.

## Public web answer

This check called the configured web function on a temporary database. It did not submit a BlueBubbles webhook, did not send a text, and did not open the production database. Live group delivery of a web answer stays unverified. An earlier automatic review rejected that extra group text.

`should_search_web` is true for the question below, which is the same predicate `_priority_command_answer` uses before `web_answer_fn(message.text, tone=group_tone(messages))`. That call forwards the addressed text and a local tone label. It does not forward the message list. This check did not call `receive` or `_priority_command_answer`, so nothing was delivered.

Path: `Settings.from_env` with `database_path` replaced by a temp SQLite file, `allowed_chat_ids` replaced by one synthetic chat, and `portal_publish_approved` false, then `build_service`, then `service.web_answer_fn`, then `GrokWebClient.answer`, then `POST https://api.x.ai/v1/responses`.

`build_service` added no threads. `RallyService._pool` stayed unset. No HTTP request ran during construction. Send, attachment, reaction, typing, and history fetch were replaced with guards that raise. None of them ran. The production database mtime and size were unchanged. The temp database was removed afterward. Web search is enabled, the xAI key is present, `RALLY_WEB_DAILY_LIMIT` is 0, and `RALLY_WEB_MAX_TOOL_CALLS` is 3.

Question: `What is the official latest stable Python release, and what is its source page on python.org?`

| Check | Result |
| --- | --- |
| Provider | HTTP 200, body status `completed`, 13586 ms |
| Model | `grok-4.7` |
| Tools | `[{"type": "web_search"}]`, `store` false, `max_tool_calls` 3 |
| Input roles | `system`, `user`. The user text was only that question |
| Output types | two `web_search_call` items, then a `message` |
| Search queries | `official latest stable Python release python.org`; `Python 3.14.7 release source download site:python.org` |
| Answer | Latest stable is Python 3.14.7 (Aug 5, 2026). Source page: `https://www.python.org/downloads/release/python-3147/` |
| Extra citations | `https://blog.python.org/2026/08/python-3147-31315/` and other public python.org and blog.python.org URLs |

A separate GET of `https://www.python.org/downloads/release/python-3147/` returned HTTP 200 and the page contains `Python 3.14.7`. The authorization header was present on the provider request and was not printed.

## Group pages

All three allowlisted group pages returned HTTP 200 `text/html`, begin with `<!doctype html>`, and include `<h1>Group chat</h1>`:

| Public id | HTTP | History line |
| --- | --- | --- |
| `C3JgCmCfInFygNDeMdKM3rHBFFr8kERN` | 200 | History imported · 375 messages |
| `NTWi6v0vn-0eEj5qjFbX2X6b8pg8ktaP` | 200 | History imported · 10833 messages |
| `t2aw0RjkAHme8l3kX-HudmKjLxw0Kox3` | 200 | History import pending · 2134 messages |

The allowlisted direct chat returns HTTP 404. Its public id is omitted here.

Read-only count of human rows with `processed=0`: 71. No row was marked processed.

## Gaps

- The public archive was not uploaded. The earlier automatic review that rejected that upload still stands. `.env` and pid 92478 both keep publication off.
- Live group delivery of a web answer is still unverified. The earlier automatic review that rejected that group text still stands. The provider lookup above had no delivery.
- Pid 92478 still has the sandbox `PLAYWRIGHT_BROWSERS_PATH` from when it started. Its HTTP status `installed: true` still means the Playwright package imports. A normal start with the variable unset uses `~/Library/Caches/ms-playwright`.
- The example.com checks ran in separate processes. The server's own browser runtime is still `running` false.
- 71 human rows remain unprocessed. The state audit still describes windows above the recovery cap. That recovery belongs to the other worker.
- One group import is still `pending` at 2134 messages. Local pages for the other two groups are ahead of the last recorded Vercel snapshot in `docs/demo-state-audit.md`. This check did not fetch Vercel again.
- Vapi credentials answer read-only GETs, and the factory caller is not in dry-run. An authorized group `yes` could dial. Callback number is unset, the voice page is off, Twilio is not ready, and the Private API helper is disconnected.
- Geoapify is unset and demo venues are off, so the old planner `search()` raises `PlacesError` before Geoapify. The restaurant phone path does not use that lookup. That planner was not edited.
- The full suite waits until the venue follow-up is done. Root will trigger the final verifier.
