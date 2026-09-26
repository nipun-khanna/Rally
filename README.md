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

## Test with code

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m scripts.demo_smoke
```

The smoke script exercises plan state, automatic intervention, proposal, explicit approval, mock reservation, and final report with fixed local fixtures. It makes no external calls. Live BlueBubbles, Grok, and Geoapify calls require credentials and are separate from this local smoke check.

Optional Google Calendar creation is documented in [docs/calendar.md](docs/calendar.md). It is disabled by default and requires approval that explicitly includes adding a calendar event.
