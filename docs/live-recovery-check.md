# Live recovery check — 2026-09-27

Bounded pending extraction for the three allowlisted groups that still had unprocessed human rows. The configured extractor ran through `scripts/recover_pending.py run --apply --limit 200`. The command’s send function was the CLI `no_send` guard. This run did not call `receive`, did not send a BlueBubbles text, did not place a call, did not deploy, and did not upload an archive. No product code was edited. The full suite was not run. Auto-review allowed the apply command; it was not bypassed.

Message text, raw ids, and secrets are not copied here. Group labels are SHA-256 prefixes (12 hex digits). Set digests are the first 16 hex digits of SHA-256 over the sorted raw pending ids, the same digests as `docs/demo-state-audit.md`.

## Preflight

Read-only, before any backup or stop. Allowlist size 4. Extractor provider `grok`. Pending Vapi calls 0. Unidentified dialing claims 0. `voice_call_attempts` and `restaurant_call_snapshots` were empty. Outbox was 195 rows, all `sent`.

Pid **92478** was the only listener on `127.0.0.1:8770`. PPID 1, PGID 92478, state `Ss`, started Sun Sep 27 05:45:20 2026 local. Command path `.venv/bin/python`, argv `uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8770 --no-access-log`, cwd `/Users/tarun/workspace/recents/Rally`. `RALLY_PORTAL_PUBLISH_APPROVED=0`. Stdin was `/dev/null`. Stdout and stderr were `data/runtime-8770.log`.

Each group below had every pending human id inside the ordered 200-message prefix that starts at the oldest pending row, and a processed human row sorted after that prefix. That is the chronology guard: recovery can ack the prefix and must not call `save_plan`. The fourth allowlisted chat had no pending rows, so it was not passed to the command.

| Chat hash | Prior set digest | Pending | Inside prefix | Outside prefix | Prefix length | Window | Prefix end (UTC) | Newer processed human after prefix |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `0c19b3a5ac7f` | `5da4acc0c551a2cc` | 2 | 2 | 0 | 200 | 218 | 2026-09-27T04:11:41.545000+00:00 | yes |
| `27f4ac3cb10f` | `21d78f0a8b1918a7` | 6 | 6 | 0 | 200 | 237 | 2026-09-27T05:45:20.552000+00:00 | yes |
| `1003f1df01ff` | `5fda3cde6e5f48db` | 63 | 63 | 0 | 200 | 237 | 2026-09-27T06:27:27.503000+00:00 | yes |
| `dff3dab5282a` | none | 0 |  |  | 0 | 0 |  |  |

Diagnostics on the pending rows, with no message text: `0c19b3a5ac7f` had one `extract` / `validation` and one `unknown` / `not_recorded`. `27f4ac3cb10f` had six `unknown` / `not_recorded`. `1003f1df01ff` had 63 `unknown` / `not_recorded`.

Plans at preflight, current row only:

| Chat hash | Plan id hash | Version | State | Facts SHA-256 | `last_human_at` | Plan rows | Proposal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `0c19b3a5ac7f` | `f5391c5878da` | 13 | SPARK | `2581fa997faf5662b7e4b350825e71c60945c0b4bd576a29fe6949296cf14ca6` | 2026-09-27T04:49:20.124000+00:00 | 7 | no |
| `27f4ac3cb10f` | `1709f0f13bd9` | 7 | SPARK | `73b1c306f03da4b143546bb1d74c53816435ba0935dc00a34cce98600d2798b9` | 2026-09-27T05:56:54.645000+00:00 | 8 | no |
| `1003f1df01ff` | `a565e9ecb4d3` | 19 | ALIGNMENT | `f46aa7558006cfee7ed887f0e95e8805c39a34e56a030952e3d96e167efc50a9` | 2026-09-27T08:58:46.551000+00:00 | 1 | no |
| `dff3dab5282a` | `ef8ed3cddeab` | 3 | SPARK | `b7c537dd6598ee8ac69d23aad980460e1ee03d1f1df045d0be014a8d2bb3bcbc` | 2026-09-27T04:52:50.894000+00:00 | 4 | no |

Outbox by chat, all `sent`: 54, 70, 50, and 21.

The same guard and the same zero call counts were true again immediately before SIGTERM, and again after pid 92478 had exited and the port was free.

## Backup and stop

SQLite backup API, source opened read-only, into `data/backups/rally-pre-live-recovery-20260927T095357Z.sqlite3`. `git check-ignore` matched that path. Integrity check `ok`. Page count 1580, equal to the source. File size 6471680 bytes. The backup was not printed or copied out of `data/`.

SIGTERM went to pid 92478 only. It exited. Nothing else was listening on `127.0.0.1:8770`.

## Apply

Order was the two-row group, then the six-row group, then the 63-row group. Each invocation was `.venv/bin/python -m scripts.recover_pending run --apply --limit 200 --chat-id <that group>`. No model error. No row was updated by hand.

| Chat hash | Exit | Seconds | Pending before | Recovered | Pending after | `sent_messages` |
| --- | --- | --- | --- | --- | --- | --- |
| `0c19b3a5ac7f` | 0 | 19.99 | 2 | 2 | 0 | 0 |
| `27f4ac3cb10f` | 0 | 28.97 | 6 | 6 | 0 | 0 |
| `1003f1df01ff` | 0 | 46.15 | 63 | 63 | 0 | 0 |

Exact total: 71 pending human rows recovered, 0 remaining on the allowlisted chats. The fourth chat stayed at 0 pending and was not part of a model call.

## After

Plan id hash, version, state, facts SHA-256, `last_human_at`, plan row count, and proposal flag match the preflight table on all four chats. Outbox is still 195 `sent` and the per-chat counts are still 54, 70, 50, and 21. Pending Vapi calls 0. Unidentified dialing claims 0. Both call tables still have 0 rows.

## Listener

Pid 92478 is gone. The replacement is pid **99202**, PPID 1, started Sun Sep 27 05:55:32 2026 local. At the final check its state was `S` and its PGID was 99201. Pid 99201 was the intermediate process from the detach and has exited, so 99202 is not the session leader. It is the only listener on `127.0.0.1:8770`. Argv matches `uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8770 --no-access-log`. Cwd is this repo. `RALLY_PORTAL_PUBLISH_APPROVED=0`. Stdin is `/dev/null`. Stdout and stderr append to `data/runtime-8770.log`.

`GET /health` returned HTTP 200 `{"status":"ok"}`.

The log grew through the 92478 shutdown lines and the 99202 startup lines, ending at `Uvicorn running on http://127.0.0.1:8770`. It was 1245 bytes and 28 lines, with no traceback and no publication line. No second server was started.

## Playwright path follow-up

Pid 99202 was still the only listener on `127.0.0.1:8770`. Its `PLAYWRIGHT_BROWSERS_PATH` was a Cursor sandbox cache, not `~/Library/Caches/ms-playwright`. No Python file under the repo was newer than that process. Pending human rows were 0, pending Vapi calls were 0, and unidentified dialing claims were 0. Outbox was 195 `sent`. Both call tables were empty.

SIGTERM stopped only pid 99202. The port was free. The replacement was started with that variable removed from the environment and `RALLY_PORTAL_PUBLISH_APPROVED=0`. The rest of the private environment was not printed or edited. `.env` has `RALLY_PORTAL_PUBLISH_APPROVED=0`.

Pid **440**, PPID 1, PGID 440, state `Rs`, started Sun Sep 27 05:59:27 2026 local. It is the only listener on `127.0.0.1:8770`. `PLAYWRIGHT_BROWSERS_PATH` is absent. Argv matches `uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8770 --no-access-log`. Cwd is this repo. Stdin is `/dev/null`. Stdout and stderr append to `data/runtime-8770.log`. Pid 99202 is gone.

`GET /health` returned HTTP 200 `{"status":"ok"}`.

`GET /browser/status` without a token returned 403. With the browser admin token it returned 200: `running` false, `installed` true, `profile` configured, `channel` chrome, `backend` browser-use. The server browser was not started. The token was not printed.

All three group pages returned HTTP 200 `text/html`, begin with `<!doctype html>`, and include `<h1>Group chat</h1>`:

| Public id | HTTP | History line |
| --- | --- | --- |
| `t2aw0RjkAHme8l3kX-HudmKjLxw0Kox3` | 200 | History imported · 2134 messages |
| `NTWi6v0vn-0eEj5qjFbX2X6b8pg8ktaP` | 200 | History imported · 10833 messages |
| `C3JgCmCfInFygNDeMdKM3rHBFFr8kERN` | 200 | History import pending · 378 messages |

Read-only after the restart: allowlisted pending human rows 0, outbox 195 `sent`, pending Vapi calls 0, unidentified dialing claims 0, call-attempt rows 0, restaurant snapshot rows 0.

A separate process used the same publish value and had `PLAYWRIGHT_BROWSERS_PATH` unset. `BrowserRuntime.start(headed=False)` used a temporary profile directory, not the owner profile. The Chromium executable resolved under `~/Library/Caches/ms-playwright` and not under a sandbox cache. Logged-out navigation of `https://example.com/` returned status ok, title `Example Domain`, and that URL. The owner opener was not called. Owner context and owner page stayed unset. The browser process was stopped afterward. The server route stayed `running` false.

The log gained the 99202 shutdown lines and the 440 startup lines through `Uvicorn running on http://127.0.0.1:8770`. It was 1592 bytes and 36 lines, with no traceback and no publication line. No second server was started. No text was sent, no call was placed, nothing was deployed, and the full suite was not run.
