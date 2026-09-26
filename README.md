# Rally

Rally helps an iMessage group finish a plan: it understands the chat, notices a stalled decision, suggests a venue, waits for approval, and posts a clearly labeled **demo reservation**. Product requirements are in [PRD.md](PRD.md), implementation behavior in [SPEC.md](SPEC.md), and build tasks in [tasks/todo.md](tasks/todo.md).

## Run locally

Use Python 3.13. Create an environment and install the pinned runtime packages:

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set the credentials. Export its variables before starting the server; `.env` is ignored by Git. BlueBubbles needs a running Mac server and a group-chat webhook. Grok requires an xAI key. Geoapify offers a free places and geocoding tier; Rally caps its own requests at 100 per UTC day by default. Only Grok is allowed to incur API charges. The exact [BlueBubbles setup and demo steps](docs/demo.md) explain the remaining configuration.

```sh
set -a
. ./.env
set +a
.venv/bin/uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

Health: `GET /health`. Incoming BlueBubbles events: `POST /webhooks/bluebubbles?token=<RALLY_WEBHOOK_TOKEN>`. The backend checks the shared token and ignores Rally's own replies, direct-chat, and duplicate messages. Scheduler checks run automatically. The debug view and optional demo trigger require the same token.

In an allowlisted group, a member can ask `Hey Rally, what's the plan?` or `Rally, recap the options.` Rally replies promptly in that thread using the group's recent messages and saved plan. Incidental mentions do not prompt replies. A request to book is answered as a question; only the separate, explicit approval phrase documented below can authorize a reservation. When Rally shares your current iMessage account, your own messages can also address it; Rally-generated replies begin with `Rally:` and are ignored on inbound.

Set `RALLY_ALLOWED_CHAT_GUIDS` to the exact BlueBubbles group-chat GUIDs that Rally may serve, separated by commas. It defaults to an empty set: the live backend will not ingest, schedule, or send for any group until one is configured. See [docs/demo.md](docs/demo.md) for the iMessage identity and group setup.

## Group portal

For each allowlisted group, Rally creates a page at `{RALLY_APP_URL}/{group_id}`. The public `group_id` is random and can be replaced; anyone holding that link can read the page. Set `RALLY_APP_URL` to the reachable base URL before asking Rally to share a link. A localhost URL works for testing on this Mac only.

The portal imports the group's full history available to BlueBubbles, including message text, supported attachments, and reactions. It stores this archive separately from Rally's live planning messages. Import runs in resumable pages in the background, syncs new webhook messages, and rescans the archive hourly for missed or changed messages. The page shows import status and labels unavailable media. Historical messages feed the archive and analytics; they do **not** create Rally plan records or trigger actions.

Ask `Hey Rally, send our page link` in the group. Members can also ask `Hey Rally, hide media on our page`, `show media`, `hide analytics`, `show history`, `hide plans`, `hide members`, `hide activity`, `name our page to Weekend Crew`, `set our page theme to midnight`, or `replace our page link`. After the next publish, the old production path stops working when replaced. Vercel may retain caches or old immutable deployments; the publisher removes its previous deployment, but complete erasure cannot be guaranteed. The portal's older-plan search looks for possible plan mentions in archived messages on demand, labels findings as inferred, and shows supporting messages. It runs locally or in the browser without sending archived messages to an external model. The live backend has a per-group daily search cap and cache. The main plans list contains only plans Rally tracked, along with saved proposal and action outcomes.

`POST /portal/admin/{chat_id}/settings?token=...` and `POST /portal/admin/{chat_id}/import?token=...` provide authenticated local administration. The live backend depends on a persistent SQLite database, local media files, and the Mac-hosted BlueBubbles service. `python -m scripts.export_portal` builds a static snapshot in ignored `data/portal_build` without uploading it. With the group's approval to host its archive on Vercel, set `RALLY_PORTAL_PUBLISH_APPROVED=1` and `RALLY_APP_URL=https://rallyplans.vercel.app`; the running backend publishes changed snapshots about every five minutes using `scripts.publish_portal`. The hosted page is a static snapshot, so the live local page reflects changes first. Vercel serves only the exported page, local search index, and allowed media files, never `.env` or the operational SQLite database. Active attachment formats are downloads with restrictive headers.

## Test with code

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m scripts.demo_smoke
```

Install the test runner with `uv pip install --python .venv/bin/python pytest` (or pip in that environment). Use pytest for the full suite: unittest discovery skips the pytest function tests.

The smoke script exercises plan state, automatic intervention, proposal, explicit approval, mock reservation, and final report with fixed local fixtures. It makes no external calls. Add `--output-dir data/demo_replay` to export labeled browser snapshots; see [the replay steps](docs/demo.md). Live BlueBubbles, Grok, and Geoapify calls require credentials and are separate from this local smoke check.

Optional Google Calendar creation is documented in [docs/calendar.md](docs/calendar.md). It is disabled by default and requires approval that explicitly includes adding a calendar event.
### Public web research

With `RALLY_WEB_ENABLED=1`, addressed public/current-information questions (for example, “Rally, find food nearby”) use xAI web search and return cited URLs in the same iMessage group. Search is read-only; it cannot book, send messages to others, create events, or run code. A persisted daily limit and per-request tool cap control usage. Only the current request and an abstract group-tone label go to this search path. Setup, cost, and limitations: [docs/web-search.md](docs/web-search.md).

### Relationship reminders

Private relationship tracking, reminder scheduling, and selected-conversation
learning are documented in [relationship setup](docs/relationship-setup.md).
Monitoring runs on your Mac without sending selected texts to Grok. Configure a
private destination and choose sources explicitly; neither is enabled by default.
