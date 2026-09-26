# Project lessons

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
