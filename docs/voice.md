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
4. Start the app, then open `http://127.0.0.1:8000/voice?token=<RALLY_ADMIN_TOKEN>`
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

Allowlisted chats can ask Rally to **call the restaurant** and book a table.
Grok Voice (`grok-voice-latest`) does the live back-and-forth. Rally then
texts the group `booked`, `need confirm`, or `failed`. It will not say
booked unless a live phone call produced a confirmation code.

Example: `Hey Rally, call Taj and book for 4 at 8` (or the same ask during
the five-minute Rally turn). Party size, time, name, and callback number
come from the message, the current plan/proposal, or `RALLY_CALLBACK_NUMBER`.

### Mac Phone call pipeline (no Twilio)

`Hey Rally, call 7032004231` is one path:

1. Open Phone.app with `tel://` (allowlisted number only).
2. Rally clicks **Click to Call** itself (green chip, top-right).
3. Attach Grok Voice on this Mac (`grok-voice-latest`): mic in, speakers out.

Nothing is booked unless a live host gives a real confirmation. Cards are never invented. iPhone Mirroring cannot originate calls — do not use it.

Without a number (or Continuity off), Rally uses the mock-host loopback and still never completes a booking.

Dev helper: `scripts/place_test_call.py --method phone` (or `--dry-run`).

### What is needed to actually dial

True PSTN outbound uses Twilio:

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
