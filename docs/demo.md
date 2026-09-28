# Rally demo and integration setup

## Prerequisites

1. Run BlueBubbles Server on an available Mac with iMessage signed in. Configure its new-message webhook to reach this backend: `http://127.0.0.1:8770/webhooks/bluebubbles?token=<RALLY_WEBHOOK_TOKEN>` when both processes run on the same Mac. Rally on this Mac listens on port 8770. If they run on different machines, use an HTTPS address reachable from the Mac. BlueBubbles [documents webhooks and REST password authentication](https://docs.bluebubbles.app/server/developer-guides/rest-api-and-webhooks.md).
2. Create a Grok API key in the [xAI Console](https://console.x.ai/) and make sure the xAI account has API credits. The model is the one paid API allowed by this project. Set `RALLY_XAI_API_KEY` and, if needed, `RALLY_GROK_MODEL` in the ignored local `.env`, then restart Rally. Cursor credits do not pay for xAI API calls. Grok's [structured output](https://docs.x.ai/developers/model-capabilities/text/structured-outputs) drives fact extraction and venue selection.
3. Create a free Geoapify API key and set `RALLY_GEOAPIFY_API_KEY`. The [free plan](https://www.geoapify.com/pricing/) currently offers 3,000 credits per day without a credit card. Rally defaults to 100 geocoding or place requests per UTC day and stops at that local limit.
4. Set a random `RALLY_WEBHOOK_TOKEN`, BlueBubbles server URL and password, and `RALLY_DEFAULT_CITY` plus `RALLY_TIME_ZONE`. Put these in `.env` and export them before starting Rally. Never paste credentials in the group chat.

Rally does not create an iMessage identity. BlueBubbles sends as the Apple account signed into Messages on its server Mac. To make Rally appear as its own group member, use a dedicated Apple account signed into Messages in a separate macOS user session or on a dedicated Mac, then add that account's iMessage address to the group. [BlueBubbles documents separate macOS users](https://docs.bluebubbles.app/server/basic-guides/multiple-users-on-the-same-mac). Using your existing Messages account instead makes Rally's messages appear to come from you.

Install BlueBubbles Server from its [official server download](https://bluebubbles.app/downloads/server/) and complete its macOS permission and server-password setup. In BlueBubbles, enable a `new-message` webhook pointing to Rally's `/webhooks/bluebubbles?token=...` endpoint. Find the exact group-chat GUID from BlueBubbles' chat query or an incoming webhook and set `RALLY_ALLOWED_CHAT_GUIDS` to it. The setting is empty by default, so Rally cannot act in unrelated groups. Start with one test group. BlueBubbles can use its standard send path for Rally's plain text messages; the optional Private API is not required.

Start Rally with the command in [README.md](../README.md). Use `GET /health` as a code-level readiness check. Configure BlueBubbles to POST new-message events to the webhook URL. The BlueBubbles server's Mac must remain awake and connected.

To test direct address after configuring Grok, send `Hey Rally, what's the plan?` in the allowlisted group. Rally checks each incoming human group message for an explicit call to its name and replies in the same thread using that group's saved plan and recent conversation. Ordinary planning messages still update plan state without an immediate reply. While using your current Messages account, Rally's reply appears to come from you. Outbound text keeps its original wording and does not add a `Rally:` prefix. Rally drops the echo of its own send when the incoming guid or temp guid matches a remembered send, for six hours. Until that id is known, identical text is dropped for at most 60 seconds. A later owner message with a new id is accepted, including one that still begins with `Rally:`. Keep `Rally, book it` separate from an approval: only a later `Book it.` response to a pending proposal authorizes the demo reservation.

## Scripted live iMessage flow

Use a 3–8 person iMessage group. Set `RALLY_STALL_MINUTES=1` and `RALLY_TICK_SECONDS=5` for the demo. Keep `RALLY_DEMO_MODE=1` if you want the manual trigger; its eligibility check is identical to the scheduler's. Set `RALLY_DEMO_VENUES=0` for live Geoapify search. For a repeatable venue result, set `RALLY_DEMO_VENUES=1`; Rally then labels the venue data as a demo fixture.

Have four distinct members send a short conversation about a specific upcoming Friday, for example:

```text
Nick: Dinner Friday, October 2?
Sarah: I'm down. Anything except sushi.
Alex: Same. I can't until after 7.
Maya: I'll join too. Midtown?
```

The exact date must be an upcoming Friday when the demo runs. Wait at least the configured stall threshold after the final human planning message. Rally should post a single proposal in that same group. A member then replies `Book it.` Rally should create one **demo reservation** and post the confirmation in the group. The debug view at `/debug?chat_id=<URL-encoded BlueBubbles group GUID>&token=<RALLY_WEBHOOK_TOKEN>` shows the stored facts, blocker, state, and confidence. The demo-only `POST /demo/evaluate?chat_id=<GUID>&token=<TOKEN>` can run the same eligibility check when staging an already quiet plan.

For an offline code check with no accounts, run `python -m scripts.demo_smoke`. It prints JSON with `state: DONE`, two outgoing messages, one mock reservation, and elapsed time. This verifies the coordination path but does not prove a live iMessage delivery or model response. Reset the offline demo by running it again; it uses a fresh temporary SQLite database. Use a new group chat for each fresh live demo.

## Failure behavior

For a browser fallback, prepare the synthetic offline replay before the presentation:

```sh
.venv/bin/python -m scripts.demo_smoke --output-dir data/demo_replay
.venv/bin/python -m http.server 8792 --bind 127.0.0.1 --directory data/demo_replay
```

Open `http://127.0.0.1:8792/blocked.html` and use the three stage links. Each page
states that extraction and venues are fixed fixtures and that booking is simulated.
The replay uses a fresh temporary database, upcoming Friday, cited synthetic source
messages, and a sushi candidate rejected by Rally's real cuisine filter. It exercises
proposal, explicit approval, and local delivery state; it does not prove live model
extraction, iMessage transport, or real venue availability. No private history is exported.

For the live demo, keep the authenticated local `/debug` page open and refresh after
proposal and approval. It shows source quotes from the recent same-chat messages;
older references outside that window are labeled unavailable. The hosted group portal
is a static snapshot and should not be used to demonstrate immediate state changes.

If venue search fails or the free request cap is reached, Rally does not invent a venue. A definite local delivery failure stays in SQLite's outbox for a later attempt; retrying delivery does not rerun the reservation. A BlueBubbles error or lost response is marked `uncertain` and is **not automatically retried** because the message may already have reached iMessage. Inspect the group thread before resolving or retrying it. If the mock reservation fails, the plan stays unresolved and is not automatically retried. A changed venue, time, date, or party size invalidates its pending proposal and needs fresh approval. An unapproved proposal expires after 24 hours.
