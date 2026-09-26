# Project lessons

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
