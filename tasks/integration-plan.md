# Integration plan

Updated 2026-09-27 from the live check in `docs/integration-demo-check.md`. This follow-up writes that doc, this file, and the one `.env` publish line. Recovery and the old venue planner stay with their owners.

## Current runtime

- [x] Revalidate pid 82576 as the only `127.0.0.1:8770` listener, stop only that process, and start detached pid **92478** (PPID 1, state `Ss`) with `RALLY_PORTAL_PUBLISH_APPROVED=0` and `--no-access-log`. Log: `data/runtime-8770.log`. Stdin is `/dev/null`.
- [x] `GET /health` returns HTTP 200 `{"status":"ok"}`.
- [x] Browser admin route is 403 without a token and 200 with the token. Server browser `running` is false.
- [x] Three allowlisted group pages return HTTP 200 HTML. The direct chat returns 404.
- [x] Scheduler stays on (`schedule=True`, tick 60). Reconcile sends a result only when `reconcile_calls` is nonzero. Pending Vapi calls were 0.
- [x] BlueBubbles `new-message` webhook points at `http://127.0.0.1:8770/webhooks/bluebubbles` with a token configured. Token not recorded.
- [x] Vapi assistant and phone number return HTTP 200 on GET. No call was placed.
- [x] Logged-out `BrowserRuntime` opened `https://example.com/` (title Example Domain) in a headless Chromium context. A second context did not see the probe cookie. The owner profile was not opened.
- [x] `env -u PLAYWRIGHT_BROWSERS_PATH .venv/bin/python -m playwright install chromium` exited 0. Chromium 1243 is in `~/Library/Caches/ms-playwright`. A clean process with that variable unset started `BrowserRuntime`, opened Example Domain, and did not open the owner profile.
- [x] `.env` `RALLY_PORTAL_PUBLISH_APPROVED` is `0`. Only that line changed. Pid 92478 was left running and `GET /health` stayed HTTP 200.
- [x] Temp-database `build_service` `web_answer_fn` called xAI `web_search` once (HTTP 200, 13586 ms) for the official Python release. Answer: Python 3.14.7, source `https://www.python.org/downloads/release/python-3147/`. No send, no webhook, no production database write. Live group delivery stays unverified.

## Leave for later

- [ ] Rerun the full suite after the venue follow-up is done. Root will trigger the final verifier. Last recorded result is 770 passed in `docs/demo-readiness-audit.md`. This check did not rerun it.
- [ ] The next normal server start should leave `PLAYWRIGHT_BROWSERS_PATH` unset so it uses `~/Library/Caches/ms-playwright`. Pid 92478 still has its sandbox path until that restart.
- [ ] Recover the 71 unprocessed human rows with the other worker's prefix plan. Do not mark them processed from here.
- [ ] Finish the pending group import (`t2aw0RjkAHme8l3kX-HudmKjLxw0Kox3`, 2134 messages) without publishing.
- [ ] Place a Vapi call only after a person asks. Callback number is unset, and the factory caller is not in dry-run.
- [ ] Send a live group web-search text only after a person asks. The provider lookup is done. Group delivery is not. The previous automatic review rejection still stands.

## Out of scope here

- No texts, no calls, no Vercel deploy, and no manual production database edits.
- Do not edit the recovery script or the old venue planner.
- Do not force an automatic-review rejection.
