# Live Pending Recovery

Operator run on 2026-09-27. Evidence is in `docs/live-recovery-check.md`.

**Goal:** Finish residual pending group extraction with the existing bounded recovery command, then put the port 8770 listener back.

**Constraints:** No code edits. No `receive` replay. No BlueBubbles text, phone call, deploy, or archive upload. No manual `processed` updates. No full suite. If the chronology guard or a pending call failed, do not apply. If auto-review rejected the apply command, do not bypass it.

- [x] Read `docs/pending-message-recovery.md`, `docs/recovery-demo-check.md`, and `tasks/recovery-plan.md`.
- [x] Read-only preflight: every pending human id in each allowlisted group with pending rows was inside the 200-message prefix, and a newer processed human sorted after that prefix.
- [x] Revalidated pid 92478 as the only `127.0.0.1:8770` listener, with pending Vapi calls 0 and unidentified dialing claims 0.
- [x] Backed up SQLite with the backup API to `data/backups/rally-pre-live-recovery-20260927T095357Z.sqlite3` (gitignored, integrity ok, 1580 pages).
- [x] Stopped only pid 92478. The port was free.
- [x] Ran `scripts.recover_pending run --apply --limit 200` for the three allowlisted groups that had pending rows. Recovered 2, 6, and 63. Each exit code was 0. Pending counts fell to 0. `sent_messages` was 0.
- [x] Plan id, version, state, facts hash, `last_human_at`, and plan row count were unchanged. Outbox stayed 195 `sent`. Call tables stayed empty.
- [x] Restored one detached listener: pid **99202**, PPID 1, `RALLY_PORTAL_PUBLISH_APPROVED=0`, `--no-access-log`, log `data/runtime-8770.log`. `GET /health` returned `{"status":"ok"}`.
- [x] Pid 99202 had a sandbox `PLAYWRIGHT_BROWSERS_PATH`. Pending calls were 0. Restarted only that listener as pid **440** with the variable removed and publish 0. `.env` publish is 0. Health, browser auth, and the three group pages checked. Pending backlog stayed 0 and the outbox and call tables stayed unchanged. A separate logged-out `BrowserRuntime` opened Example Domain from `~/Library/Caches/ms-playwright` without the owner profile.
