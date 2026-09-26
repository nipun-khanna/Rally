# Adaptive Rally requests — implementation plan

Source: `docs/remaining-functionality-design.md` and `tasks/todo.md`. This work is separate from the externally assigned dashboard, follow-up, calendar and deployment tasks.

## Goal

When an explicitly addressed group member asks Rally to do something beyond its canned replies, Rally identifies a registered capability, proposes a validated workflow, executes read-only steps, or records a missing capability for developer review. It never treats a generated code artifact as executable or a saved workflow as standing permission for a later action.

## Boundaries

- Only existing allowlisted group chats. Personal selected-source texts never enter this path.
- Existing portal link, group planning approval, web search, and reservations retain their current behavior. Do not replace those paths before parity is verified.
- Registry effects: `read` may run immediately; `commitment` requires exact current-version approval. Unknown tools or invalid arguments are rejected.
- Agent output is data, not authority. Validate each tool, arguments, side-effect class, chat scope, budget and output before execution.
- Generated code is an inert text artifact under ignored `data/capability_proposals`, never imported, installed, or run. No package installs.
- Source artifacts are only available to a local authenticated administrator, never the bearer-link group portal.
- All persistence uses SQLite; source and keys are not logged.

## Task A: Request and workflow persistence

Files: `app/adaptive/store.py`, `tests/test_adaptive_store.py`.

- [ ] Test unique `(chat_id, message_id)` request creation and restart recovery; fail first.
- [ ] Implement owner/chat-scoped request, revision, state (`pending`, `planned`, `blocked`, `awaiting_approval`, `running`, `complete`, `failed`, `pending_review`), step, proposal and workflow tables.
- [ ] Test stale revision refusal, unique step outcomes, exact argument hash and approval invalidation.
- [ ] Implement transactional methods; preserve pending/uncertain results across restart.

## Task B: Registered tool boundary

Files: `app/adaptive/tools.py`, `tests/test_adaptive_tools.py`.

- [ ] Test unknown tool, unknown fields, malformed types, cross-chat access and unapproved commitment failures; fail first.
- [ ] Implement immutable `ToolSpec(name, schema, effect, handler)` registry and schema validation.
- [ ] Register only existing safe read capabilities first: local plan status and public web research. Web research uses the current explicit request, tone hint and existing budget; no raw history transfer.
- [ ] Give commitment steps explicit exact-argument approval records; do not register calendar/booking until the assigned teammate exposes stable APIs.

## Task C: Structured planning and inert code proposal

Files: `app/adaptive/agent.py`, `app/adaptive/proposals.py`, `tests/test_adaptive_agent.py`, `tests/test_capability_proposals.py`.

- [ ] Test structured plan is bounded to 3 steps; unsupported tools become a missing-capability record with no execution.
- [ ] Implement Grok schema-checked planner using the existing xAI client and explicit current request plus sanitized available-tool metadata. Preserve source prompt isolation and safe errors.
- [ ] Test generated source is saved only as data, under an ignored path with random ID and restrictive mode; syntax check uses `ast.parse` only, no import/exec/subprocess.
- [ ] Generate code proposal with summary, dependencies, proposed tests and tool schema; status remains `pending_review` even if syntax passes.
- [ ] Record invalid or failed generation honestly; no fallback that claims the capability exists.

## Task D: Same-chat request handling

Files: `app/orchestrator.py`, `app/config.py`, `app/main.py`, `tests/test_adaptive_http.py`.

- [ ] Add an explicit adaptive request entry point that does not steal ordinary planning/portal/web commands. A message ID is processed at most once and reply uses the same chat.
- [ ] Save request before model/tool work; resume nonterminal state safely after a crash without blind replay of uncertain commitment effects.
- [ ] Expose local authenticated review metadata endpoint (no source in public portal); no installation endpoint.
- [ ] Test duplicate webhook, unknown capability, provider failure, exact approval, stale approval and restart recovery.

## Task E: Verification

- [ ] Full suite, offline smoke, malformed agent output, malicious source proposal inertness, public portal exclusion and cross-chat isolation.
- [ ] Local synthetic integration. Do not send a live group request unless its intent and side effects are safe and clearly labeled.
- [ ] Commit in reviewable units; push under standing authorization. Record blocked integrations with teammate-owned calendar/dashboard separately.

## Initial implementation slice

Task A and the inert artifact part of Task C can be built and verified independently now. Tool execution and group routing follow after their contracts and tests are ready; do not claim full adaptive requests based on the initial slice.
