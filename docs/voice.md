# Voice relationship check-in (Grok Voice)

A private, owner-only browser page lets you talk to Rally about your
relationships: "who am I falling behind with", "I haven't seen Jake in a
while, figure something out", "remind me to call Grandma every week". It
runs alongside the existing group-planning and relationship-reminder
features and does not change how either of those behaves.

## How it works

The browser connects **directly** to xAI's realtime voice API over a
WebSocket; your long-lived `RALLY_XAI_API_KEY` never leaves the server. Rally
mints a short-lived (5 minute) ephemeral token for each session instead:

```
Browser --(POST /voice/session)--> Rally server --(mints token)--> xAI
Browser --(wss, ephemeral token)---------------------------------> xAI
```

When the model wants to call a tool, xAI sends the request back over that
same WebSocket to the browser, which relays it to `POST /voice/tool` on the
Rally server. The server runs the tool against the real SQLite-backed
relationship and plan state and returns a JSON result, which the browser
hands back to xAI so the model can keep talking. The browser itself never
reads the database directly.

Reference: [xAI Voice Agent API](https://docs.x.ai/developers/model-capabilities/audio/voice-agent),
[Ephemeral Tokens](https://docs.x.ai/developers/model-capabilities/audio/ephemeral-tokens).

## Setup

1. Set `RALLY_ADMIN_TOKEN` to a random secret (already generated in this
   repo's `.env`) and `RALLY_XAI_API_KEY` to a valid key.
2. Set `RALLY_VOICE_ENABLED=1`.
3. Optionally set `RALLY_VOICE_OWNER` (default `local-imessage-account`,
   matching the relationship reminders owner — see
   [relationship setup](relationship-setup.md)) and `RALLY_VOICE_MODEL`
   (default `grok-voice-latest`).
4. Start Rally on port 8770, the port BlueBubbles uses on this Mac (see
   [README.md](../README.md)), then open
   `http://127.0.0.1:8770/voice?token=<RALLY_ADMIN_TOKEN>`
   in a desktop browser on the same Mac and click **Start talking**. The
   first click prompts for microphone permission.

A phone browser will refuse microphone access over plain HTTP; this page is
built for local use on the Mac running the server, over `127.0.0.1`.

## What the voice agent can actually do

| Tool | Effect | Backed by |
|---|---|---|
| `list_attention` | read | Real relationship cadences (`app/relationships/store.py`) + real stalled group plans (`app/store.py`). Follow-up/commitment detection is separate teammate work (see [team ownership](team-ownership.md)) and always returns empty, clearly labeled, until that lands. |
| `get_person` | read | Real relationship record and recent contact history. |
| `set_intention` | read* | Creates/updates a relationship cadence — the same effect as the existing `remind me to call Mom every week` iMessage command. Requires reminders to be configured first ([relationship setup](relationship-setup.md)). |
| `check_plan_status` | read | Looks up the real group plan linked to a person through an existing `rel_sources` mapping. |
| `find_hangout_slot` | read | **Stub.** Calendar availability is separate teammate work and is not connected. Always reports unavailable rather than inventing a free time. |
| `propose_message` | read | Drafts an iMessage to a person's linked conversation. Does not send it. |
| `nudge_plan` | read | Prepares running Rally's existing stalled-plan check on a person's linked conversation. Does not run it. |
| `confirm_action` | **commitment** | Executes a previously drafted `propose_message`/`nudge_plan` action by ID: sends the real iMessage, or runs the real planning check. This is the only tool with a real side effect, and it only ever acts on an already-displayed draft — never on text the model invents in the moment. |

"Linked conversation" means a person has an active row in `rel_sources`
pointing at a specific BlueBubbles chat GUID — the same mechanism used for
selecting a private learning source. Without that link, `check_plan_status`,
`propose_message`, and `nudge_plan` report that plainly instead of guessing
which group chat you mean.

## Demo script

```
You: "Yo, who should I catch up with this week?"
Rally: (calls list_attention) "You haven't confirmed contact with Jake in
        a while, and there's a stalled dinner plan in a group he's in."
You: "Draft a message to Jake asking about Thursday."
Rally: (calls propose_message) "Here's the draft: 'Hey, dinner Thursday?'
        Want me to send it?"
You: "Yeah, send it."
Rally: (calls confirm_action) "Sent."
```

## Restaurant reservation calls

### Vapi outbound calls

For an explicit addressed call request in an allowed chat, Rally dials the
requested valid phone number through Vapi. Vapi hosts the phone
audio, so this path does not depend on Phone.app, BlackHole, or the Mac voice
worker. Rally reports that the call started, then checks Vapi for a final
transport status and posts one follow-up in the same chat. An accepted or
ended call does not establish that the person answered or that a booking
happened. The saved Vapi assistant cannot read Rally's private app data yet.

Dial order in `ReservationCaller.run` when a destination number is present:

1. A restaurant-booking request stays in the restaurant brief and, once authorized, dials through Vapi. The phone number comes from a fetched public page, then Browser Use, then the local browser reader. That lookup does not use Geoapify.
2. Any other request with a destination number dials Vapi when Vapi is configured.
3. Twilio runs only when Vapi was not selected. `can_place_pstn_call` also requires `audio_bridge_ready()`, which currently returns false, and it accepts only the Continuity test number.
4. Continuity Phone.app runs only after Vapi and Twilio both decline, and only for its allowlisted test number.

To set it up, create or select a Vapi assistant, then connect an
outbound-capable phone number in Vapi. Vapi's free phone numbers cannot place
outbound calls. Put the private key, assistant ID, and phone number ID in the
ignored `.env` as `RALLY_VAPI_API_KEY`, `RALLY_VAPI_ASSISTANT_ID`, and
`RALLY_VAPI_PHONE_NUMBER_ID`. Do not put the key in chat or commit it. The
assistant's model and voice are configured in Vapi; this integration does not
send the local `grok-voice-latest` realtime stream into a Vapi call.

The separate test helper remains pinned to `+16785991244`: run
`python scripts/place_vapi_call.py` to validate local configuration and
show the destination without calling. Run
`python scripts/place_vapi_call.py --place` to place one call. The command
prints the Vapi call ID and initial provider status; check that ID in the Vapi
dashboard for the subsequent outcome. `--number` rejects any number other
than `+16785991244`.

For example, `Rally, call +16785991244` uses the app workflow when configured.
Rally will not claim a reservation until a separate confirmation exists.

References: [Vapi outbound calling](https://docs.vapi.ai/calls/outbound-calling),
[create a call](https://docs.vapi.ai/api-reference/calls/create), and
[get call status](https://docs.vapi.ai/api-reference/calls/get).

### Restaurant reservations

A group request such as `Hey Rally, reserve a table at Carbone` or
`Hey Rally, call Taj and book...` does not book through the browser and does
not use the local demo loopback as a real reservation. Rally:

1. Searches public results, then fetches the result page. A phone counts only
   when that fetched page names the restaurant. If a city was requested, that
   page must also name the city, even when it publishes only one number.
   New York, NYC, and Brooklyn match one another. A city that is only in the
   request is not treated as printed on the page. A search snippet is not a
   verified number. If the homepage has no single number, Rally follows
   contact or location links. When a Browser Use client is configured, Rally
   asks it to open a page past the homepage and then fetches that URL itself.
   Two published locations become a location question, not a request for the
   group to type a phone number.
2. The saved brief has an exact date, time (`7:30pm` or `19:30`), timezone,
   party size, and reservation name. `tonight`, `tomorrow`, and a month and
   day without a year are resolved from the clock once the timezone is known.
   A named city such as New York, or one city on the fetched page, supplies
   that timezone. The reply shows the resolved date and zone before any yes.
   The owner name and callback number come only from the message or, for the
   callback, `RALLY_CALLBACK_NUMBER` when that value is already configured.
   Rally asks when either is absent. It does not use the voice-owner account
   id as a person's name, and it does not reuse the restaurant number as the
   callback.
3. Replies with that brief and waits for an explicit yes in the same chat
   (`yes`, `place the call`, `go ahead`). A later booking message in that
   chat updates the open brief unless the restaurant name changes. Another
   chat, or a yes that also changes a term, does not authorize the old brief.
   The dial claim is saved before the provider POST. A claim that never
   receives a provider id is reported for a manual Vapi check and is not dialed
   again.
4. Saves the brief in `restaurant_call_snapshots` before any dial. The Vapi
   create-call body passes `assistantOverrides` for that snapshot: the opening
   line is `I am calling on behalf of [owner]...`, the system prompt does not
   volunteer an AI label, and a direct question about automation is answered
   truthfully. The saved relationship-check-in assistant is not the script for
   this call. Ordinary `Rally, call +1...` requests still use that assistant
   and do not require this brief.
5. After the call ends, reports **booked** only when a restaurant-side turn
   (user, customer, or host in the Vapi messages, or a speaker-labeled
   transcript) confirms the saved party, date, time, guest, and venue and
   speaks a real confirmation code. Assistant narration, unlabeled text, and
   structured model output do not confirm. The word `set` is not a code.
   `ended` by itself stays **unresolved**.

Set `RALLY_VAPI_API_KEY`, `RALLY_VAPI_ASSISTANT_ID`, and
`RALLY_VAPI_PHONE_NUMBER_ID` before a real authorized call. There is no
fixed destination list in the app. The helper `scripts/place_vapi_call.py`
remains limited to `+16785991244` and is separate from this workflow. This
tree's dry-run path builds the override payload and does not POST it.

See [restaurant demo check](restaurant-demo-check.md).

### Mac Phone call pipeline

This is the Continuity fallback after Vapi and Twilio decline. With Vapi configured, an explicit destination number dials Vapi first. `Hey Rally, call 7032004231` reaches Phone.app only when that fallback is the one selected:

1. Open Phone.app with `tel://` (allowlisted number only).
2. Rally clicks **Click to Call** itself (green chip, top-right).
3. Attach Grok Voice on this Mac (`grok-voice-latest`): mic in, speakers out.

Nothing is booked unless a live host gives a real confirmation. Cards are never invented. iPhone Mirroring cannot originate calls — do not use it.

Without a number (or Continuity off), Rally uses the mock-host loopback and still never completes a booking.

Dev helper: `scripts/place_test_call.py --method phone` (or `--dry-run`).

### Twilio fallback

Vapi is the PSTN path used for configured outbound calls. Twilio is the next branch, and it stays closed while `audio_bridge_ready()` is false. When that gate is opened, Twilio still accepts only the Continuity test number and needs:

| Key | Role |
|---|---|
| `RALLY_TWILIO_ACCOUNT_SID` | Twilio account |
| `RALLY_TWILIO_AUTH_TOKEN` | Twilio auth |
| `RALLY_TWILIO_FROM_NUMBER` | Caller ID Twilio number (E.164) |
| `RALLY_CALLBACK_NUMBER` | Number Rally gives the restaurant |
| `RALLY_APP_URL` | Public **https** origin Twilio can reach for `/voice/call/twiml` and `wss://…/voice/call/stream` |

`127.0.0.1` / localhost cannot receive Twilio media. Point `RALLY_APP_URL` at
a public HTTPS tunnel (or deployed host), include the restaurant's number in
the text (Rally will not invent one), then reload 8770.

The Mac loopback page (`/voice/call?token=…`) uses the same ephemeral-token
path as `/voice`, with reservation instructions and `wait_for_human` /
`report_reservation_result` tools.

## Known limitations (unverified without a live browser + microphone)

This was built and tested against the real relationship/plan/orchestrator
code with fakes standing in for the browser and the xAI socket (see
`tests/test_voice_tools.py`). Verified live against the real xAI API on
2026-09-26: `POST /voice/session` successfully minted a real ephemeral
token (the `value` field in xAI's response) and `POST /voice/tool` executed
a real `list_attention` call. The following still have not been exercised
end-to-end with a live microphone and browser WebSocket, because that
requires an actual browser session:

- The WebSocket connection itself, `session.update`, and the function-call
  event round-trip over that socket.
- Audio round-trip quality (resampling to/from 24kHz PCM16 in-browser).
- Barge-in behavior if you start talking while Rally is still speaking (the
  current page does not cancel in-flight playback on interruption).

Try it once with real credentials before demoing, and watch the on-page log
panel — it shows every tool call and result live.
