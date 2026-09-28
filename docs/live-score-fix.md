# Current score and follow-up routing

The reported conversation exposed three routing defects: score/game questions were absent from the public-web intent classifier; short "pull it live" follow-ups had no public-topic resolution; and BrowserInbound intercepted "search for the scores" before RallyService, opening a generic search instead of answering the matchup. Web priority replies also did not refresh the five-minute conversation turn.

Score questions now reach read-only web research. A bounded resolver follows the latest human score/game request in the same chat, within five minutes and twelve messages, across short score follow-ups. It stops at unrelated human messages and never treats Rally's generated score claims as evidence. The browser handler yields score questions to that route. Web replies refresh the existing conversation turn, and score follow-ups bypass the idle-chatter filter.

For score requests, GrokWebClient requires a web tool invocation, verifies a completed `web_search_call` and public URL citation, and suppresses unsupported generated scores. Source URLs and UTC lookup time accompany retrieved answers. The prompt requires game date/live/final distinction and source update time if available; missing evidence or disabled web yields honest inability to verify. This is a public-page lookup, not a guaranteed real-time subscription feed.

Provider contracts checked against official xAI docs:
- https://docs.x.ai/developers/tools/web-search
- https://docs.x.ai/developers/tools/tool-usage-details
- https://docs.x.ai/developers/tools/function-calling

Verification: four failing-before regressions reproduced missing routing, generic browser interception, unsupported-score leakage, and missing lookup time. Final focused run: 82 passed, 11 subtests passed, one existing Starlette deprecation warning. Eight new tests include the actual FastAPI webhook sequence and check cross-chat/expired/intervening-topic exclusion, disabled-web truthfulness, and retrieval/citation validation. `git diff --check` passed. Root runs the full suite and restarts after combining the parallel named-call fix.

Read-only real provider check: the first configured-model score request timed out at 45 seconds. No score was asserted or sent to any chat. Longer diagnostic check pending; routing tests use controlled transport and cannot establish provider latency or live-data freshness.

No production database was modified, no iMessage was sent, no phone call was placed, and no deployment/server restart was performed for this repair.
