# Final demo audit

## Latest status — 2026-09-27

Bookkeeping after the authorized HackGT web text in [docs/live-web-text-check.md](live-web-text-check.md). No second text, call, deploy, or commit. No product code was edited, and the full suite was not rerun. Pid 440 was not restarted.

| Item | Latest |
| --- | --- |
| Live web group delivery | Verified. One BlueBubbles probe `B890F64B-FF5B-43DE-9994-98DC91ADFCA1` has one outbox `direct_reply`, `sent`, unprefixed, citing `https://www.python.org/downloads/release/python-3147/`. Reply guid `51A56A11-1EB3-4DC0-AC41-959B47A9A3BF`. Outbox is 197 `sent`. |
| Health | Pid 440 is the only listener on `127.0.0.1:8770`. `GET /health` is HTTP 200 `{"status":"ok"}`. Process env `RALLY_PORTAL_PUBLISH_APPROVED=0`. |
| Local snapshot | `scripts.export_portal --output data/portal_build` exit 0: `{'groups': 3, 'pages': 135, 'media': 970}`. Directory mtime 2026-09-27 08:38:36 EDT. `git check-ignore` matches it. No upload. |
| Database | Size 6479872 bytes and mtime 2026-09-27 08:37:38 local were the same before and after that export. |
| Snapshot privacy | Top level is `index.html`, `vercel.json`, `.vercelignore`, and the three group directories. No `.env`, no SQLite file, no direct-chat directory. |
| Layout | Same headless Chromium measurement as the historical section below, `PLAYWRIGHT_BROWSERS_PATH` unset. No new test. 1280×800 and 390×844: no horizontal overflow, h1 and five section headings visible on all three pages. |
| Remaining approval | Public archive upload only. Vercel was not fetched again and was not updated. Publication stays 0. |

Current import rows, read before the export. The history line is `imported_count`, not the archive row count.

| Public id | Status | `imported_count` | Cursor | Error | Updated (UTC) | Archive rows | Snapshot line |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `C3JgCmCfInFygNDeMdKM3rHBFFr8kERN` | complete | 380 | 367 | empty | 2026-09-27 12:33:07 | 382 | History imported · 380 messages |
| `NTWi6v0vn-0eEj5qjFbX2X6b8pg8ktaP` | pending | 10833 | 6800 | empty | 2026-09-27 12:37:38 | 10833 | History import pending · 10833 messages |
| `t2aw0RjkAHme8l3kX-HudmKjLxw0Kox3` | complete | 2134 | 2118 | empty | 2026-09-27 12:36:37 | 2134 | History imported · 2134 messages |

The direct chat's import is `complete` at 441 archive rows. It was not exported. HackGT archive rows 382 include the probe and the reply. The counter 380 was written at 12:33:07 UTC, before that send at 12:34:59 UTC, so the status line is two behind the archive. The HackGT pages contain `[Rally web test]`, `3.14.7`, and the official release URL. Each group index lists History, Media, Plans, Analytics, Members, and Activity as Shown.

The second group's pending state was already written by the running importer at 12:37:38 UTC. This bookkeeping pass did not change it.

## Historical check

Checked 2026-09-27, with a follow-up the same day after `docs/live-recovery-check.md`. No product code was edited. The full suite was not run again. No text was sent in that follow-up, no call was placed, nothing was deployed, and that follow-up did not write the production database except by running the existing portal export, which reads it and writes ignored `data/portal_build`. Pid 440 was left running. The rows below are the record of that pass. The latest status section is the current one.

## Commands

```text
.venv/bin/python -m pytest -q --tb=line
```

Still the latest run, from the first pass, with no code change since: `790 passed`, `57 subtests passed`, one Starlette `DeprecationWarning` (`anyio.abc.BlockingPortal`), 10.17s, exit 0.

```text
.venv/bin/python -m compileall -q app tests scripts
git diff --check
```

Both exited 0 on that pass. `git diff --check` printed nothing.

Follow-up export:

```text
.venv/bin/python -m scripts.export_portal --output data/portal_build
```

Exit 0. Result: `{'groups': 3, 'pages': 135, 'media': 970}`. Directory mtime 2026-09-27 10:02:28 UTC. No upload.

## Requirement by requirement

| Requirement | Result |
| --- | --- |
| Real group text, prefix-free send, echo | Confirmed from stored rows. One HackGT probe guid `937809A1-C35A-4575-A0E2-0DCD0FD8B9AD` has one outbox `direct_reply`, `sent`, length 4, unprefixed, body exactly `pong`. History guid `16A4E3A8-792C-4569-936B-67E91CF97794` is that same body, `is_from_me` 1 in the archive. Outbox is 195 `sent`. 21 older `direct_reply` rows still start with `Rally:`. No new text was sent. |
| Logged-out public browser | Confirmed in `docs/integration-demo-check.md`. A process with `PLAYWRIGHT_BROWSERS_PATH` unset opened `https://example.com/` logged out: title `Example Domain`, owner context unset. `docs/live-recovery-check.md` repeated that after the durable browser start. The server route on pid 440 was still `running` false. This follow-up did not restart it. |
| Public web answer | Historical for this table: confirmed in `docs/integration-demo-check.md` on a temp database, with no group delivery in that pass. Latest group delivery is verified in the status section above and in `docs/live-web-text-check.md`. |
| Restaurant discover, terms, authorization, dry-run, role outcome | Confirmed by the suite (`tests/test_demo_end_to_end.py`, `tests/test_vapi.py`, restaurant tests). No live call was placed because this task was told not to place one. That is an instruction, not an open product gap. |
| Three local dashboards | Historical snapshot below was 378 / 10833 / 2134, all imported. Latest local snapshot is in the status section: 380, pending 10833, and 2134. |
| Three public dashboards | Historical and still the last public check. Vercel root was HTTP 200. HackGT was HTTP 200, cache HIT, `History imported · 165 messages`. The other two group URLs were 404. Upload remains unapproved. This bookkeeping pass did not fetch or upload. |
| HackGT allowlist | Confirmed. Allowlist is 4 chats: 3 groups and 1 direct. Guid `any;+;chat536074477903103142` is present. |
| Bounded recovery leaves current plans unchanged | Confirmed. See the plan-order correction below. |
| Portal import that had been pending at 2134 | Confirmed complete. Cursor `2118`, count 2134, error empty, updated 09:52:36 UTC. A read-only BlueBubbles fetch at that cursor returns 0 messages. |

## Plan order, not a recovery change

`Store.get_plan` is `SELECT * FROM plans WHERE chat_id=? ORDER BY rowid DESC LIMIT 1`. The earlier note in `docs/demo-state-audit.md` listed ABANDONED v20 for `t2aw0RjkAHme8l3kX-HudmKjLxw0Kox3`. That row is the highest version. It is not the row `get_plan` returns.

Read-only comparison of `data/backups/rally-pre-live-recovery-20260927T095357Z.sqlite3` (6471680 bytes, the pre-apply backup) and the current database. Plan id hash, version, state, facts SHA-256, `last_human_at`, and plan-row count match on all four chats, and they match the preflight and after tables in `docs/live-recovery-check.md`.

| Chat hash | Public id | `get_plan` | Highest version row |
| --- | --- | --- | --- |
| `1003f1df01ff` | `C3JgCmCfInFygNDeMdKM3rHBFFr8kERN` | rowid 1, ALIGNMENT v19, id `a565e9ecb4d3` | same row |
| `0c19b3a5ac7f` | `NTWi6v0vn-0eEj5qjFbX2X6b8pg8ktaP` | rowid 8, SPARK v13, id `f5391c5878da` | same row |
| `27f4ac3cb10f` | `t2aw0RjkAHme8l3kX-HudmKjLxw0Kox3` | rowid 20, SPARK v7, id `1709f0f13bd9`, `last_human_at` 2026-09-27 05:56:54.645000 UTC | rowid 9, ABANDONED v20, `last_human_at` 2026-09-27 05:36:38.596000 UTC |
| `dff3dab5282a` | direct, id omitted | rowid 13, SPARK v3, id `ef8ed3cddeab` | rowid 10, ABANDONED v5 |

SPARK v7 / `1709f0f13bd9` was already current in the backup, before `recover_pending --apply`. Recovery did not change it. The earlier ABANDONED v20 label was a different row, the highest version, not `get_plan`'s current row. No plan facts were printed.

## Import count 375 and archive rows 378

The history line is `imported_count` from the last `set_import_state`. That value is `COUNT(*)` of `portal_messages` at that write. It is not the analytics "Messages" count, which drops empty text and reactions.

At the first pass, HackGT `C3JgCmCfInFygNDeMdKM3rHBFFr8kERN` was `complete` at 08:57:38 UTC with `imported_count` 375, while `portal_messages` had 378 rows. Three of those rows have `sent_at` after 08:57:38 UTC, so they were archived after that import write. The status line was the counter from the completed import, not a live total. Webhook and live-thread upserts do not rewrite `imported_count`.

A later import write, read before this export, set the same group to `complete`, cursor `365`, `imported_count` 378, `updated_at` 2026-09-27 10:00:40 UTC. Archive rows are 378, of which 5 are reactions and 0 are deleted. The analytics message count is 366. The fresh snapshot line is `History imported · 378 messages`, which matches the archive row count. The earlier 375 versus 378 gap was the frozen import counter versus rows added after it.

`t2aw0RjkAHme8l3kX-HudmKjLxw0Kox3` remains `complete` at cursor 2118 and count 2134. `docs/live-recovery-check.md` saw HackGT as `History import pending · 378` just after pid 440 started. By the export read it was `complete` at 378.

## Historical local snapshot

This is the 10:02:28 UTC export from the earlier pass, before the web text. The current tree is in the latest status section.

That tree contained `index.html`, `vercel.json`, `.vercelignore`, and the three group directories. It did not contain `.env`, a SQLite file, or the direct chat's directory.

Each group `index.html` starts with `<!doctype html>`, has `<h1>Group chat</h1>`, title `Group chat · Rally`, five section ids, six `Shown` labels, a viewport meta tag, and both `@media (max-width: 700px)` and `@media (max-width: 480px)`.

| Public id | Status line |
| --- | --- |
| `C3JgCmCfInFygNDeMdKM3rHBFFr8kERN` | History imported · 378 messages |
| `NTWi6v0vn-0eEj5qjFbX2X6b8pg8ktaP` | History imported · 10833 messages |
| `t2aw0RjkAHme8l3kX-HudmKjLxw0Kox3` | History imported · 2134 messages |

Playwright opened those three files with `PLAYWRIGHT_BROWSERS_PATH` unset, the same headless Chromium measurement used in `docs/portal-demo-check.md`. No new test was added.

| Viewport | Pages | Horizontal overflow | h1 and five section headings visible |
| --- | --- | --- | --- |
| 1280×800 | 3 | no (`scrollWidth` 1280 = `clientWidth` 1280) | yes |
| 390×844 | 3 | no (`scrollWidth` 390 = `clientWidth` 390) | yes |

## Remaining approval

Historical gap list from the earlier pass: automatic review had rejected both public archive upload and one extra live web-search text. The web-search text is no longer a permission block. It was sent once and verified in `docs/live-web-text-check.md`.

The only remaining approval is public archive upload. Local pages are ahead of the last Vercel check (HackGT cache HIT at 165 messages; the other two group URLs 404). This pass did not upload. `RALLY_PORTAL_PUBLISH_APPROVED` stays 0.

A live phone call is outside this task's instructions. Restarting the listener and the recovery database writes were outside this check's scope; the other workers already did the authorized restart and the authorized recovery. Those are not open permission blockers.
