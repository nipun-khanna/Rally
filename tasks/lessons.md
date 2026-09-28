# Project lessons

## 2026-09-27 — Verify replies from other group members

- User correction: a successful test from the owner's iMessage account does not prove that Rally replies to other participants.
- Rule: inspect the other participant's inbound row and matching outbox record separately. Keep a direct Rally request from going silent solely because the model marks it irrelevant or returns no answer; test both sender identities.

## 2026-09-26 — Do not impose an arbitrary search cutoff

- User correction: the twenty-per-day web search limit blocked expected Rally use.
- Rule: distinguish a local cost guard from a provider limit. Default to usable access when the user asks for broad search, make a daily cap opt-in, and explain the remaining provider charges and per-request tool bound.

## 2026-09-26 — Distinguish Rally's browser from the assistant's browser

- User correction: “give it a browser” meant Rally itself should gain a browser tool, not that this coding session should connect to a browser.
- Rule: resolve “it” against the product under development when the context is an agent capability request. Distinguish product runtime capabilities from tools available to the coding assistant before taking action.

## 2026-09-26 — Separate local monitoring from Rally's identity

- User correction: treating the monitored user's current iMessage profile as Rally's account does not describe a deployable personal reminder service.
- Rule: distinguish the user's local data/analysis identity, reminder recipient, and Rally's sending identity before configuring live delivery. A dedicated sender cannot access another account's history merely by receiving a private message.
- Rule: local monitoring can use local notifications directly; separate-contact iMessage reminders require a separately authenticated sender and a minimal, authenticated relay. Do not claim the current single-account transport implements that deployment.

## 2026-09-26 — Group sites need complete history

- User correction: the proposed group website must reflect the full existing group history, including messages before Rally joined.
- Rule: design a paginated historical import with resumable progress and deduplication before treating analytics as complete; distinguish imported history from the subset used for active plan decisions.
- User clarification: use older messages for history and analytics; show only Rally-tracked plans by default, while allowing members to request older plan findings in the portal.
- Rule: keep inferred historical plans separate from Rally's tracked plan records and label their source and uncertainty.
- User clarification: portal access should be a simple `{app_url}/{group_id}` link that anyone holding it can open.
- Rule: keep the requested URL shape while making the public group ID opaque and replaceable; never expose an internal BlueBubbles GUID as the access token.
- User clarification: full history includes available media and attachments, with controls for groups that do not want every section shown.
- Rule: model portal visibility by section and make imported media availability explicit instead of silently dropping attachments.
- User clarification: the portal should be themed to the iMessage UI.
- Rule: carry that visual direction into the portal design and verify it on mobile and desktop layouts.
- User correction: use the Vercel CLI, not the browser, for domain work.
- Rule: when the user specifies a tool surface, stay on it; diagnose its authentication and connectivity directly.

## 2026-09-26 — Verify native app stability before live transport tests

- User correction: BlueBubbles setup finished, but Messages crashes while attempting live iMessage testing.
- Rule: inspect native crash evidence and confirm Messages can stay open before testing BlueBubbles send or receive. Keep a real send limited to the explicitly named test group.
- User correction: the Mac was unlocked for the retry.
- Rule: recheck console lock state and a read-only Messages AppleEvent immediately before each live send; inspect the thread for any earlier uncertain delivery before retrying.

## 2026-09-25 — Continue from verified state

- User correction: inspect what is already built, consult the PRD for omissions, and finish the remaining scope without rebuilding completed work.
- Rule: audit the current code, tests, and task checklist against `PRD.md` before implementing; change only confirmed gaps and keep externally blocked checks explicit.

## 2026-09-25 — Ground planning documents in the PRD

- User clarification: the spec and task list must be based on the PRD.
- Rule: use `PRD.md` as the product source of truth; trace requirements back to it and label implementation choices as proposed defaults.
- Rule: inspect the PRD before inferring product scope from the project name or README.

## 2026-09-25 — Discuss functionality before detailing tasks

- User correction: discuss the entire functionality list before writing the task document.
- Rule: pause document drafting, walk through the PRD's functionality and scope choices with the user, and resume the detailed task list after that discussion is settled.

## 2026-09-25 — Distinguish model costs from integration costs

- User clarification: paid LLM access is allowed; other APIs should be free.
- Rule: apply the free-API constraint to non-LLM integrations. Verify ongoing free access, billing requirements, quotas, and potential overages using official sources before recommending providers.

## 2026-09-25 — Preserve lasting plan state

- User correction: “ephemeral” was a misstatement; Rally should be long lasting.
- Rule: persist plan history across restarts and completion. Do not add deletion or short retention requirements based on the earlier wording.

## 2026-09-25 — Finish requested documents promptly

- User steering: complete the task document quickly after functionality was settled.
- Rule: write the requested artifact before optional further research or process discussion when requirements are sufficient.

## 2026-09-26 — Website collaboration deployment scope

- User correction: GitHub-to-Vercel deployment is for other developers working on the website.
- Rule: separate website code previews and production deployment from local chat-data publication; do not propose a Mac runner for frontend collaboration.
- User correction: defer the GitHub Actions pipeline and deploy manually as needed.
- Rule: stop CI implementation when the user changes deployment mode. Document the manual CLI path, identify the existing Vercel project's purpose, and avoid creating an extra project or workflow without a renewed request.

## 2026-09-26 — Lead the README with the product

- User correction: the main README should explain what the app does, not open with a narrow implementation pitch.
- Rule: introduce the product and its main use cases first; distinguish working functionality from planned work before setup instructions, and keep those claims aligned with the PRD and current task tracker.
- User correction: Rally's primary goal is personal relationship intelligence; group planning is supporting functionality.
- Rule: prioritize relationship intentions, private memory, evidence-based attention, and user-approved follow-through in product language and implementation. Treat group-chat planning as one supporting source/action, not Rally's product center.

## 2026-09-26 — Explicit imperative Rally commands

- User reported no response to an explicit Rally request. The trigger excluded imperative verbs such as turn, enable, and hide.
- Rule: test actual user command wording through trigger detection and command handling; disabled capabilities must produce a deterministic explanation instead of falling through to model extraction.

## 2026-09-26 — Respond to any direct Rally call

- User correction: Rally must respond whenever explicitly called, regardless of the words after its name.
- Rule: direct-address detection recognizes the name at message start with optional greeting/@ and does not use a command-verb allowlist. Test arbitrary statements, contextual requests, emojis, and the name alone; ordinary mid-sentence mentions remain distinct.

## 2026-09-26 — Honor external teammate ownership

- User correction: dashboard, follow-up detection, calendar integration, and website deployment are already assigned to human teammates.
- Rule: before dispatching implementation, record human/subagent ownership and file/API boundaries. Do not implement an assigned subsystem in parallel. Root owns existing runtime reliability, shared contract coordination, and integration after teammate deliverables; ask for branches/PRs without blocking independent reliability work.
- Rule: an approved implementation plan is narrowed by later ownership instructions. Update the plan immediately and give agents the exclusions explicitly.

## 2026-09-26 — Do not sign outbound texts as Rally

- User correction: stop signing sent messages as Rally.
- Rule: deliver replies and reminders as natural message text without a `Rally:` prefix. Keep bot identity in transport metadata/internal state, and normalize already queued outbound messages before sending.
## 2026-09-26 — Conversation follow-ups after a direct Rally call

- When a member explicitly addresses Rally and Rally answers, the next short question in the same group should inherit that conversational turn for a bounded period. Requiring the name on every follow-up makes Rally appear to ignore natural replies such as “what can you do?”
- Keep the carry-forward rule bounded and test that it expires, is reset by unrelated messages, and does not trigger on arbitrary group conversation.

## 2026-09-26 — Temporary outbound text style

- User temporarily changed the outbound convention: prefix texts with `Rally:` and write the body in lowercase.
- Apply presentation at the BlueBubbles send boundary so queued content stays canonical, retries get the same formatting, and inbound matching remains unchanged. Treat the user's later style instructions as superseding this temporary rule.

## 2026-09-26 — Judgement during group chat floods

- User correction: a called Rally should not answer every follow-up or repeated call when the group is spammed.
- Rule: treat relevance as permission to consider a reply, then require usefulness and apply burst coalescing plus a per-group rate cap before sending a text or reaction. Keep explicit approvals and safety controls operable.

## 2026-09-27 — Preserve the proven Continuity calling and audio path

- Only call Akshit at +17032004231 using Phone's tel URL on `feat/mac-phone-grok-voice`. Confirm with the green Continuity pill button; Notification Center's reported click is not evidence of a call.
- Keep system input BlackHole 2ch, system output MacBook Pro Speakers, Phone microphone/output Use System Setting, and Grok playback BlackHole 2ch. Do not replace these with aggregate devices or select Phone's microphone by BlackHole name.
- Diagnose mouth and ears separately: beep into BlackHole verifies transmit routing with recipient feedback; receive audio uses a process tap of speaker playback. `response.done` and playback-started establish generation/local playback only.
- User correction: perform call confirmation through computer use. Use `sky` to press the green Continuity control; when capture is unavailable, the user explicitly supplied the 1512×982-display coordinate (1449,80). Inspect call state afterward; a click alone is not a placed-call result.
- User explicitly approved adding Ghostty's System Audio Recording Only permission. Carry that authorization forward; do not re-ask for the same permission. Verify the toggle and actual capture separately, since a preexisting tap can stay silent until its host restarts.
- On an active Continuity call, inspect the Mute/Unmute control before changing audio routing. `Unmute` means transmit is blocked even when Grok produces a healthy BlackHole signal. User unmuted after this was observed; verify a new response afterward.
- User pivoted to Vapi for calling. Stop extending or debugging the local Continuity/BlackHole path; preserve work and move the calling integration to the selected provider. The destination restriction remains Akshit-only until explicitly broadened.
- User changed the Vapi test destination to +16785991244. This supersedes the earlier Akshit-only restriction for the new Vapi path; do not dial +17032004231 for subsequent Vapi tests.
- User corrected the Twilio account status: it is not a trial. Do not suggest trial recipient verification as the active diagnosis for this account; prioritize Twilio Voice geographic permissions and the exact provider error from fresh call logs.
- User corrected the interpretation of the Twilio phone number during Vapi testing. Explicitly distinguish the number that should ring from the provider-owned caller number before changing calling permissions or placing another call; suspend the old +16785991244 assumption until clarified.
- User clarified that +16785991244 is a test-only destination. Keep the live-test CLI bounded, but do not hardcode that destination as the only number the actual Rally app can call; its workflow must use the number supplied in an authorized request.
- User clarified that Rally should use its Vapi/Twilio caller number to call restaurants and make real reservations for the group. A generic relationship check-in assistant or a browser page lookup does not fulfill a restaurant booking request. Pass exact group reservation terms to a restaurant-specific caller, and report a booking only from restaurant confirmation evidence.
- User corrected the restaurant call introduction: do not volunteer an AI label. Open by saying the call is on behalf of the configured owner, give the reservation request, and answer truthfully if directly asked about automation.

## 2026-09-27 — Outbound texts are not signed Rally

- User correction: remove the `Rally:` prefix before every outbound message, and keep ignoring Rally's own echoes.
- Rule: format at the send boundary. Strip a legacy `Rally:` prefix and do not add it back. Keep the body's original case so confirmation codes and other identifiers are not lowercased. Drop inbound `isFromMe` echoes only by confirmed guid, temp guid, or the short identical-text fallback while that id is unknown. An owner message that starts with `Rally:` is a human message unless its id is a known bot send.
## 2026-09-27 — Direct repair and named-call coverage

- User correction: handle the missed-call bug directly rather than delegating it to Cursor. This supersedes the earlier Cursor-only preference for this repair.
- A supported number-only call test does not prove name-based calling. Test the user's exact named command at the webhook boundary and require a durable provider call id before claiming a call started.
- Route unresolved explicit call requests to deterministic clarification. Do not allow a conversation model to promise execution without the calling backend.
