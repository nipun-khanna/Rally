# Project lessons

## 2026-09-26 — Do not impose an arbitrary search cutoff

- User correction: the twenty-per-day web search limit blocked expected Rally use.
- Rule: distinguish a local cost guard from a provider limit. Default to usable access when the user asks for broad search, make a daily cap opt-in, and explain the remaining provider charges and per-request tool bound.

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
