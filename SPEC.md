# Rally MVP specification

**Source:** [PRD.md](PRD.md). This document makes implementation choices for the hackathon MVP. If the PRD and this spec differ, the explicit choices confirmed in conversation take precedence: automatic intervention is required; plan memory is long lasting; paid LLM use is allowed; other APIs must have a usable free option.

## Outcome and scope

Rally lives in an iMessage group through BlueBubbles. It notices a promising social plan, understands participants and constraints, detects a blocker after the conversation stalls, proposes one concrete next step, waits for explicit approval, performs an approved reservation through a realistic mock service, and reports the outcome in the same chat. The complete dinner demo should run in under two minutes. The target group has 3–8 people.

P0 includes automatic inactivity intervention, venue search, a lightweight debug view, and a repeatable demo. Calendar creation, Meta/Muse extraction, a polished dashboard, and a real reservation provider remain later enhancements. Payments, food delivery, other messaging platforms, voting, and automatic commitments are outside this MVP.

## Proposed technical shape

- **Backend:** one FastAPI service containing the agent loop, deterministic safety checks, scheduler, and adapters. BlueBubbles remains a thin transport layer.
- **Storage:** SQLite stores message identity, recent history, plans, proposals, approvals, tool results, intervention timestamps, and outbound delivery state. Records survive service restarts. Rally does not automatically erase completed plans or build a cross-chat personality profile.
- **Model:** Grok produces schema-validated extraction and structured action decisions. The backend validates decisions and is the only component permitted to call reservation or messaging tools.
- **Messaging:** BlueBubbles webhooks for incoming group messages and its API for replies in the originating thread. The server requires an available Mac. [BlueBubbles API and webhooks](https://docs.bluebubbles.app/server/developer-guides/rest-api-and-webhooks.md).
- **Places:** Geoapify Places API is the proposed free-tier provider. Its published free plan has 3,000 credits per day and requires attribution; search requests must be capped, cached where appropriate, and stopped before relying on paid access. [Geoapify pricing](https://www.geoapify.com/pricing/), [Places API](https://www.geoapify.com/places-api/). Google Places is excluded because it requires billing. [Google Places billing](https://developers.google.com/maps/documentation/places/web-service/usage-and-billing).
- **Reservation:** a local mock service records an approved reservation and returns a stable confirmation identifier. Messages must label the result as a demo reservation, so nobody mistakes it for a real table booking.
- **Calendar:** optional. If implemented later, choose a free path and check authorization and current quota rules first.

No product dependency may require a paid non-LLM API to complete the MVP. If a free provider fails or reaches its limit, Rally reports that it cannot find a venue; it does not invent one. A seeded, labeled demo fixture may make the stage presentation reliable, while the normal path uses live search.

## Data and interfaces

An incoming `ChatMessage` contains `message_id`, `chat_id`, `sender_id`, `text`, `sent_at`, and `is_from_rally`. A unique message ID prevents duplicate webhook delivery from creating duplicate actions. Keep one active plan per chat for the MVP; another distinct activity may start a new plan after the current one is done or abandoned.

Each `Plan` contains a stable ID, chat ID, goal, activity, interested sender IDs, evidence-backed availability and preferences, objections, normalized date/time and time zone when known, current state, blockers, confidence, last human activity, last intervention, and the pending proposal ID. Preserve both a human-readable signal and the message ID that supports it. Relative dates such as “Friday” must be resolved using message time and the configured chat time zone. Ask when the city or date is genuinely ambiguous.

A `Proposal` fixes the venue, date, time, party size, and chat. It also records its source venue ID, terms version, and status. An `Approval` points to that exact proposal and the approving sender and message. A reservation is keyed by proposal ID so a repeated approval or webhook cannot create a second mock booking. Store separate status for the reservation result and the final outgoing message.

The agent returns structured `WAIT`, `NUDGE`, `ASK`, `PROPOSE`, or `ACT` with a reason, confidence, and any requested tool. `WAIT` is the default. Model output cannot override backend approval checks.

## Plan states and behavior

| State | Meaning | Allowed next behavior |
|---|---|---|
| `SPARK` | An activity was suggested. | Wait for evidence of interest. |
| `INTEREST` | At least two people expressed interest. | Gather constraints or ask one missing essential detail. |
| `ALIGNMENT` | Timing, location, or preferences are being reconciled. | Wait, ask, or search for an option. |
| `BLOCKED` | The group is interested but a decision is missing. | After the stall threshold, nudge, ask, or propose one useful next step. |
| `READY` | A concrete proposal has been sent and awaits approval. | Wait for approval, rejection, or changed terms. |
| `EXECUTING` | A valid approval has been recorded and the tool is running. | Report the result; do not issue another booking for the same proposal. |
| `DONE` | The reservation result and plan have been communicated. | Stop intervening for this plan. |
| `ABANDONED` | The group explicitly cancels or no longer wants the plan. | Stop intervening for this plan. |

State is derived from chat evidence and backend outcomes; the model may suggest a transition, but the backend applies it. Changes to date, venue, party size, or objections invalidate the pending proposal and require a new approval. A plan does not become `DONE` merely because a tool call was attempted.

**Automatic intervention:** a periodic backend job scans active plans. The proposed initial threshold is 30 minutes after the latest human planning message; make it configurable and set a shorter value for the demo. A plan is eligible only when it has at least two interested people, an unresolved blocker, and enough trustworthy context to send a useful message. One unsolicited intervention is permitted per stalled plan version. New material human input can create a new version and allow a new useful intervention. The scheduler never books a table and does not repeatedly send the same prompt. The demo also has a manual trigger that runs the identical evaluation path against a seeded quiet chat.

**Social rules:** “I’m down” means interest, not approval. “Anything but sushi” is a restriction; “Midtown preferred” is a preference; “after 7” excludes 7:00 PM. Do not fabricate consensus when constraints conflict. Ask one targeted question when necessary. Do not use low model confidence as a reason to make a social decision for the group.

**Approval rule:** only an explicit affirmative reply from a human member of the originating chat can authorize the current concrete proposal. “Book it” is sufficient when exactly one current proposal is pending; vague enthusiasm is not. Record approval before `ACT`. A changed or expired proposal needs new approval. Calendar or any future real-world tool requires approval covering that action too.

For the MVP, a proposal expires 24 hours after creation. Expiry leaves the historical plan and proposal in SQLite, cancels an unsent proposal message, and requires fresh human planning input before another automatic suggestion.

**Direct address (subsequent user requirement):** each new human group message is checked for an explicit plain-text call such as `Hey Rally, what's the plan?` or `Rally, recap the options.` An addressed message gets one concise Grok answer based on the originating group's saved plan and recent messages. Incidental mentions do not trigger a reply. Answers use the same outbox and chat GUID as proactive messages, and they cannot execute tools or count as booking approval. While testing through a shared iMessage account, self-sent human messages are accepted and Rally's `Rally:` replies are ignored on inbound.

## User-facing flow

1. BlueBubbles delivers messages from the dinner group. Rally records them once and ignores its own outgoing messages.
2. Grok extracts the goal, interest, constraints, and blockers into structured plan state.
3. When the group goes quiet, the scheduler evaluates the blocker. Rally searches venues if enough information exists; otherwise it asks one essential question.
4. Rally posts a specific, context-aware proposal in the same thread and waits.
5. A member explicitly approves the current proposal. The backend validates the approval, invokes the mock reservation once, then posts a clearly labeled demo confirmation with venue, time, party size, and confirmation ID.
6. The debug view displays the same persisted goal, signals, state, blocker, next action, and confidence driving the chat behavior.

## Failure behavior

- Replayed webhooks and repeated approvals do not create extra reservations or repeated nudges.
- Missing location, conflicting constraints, no venue result, or uncertain model output leads to `ASK` or `WAIT`, never a fabricated venue.
- A reservation failure leaves the plan unresolved and posts a truthful failure message. An outcome that cannot be determined is held for inspection, not retried automatically.
- Outgoing message failure remains visible in persisted delivery status so the demo operator can retry sending without retrying the reservation.

## MVP acceptance criteria

1. A 3–8 person BlueBubbles group can complete the dinner scenario in its original iMessage thread.
2. The extracted state identifies interested people, Friday dinner, after-7 availability, no-sushi restriction, Midtown preference, and the missing venue decision.
3. A quiet, blocked plan produces one useful automatic intervention; unrelated chatter and plans without sufficient interest remain silent.
4. A proposal contains a real searched venue or is clearly marked as a seeded demo fixture. It does not claim a real available table from place-search data alone.
5. No reservation occurs before explicit approval of the current venue, time, and party size; changed terms require approval again.
6. One approval creates one mock reservation with a stable confirmation ID, and a truthful final message appears in iMessage.
7. The lightweight debug view mirrors persisted state and the scripted demonstration completes in under two minutes.
8. Restarting the service preserves active and completed plan records and prevents duplicate interventions or bookings.

## Source differences and assumptions

Automatic inactivity nudging is P0 here because the user explicitly requested it, although the PRD lists it as optional. The user also clarified that Rally should be long lasting; stored plan records therefore persist. The PRD excludes sophisticated long-term cross-week memory, so personal profiles and automatic reuse of old preferences are deferred. The 30-minute threshold, one-active-plan-per-chat limit, FastAPI/SQLite choice, and Geoapify provider are implementation defaults for review, not statements from the PRD.
