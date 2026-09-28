# Portal demo check

## Webhook archive and live route exclusion — 2026-09-27 05:08

Allowlisted group messages are written to the portal archive before the restaurant or browser handler can return. The same message id is upserted once per request. Direct chats and relationship-private chats are skipped by group history import and by the live portal, media, and history (`before`) routes. Browser, voice, and private owner routes are unchanged.

A combined run of `tests/test_portal_http.py`, `tests/test_browser_http.py`, `tests/test_browser_integration.py`, `tests/test_relationship_http.py`, and `tests/test_voice_caller.py` was 38 passed and 1 failed. The failure was the new test constructing a reservation inbound without `caller`. After pointing that test at `browser_inbound` only, `tests/test_portal_http.py` passed 5 tests. No calls, texts, or deploy.

```text
.venv/bin/python -m scripts.export_portal --output data/portal_build
{'groups': 3, 'pages': 135, 'media': 970}
data/rally.sqlite3  1790500046  2026-09-27 05:07:26
data/portal_build   1790500138  2026-09-27 05:08:58
```

The snapshot is newer than the database. All three group pages have `<h1>Group chat</h1>`, all six sections Shown, and all five section headings. Import lines: History imported · 375, History imported · 10833, History imported · 2134. Upload still needs explicit approval.

Checked 2026-09-27. Nothing was deployed. `scripts.publish_portal` was not run, the Vercel CLI was not invoked, and `RALLY_PORTAL_PUBLISH_APPROVED` was not set.

No command in this pass was denied. The default Playwright Chromium launch failed because the browser binary was not installed (`BrowserType.launch: Executable doesn't exist` under the sandbox Playwright cache). The same check then launched Playwright with `channel="chrome"` and succeeded.

## Tests

```text
.venv/bin/python -m pytest -q tests/test_export_portal.py tests/test_publish_portal.py tests/test_dashboard_live.py tests/test_portal_view.py tests/test_portal_store.py tests/test_portal_http.py --tb=short
33 passed, 1 warning in 1.11s
```

The warning is Starlette's existing `anyio.abc.BlockingPortal` deprecation.

Member labels are the stored display names. Phone numbers and emails are not rewritten. Portal section flags are the stored settings. The extra label hashing added earlier was removed before this export.

## Local snapshot

```text
.venv/bin/python -m scripts.export_portal --output data/portal_build
{'groups': 3, 'pages': 135, 'media': 970}
```

Immediately after that command:

| Path | mtime |
| --- | --- |
| `data/rally.sqlite3` | `1790499561` · 2026-09-27 04:59:21 |
| `data/portal_build` | `1790499591` · 2026-09-27 04:59:51 |

The snapshot directory is newer than the database. The running app can write the database again after this; that later write is not part of this export.

Four chats are allowlisted. Three are groups and were exported. One is a direct chat and was omitted. No relationship-source chat was in the allowlist. The snapshot has those three group directories and no extra group directory. `index.html`, `vercel.json`, and `.vercelignore` are present. No `.env` file and no SQLite file are in the tree.

Stored titles are empty, so each page heading is the existing default `Group chat`, and `<h1>Group chat</h1>` is present. All six section settings are on, and each page says History, Media, Plans, Analytics, Members, and Activity are Shown.

| Import line | Messages |
| --- | --- |
| History imported | 375 |
| History import pending | 10826 |
| History imported | 2134 |

Each page includes Conversation history, Rally plans, Group analytics, Rally activity, and Portal settings.

Privacy scan of the text files, without copying matches into this note:

- `rel_texts` rows of at least 40 characters: 0, so none could appear.
- Direct-chat `portal_messages` texts of at least 40 characters that also appear in the snapshot: 26. Of those, 24 are the same text stored on an allowlisted group, and 2 are substrings of an allowlisted group message. No direct-chat directory was written.
- Direct-chat live `messages` texts of at least 40 characters that also appear in the snapshot: 20, all also stored on an allowlisted group.
- Of 15 non-placeholder `.env` values checked, one value occurs in the snapshot. It is `RALLY_BROWSER_OWNER_SENDER_ID`, and that value is the existing member label `local-imessage-account` (6159 occurrences). It is not an API key.

## Desktop and mobile

Playwright opened each of the three local `index.html` files in headless Chrome.

| Viewport | Pages | Horizontal overflow | h1 and five section headings visible |
| --- | --- | --- | --- |
| 1280×800 | 3 | no (`scrollWidth` 1280 = `clientWidth` 1280) | yes |
| 390×844 | 3 | no (`scrollWidth` 390 = `clientWidth` 390) | yes |

That measurement was on the 04:58:10 snapshot, which had the same export summary (`groups` 3, `pages` 135, `media` 970) and the same three import lines as the 04:59:51 snapshot.

## Live read-only URLs

`GET https://rallyplans.vercel.app/` returned **200**. The body is the landing page (`Ask Rally in your group chat`).

The three current local public paths were fetched with `GET` and were not modified:

| Local import line | Live HTTP | Live page |
| --- | --- | --- |
| History imported · 375 messages | 200 | `History imported`, `<h1>Group chat</h1>`, all five section headings |
| History import pending · 10826 messages | 404 | no portal headings |
| History imported · 2134 messages | 404 | no portal headings |

The live responses contained none of the relationship-text, direct-text, or `.env` needles described above. The two 404s are current local pages that are not on production. Publishing them would be a new deployment and was not done.

## Still required before any deploy

A person has to approve uploading this snapshot. Until then, do not set `RALLY_PORTAL_PUBLISH_APPROVED`. The manual command remains in [Vercel deployment operations](vercel-deployment.md).
