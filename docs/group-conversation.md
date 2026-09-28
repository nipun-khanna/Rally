# Group conversation

Rally can join allowlisted iMessage groups after someone calls it, then stay in a short turn instead of answering every message.

## Turns

A message that starts with `Rally` (optional greeting) opens a five-minute turn in that group. Any member can continue the same request. Rally replies to a follow-up only while the turn is fresh, the follow-up is about the active request, and nothing unrelated has closed it. Ordinary chat stays quiet.

On the first call in a chat, Rally pulls recent BlueBubbles history for that group (newest first, bounded) so it can recap and decide from messages sent **before** anyone invoked it. Those backfilled lines are stored as already processed so they do not replay as new webhooks. The public archive import stays separate.

A relevant message can still get no text if there is nothing useful to add. Rapid repeats of the same call are coalesced. At most three group replies go out per chat in a rolling minute. Booking approval, availability answers, portal commands, and forget/safety refusals stay available.

Duplicate webhooks reuse the same message ID, so they produce at most one reply and one reaction. Restarts do not treat old messages as new requests.

Portal, adaptive tools, web lookup, booking approval, and availability handling keep their existing priority. Outbound texts use a lowercase body and no `Rally:` prefix. Bot echoes are still ignored.

## Memory and forgetting

Each group has its own compact, source-linked fact list (at most 30 stored, 12 in a reply prompt). Facts are recurring preferences, shared plans, roles, and explicit decisions. Guesses, sarcasm, credentials, contact details, health, finances, intimate information, and illegal assistance are not stored.

Say `Rally, forget food.preference` to delete one key, `Rally, forget the group prefers ramen` to delete that exact stored sentence, or `Rally, forget all` to clear that group. A short word such as `the` is not a substring wipe. Deleting a fact stops future prompt use. Memory never crosses into another group or private relationship records.

Ordinary allowlisted chatter can add facts in the background after the webhook returns. That learning never blocks a visible reply.

## Content filtering

Profanity alone is allowed. Requests that ask Rally to help commit a crime get a short refusal, no tools, no reaction, and no memory write. Neutral discussion of a topic can still be answered.

## Reactions

Tapbacks use BlueBubbles `POST /api/v1/message/react` after `GET /api/v1/server/info` shows `private_api=true` and `helper_connected=true`. Rally puts 👀 on a message as soon as it starts handling a call or follow-up, then changes that tapback when the reply is sent. The completion tapback is one of love, like, dislike, laugh, emphasize, or question, chosen to match the reply — not always like. If it decides not to reply, or refuses, it removes the eyes instead of leaving a positive tapback. If the Private API helper is off, those calls are skipped and Rally does not put emoji in the text as a substitute.

This Mac currently needs the owner to enable the Private API helper (and usually disable SIP for that setup) before live tapbacks work. Text replies do not depend on that helper.

Typing indicators use `POST`/`DELETE /api/v1/chat/{guid}/typing` only after the same helper preflight. `/api/v1/server/info` is cached for a few seconds so reactions and typing do not each hit BlueBubbles.

## Startup and limits

Use the same allowlist as the rest of Rally (`RALLY_ALLOWED_CHAT_GUIDS`). Group memory and turn state live in the main SQLite file. Conversation decisions are one bounded xAI call. Replies treat recent human messages as the source of truth when the stored plan is empty or stale. Plan extraction and background memory learning run after the webhook returns so a reply is not stuck behind them. Automated tests do not send live group texts or tapbacks.
