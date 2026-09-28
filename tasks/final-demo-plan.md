# Final demo verification plan

**Goal:** Record the demo requirement by requirement from the current tree, the recovery backup, and the local portal snapshot.

**This pass:** Docs, one local export, and a viewport measurement of that snapshot. No product edit, no second full suite, no listener restart, no text, no call, no upload, and no production-database write beyond the existing export's read.

## Checks

- [x] Full suite once: 790 passed, 57 subtests passed, one Starlette deprecation warning, 10.17s, exit 0. Code has not changed, so it was not rerun.
- [x] `compileall` and `git diff --check` exited 0 on that pass.
- [x] Allowlist is 4 chats, 3 groups and 1 direct, including the HackGT13 guid.
- [x] Earlier pong is one unprefixed `sent` `direct_reply`. Outbox is 195 `sent`.
- [x] Logged-out `example.com` and the public web lookup are recorded in `docs/integration-demo-check.md`.
- [x] Restaurant discover, terms, authorization, dry-run, and role outcome are covered by the suite. No live call was part of this task.
- [x] `t2aw0RjkAHme8l3kX-HudmKjLxw0Kox3` import is `complete` at cursor 2118 and count 2134. BlueBubbles at that cursor returns 0.
- [x] `Store.get_plan` is `ORDER BY rowid DESC`. SPARK v7 / `1709f0f13bd9` is that row in both the pre-recovery backup and the current database. ABANDONED v20 is an older, higher-version row. Recovery did not change plans.
- [x] HackGT 375 was the import counter frozen at 08:57:38 UTC. Three archive rows are newer than that write. A later import write set the counter to 378, matching the archive row count. The fresh snapshot says `History imported · 378 messages`.
- [x] `.venv/bin/python -m scripts.export_portal --output data/portal_build` wrote 3 groups, 135 pages, and 970 media files. Direct chat is absent. Desktop 1280×800 and mobile 390×844 show no horizontal overflow, with the h1 and five headings visible.
- [ ] Public archive upload. Automatic review rejected it. Vercel HackGT is still 165 messages, and the other two group URLs are 404.
- [ ] Extra live web-search group text. Automatic review rejected it. The provider lookup was not delivered to a group.
- [ ] Production demo goal complete. The two items above are still open.
