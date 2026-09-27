# Rally Group Conversation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Rally converse after being called, remember useful facts separately for each allowed group, react when BlueBubbles supports it, reply faster, and refuse illegal assistance.

**Architecture:** SQLite stores compact sourced memory and per-group turn state. One structured xAI decision judges relevance/safety and drafts a reply plus optional reaction and memory candidates. A BlueBubbles adapter sends reactions only when its Private API helper reports ready. Keep message send idempotency and existing planning/action routes.

**Tech Stack:** Python 3.13, FastAPI, SQLite, Pydantic, BlueBubbles REST API, xAI Chat Completions, pytest.

**Spec:** `docs/superpowers/specs/2026-09-26-rally-group-conversation.md`

## Global Constraints

- Only configured allowlisted groups are eligible; private relationship sources never enter this flow.
- Direct `Rally` calls start a five-minute same-group turn. Only related near-term follow-ups get replies; unrelated messages close it.
- A relevant message may be ignored when no answer adds value. Coalesce rapid repeats and cap group replies at three per rolling minute; do not throttle explicit approvals or safety commands.
- Preserve temporary `Rally:` prefix and lowercase message body.
- Profanity alone is allowed. Illegal-assistance requests receive a brief refusal and no tools, reaction, or memory write.
- Group memory is compact, evidence-linked, bounded, deletable, and locally checked for sensitive content.
- No live reaction attempt while BlueBubbles reports Private API disabled; no emoji-text fallback.
- No real group messages sent during automated verification.

## Review Focus

1. HackGT13 memory never appears in the localhost prompt, even across restart.
2. An unrelated, stale, or spammed message after a direct call produces no reply or reaction.
3. Duplicate webhooks and uncertain delivery cannot produce duplicate text or tapbacks.
4. Unsafe or sensitive messages are excluded from memory and cannot trigger a positive reaction.
5. A disabled BlueBubbles helper never receives a reaction POST.

## File ownership and tasks

### Task 1: Durable group memory

**Files:** `app/group_memory.py`, `tests/test_group_memory.py`.

**Interface:** `GroupMemoryStore(path).upsert_fact(chat_id, key, fact, source_message_id, observed_at)`, `list_facts(chat_id)`, `prompt_context(chat_id)`, `forget(chat_id, key)`; at most 30 facts per group. Validate candidates before storage.

- [ ] Implement and review source-linked, bounded group memory with cross-chat, dedup, restart, forget, and sensitive-content checks.
- [ ] Run focused tests; report the exact interface to integration.

### Task 2: BlueBubbles reaction adapter

**Files:** `app/reactions.py`, `tests/test_reactions.py`.

**Interface:** `send_reaction(base_url, password, chat_id, message_id, reaction, opener=urlopen) -> ReactionResult` with `sent`, `unsupported`, or `uncertain` status. Query BlueBubbles readiness before attempting a tapback.

- [ ] Verify BlueBubbles v1.9.9 payload from primary sources, implement typed validation and readiness check, and test no POST with helper off.
- [ ] Test accepted response, malformed response, unsupported reaction, and uncertain result. Do not send live tapbacks.

### Task 3: Typed conversational decision and safety

**Files:** `app/agent.py`, `app/group_safety.py`, `tests/test_group_conversation_agent.py`.

**Interface:** one decision has `relevant`, `safety`, `message`, `reaction`, and bounded memory candidates. Direct calls need no relevance decision; follow-ups do. Locally gate obvious secrets and actionable illegal requests before any memory write or tools.

- [ ] Write focused scenarios for casual profanity, illegal facilitation, neutral discussion, prompt injection, malformed provider output, and on-topic versus unrelated follow-ups.
- [ ] Implement the structured one-call decision with recent same-chat context and memory; fail closed on invalid output.

### Task 4: Per-chat turn state and routing

**Files:** `app/group_turns.py`, `app/orchestrator.py`, `app/config.py`, `tests/test_group_conversation_service.py`.

**Interface:** persisted turn state keyed by chat ID and source message ID; five-minute expiry. Existing portal, adaptive, web, approval, and availability routes keep priority. Optional reaction callback is injected and invoked only after a safe decision.

- [ ] Test direct call, related follow-up from another member, unrelated interjection, expiry, cross-chat isolation, restart, duplicate webhook, rapid repeats, and reply caps.
- [ ] Route decisions and memory candidates without blocking visible reply on slower plan extraction; preserve durable outbox behavior.

### Task 5: Memory learning and latency

**Files:** `app/group_memory.py` or focused learner module, `app/main.py`, `app/config.py`, `tests/test_group_memory_learning.py`, `docs/group-conversation.md`, `README.md`.

**Interface:** background, per-chat batching learns durable facts from allowlisted group messages; the reply prompt reads at most 12 compact facts. Memory learning cannot delay a direct reply. Provide sanitized latency events for provider decision and send.

- [ ] Test batch learning from ordinary messages, redaction, correction, and no cross-chat or private source access.
- [ ] Measure a synthetic direct reply before/after; use a supported low-latency xAI model/config if it improves observed time without weakening required safety behavior.
- [ ] Document turn rules, memory/forget, content filtering, reaction prerequisite, startup, and performance limits.

### Task 6: Integration review

**Files:** impacted tests/docs and `tasks/todo.md`.

- [ ] Run focused and full suites, inspect changed code, and fix regressions.
- [ ] Ask the user-review subagent to rerun its five acceptance scenarios against the implementation.
- [ ] Verify local health on the BlueBubbles webhook port; do not send live group texts or tapbacks during code verification.
- [ ] Record exact shipped behavior and live reaction limitation.
