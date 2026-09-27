# Rally group conversation design

**Purpose.** In the configured iMessage groups, Rally should feel like a useful participant after someone calls it, while remaining quiet during ordinary conversation. The current two groups are HackGT13 and the localhost. The same behavior follows the configured allowlist if the owner changes it later.

## Conversation boundary

- A message that explicitly addresses Rally opens a turn in that group. Any group member may continue it.
- Rally answers a follow-up only while the turn is fresh (five minutes since the last relevant message), the follow-up concerns the active request, and no intervening unrelated message has ended the turn. It does not answer a standalone question elsewhere in the chat.
- A relevant message does not require a reply if Rally has nothing useful to add. Rapid repeats are coalesced; at most one reply is sent for a short burst and no more than three replies per group in a rolling minute. The flood guard applies to repeated direct calls too, while leaving existing approval and safety commands available.
- The decision is bound to the trusted webhook chat and message IDs. Duplicate webhooks produce at most one reply and one reaction. A restart does not turn old messages into fresh requests.
- Portal commands, adaptive tools, web lookup, booking approval, and availability handling keep their existing priority. Consequential actions still require their existing explicit approvals.
- Outbound BlueBubbles text retains the temporary `Rally:` prefix and lowercase body requested by the user.

## Group memory

- Memory is stored under the exact group chat ID, never shared between groups or private relationship records.
- Keep short, sourced, durable facts useful for future conversation: recurring preferences, shared plans, named roles, and explicit decisions. Include message ID and update time. Do not turn guesses, sarcasm, or one-off chatter into facts.
- Limit the number and size of stored facts and the number inserted into a reply prompt. A group can ask Rally to forget a specific fact. Deleting it must stop future use.
- Exclude credentials, contact details, health, finances, intimate information, and requests to facilitate wrongdoing. Existing chat history may still be present in the separate opt-in archive; group memory stores only the filtered fact.
- Learn without delaying an outgoing reply. Model-extracted candidates are validated again locally before persistence.

## Safety and reactions

- Profanity alone is allowed. Rally refuses requests that facilitate illegal activity; it may discuss a topic neutrally or help someone seek safety. Unsafe messages receive no positive reaction and create no memory fact.
- The model returns a typed decision: relevance, safety, reply, optional reaction, and optional memory candidates. Unsupported or malformed output fails closed; no reaction or memory write occurs.
- Reactions are limited to BlueBubbles-supported tapbacks, only for a message in the same allowed group, at most once per source message. An unavailable Private API is reported as unsupported and does not trigger a substitute text or delayed surprise reaction.
- A reaction is optional, never a substitute for an answer or refusal, and is suppressed during message floods.
- The BlueBubbles server currently reports `private_api=false` and `helper_connected=false`; macOS SIP is enabled. Code can be ready, but live tapbacks require the owner to configure the Private API helper on the Mac.

## Latency and failure behavior

- An explicit call uses one bounded reply decision call. A possible follow-up uses one bounded call to decide relevance and draft the reply. Keep recent context and memory prompt small.
- Queue/delivery remains durable; failures after an uncertain BlueBubbles send are never retried automatically. Per-chat serialization prevents interleaved turns; one group's slow provider call does not block another group.
- Record sanitized stage and elapsed time for inbound decision and outbound delivery, without logging message text or credentials. The visible reply is sent before slower plan extraction or memory learning continues.
- If the provider fails, Rally gives a short failure response to an explicit call; irrelevant or expired messages stay silent.

## Verification

- Exercise two independent groups, multiple senders, duplicate and out-of-order webhooks, a relevant short follow-up, unrelated interruption, expiry, and restart.
- Exercise safe profanity, illegal facilitation refusal, neutral discussion, sensitive memory rejection, forget, cross-group isolation, reaction capability off/on, uncertain send, and prompt injection.
- Measure reply latency against the existing local baseline with synthetic requests; do not send real group messages without a separate explicit live-test instruction.
