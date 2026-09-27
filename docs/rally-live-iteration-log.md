# Live iteration log (2026-09-26)

Chat: HackGT13 `any;+;chat536074477903103142` (allowlisted). Private API off; no SIP changes. No tokens or `.env` values in group text.

## What changed before these probes

- Conversation payload: last 12 humans **and** Rally replies (`from_rally`), no `sent_at_local`.
- Outbound replies stored as `rally-out:{id}` so the next turn sees them.
- Plan/proposal snapshot passed into `decide_conversation`.
- Extract no longer holds the chat lock (second call is not blocked on Grok extract).
- Recap-like asks with a known plan reply **locally** (no 25s Grok wait). Timeout fallback uses the same plan-backed text instead of “try again later.”
- Dashboard command now returns the hosted archive (`RALLY_APP_URL` / Vercel), never a local GUID or `?token=`.
- Conversation HTTP timeout is **10s** (was 25s); timeout failovers to a plan-backed local reply.

Unhinged prompt **is** in `app/agent.py`. Non-recap asks still call Grok; recap-with-plan stays local.

## Probes

| UTC | Sent | Rally reply | Wall | Score |
| --- | --- | --- | --- | --- |
| 01:43:37 | `Rally, recap what people said about dinner and pick one place.` | `Rally: i couldn't finish that request. please try again later.` | 25.8s | Fail: Grok `groupconversationdecision` timeout |
| 01:46:16 | `Rally, recap dinner from what people said and name the next step.` | same timeout text | 25.8s | Fail: same |
| 01:48:11 | `Hey Rally, send the dashboard` | `Rally: the admin desk is on the mac that runs rally. open http://127.0.0.1:8770/admin/groups/any%3b%2b%3bchat536074477903103142 there. i won't post the sign-in token in this chat.` | **0.62s** | Fast. 127.0.0.1 path. No token in group. |
| 01:48:53 | `Hey Rally, recap dinner from the thread and name the next step now.` | `Rally: dinner, 2026-09-27, at 20:00, for 2, near rambler atlanta, nearby walking distance, chinese or japanese, (akshit is isolating and will not attend). next step: pick one walking-distance spot.` | **0.65s** | Fast / useful / on-thread. Did not invent a restaurant. |
| 01:50:14 | `Hey Rally, chinese or japanese for rambler — lock one.` | feral local fallback (same facts, “quit spinning…”) | **11s** | Grok 10s timeout; local failover. Did not pick chinese vs japanese. |
| 01:50:53 | `Rally, send the dashboard` | `Rally: our group page: https://rallyplans.vercel.app/c3jgcmcfinfygndemdkm3rhbffr8kern` | **0.64s** | Vercel, no 127, no token, no chat GUID. Public id **lowercased** by `add_rally_signature`. |
| 01:51:38 | `Hey Rally, lock chinese or japanese — pick one and say why.` | same local failover as 01:50:25 | **10.9s** | Grok timeout again (`decision elapsed_ms=10054`). Useful facts, not a cuisine pick. |
| 01:55:02 | `Rally, send the dashboard` | `Rally: our group page: https://rallyplans.vercel.app/C3JgCmCfInFygNDeMdKM3rHBFFr8kERN` | **0.61s** | Mixed-case public id preserved. No 127. No token. |
| 01:56:22 | `Hey Rally, recap dinner and the next call.` | same local plan recap (“quit spinning… pick one walking-distance spot”) | **0.78s** | After 4s-timeout reload. Recap path skipped Grok; did not sit 10s. `receive elapsed_ms≈908`. |

## Bar

- **Fast:** last recap and dashboard were sub-second; not blocked on extract.
- **Useful:** recap named date, 8pm, party of 2, Rambler, Chinese/Japanese, Akshit out, and one next decision (pick a walking-distance spot).
- **Knowledge:** matches stored plan + HackGT13 humans (`tmr at 8pm`, `just 2 ppl`, Rambler, cuisine).

## Remaining gaps

- Grok `decide_conversation` still times out at 10s; unhinged model voice never made it to iMessage. Failover is slightly spicy local template, not a cuisine lock.
- `add_rally_signature` lowercases the Vercel public id (`C3Jg…` → `c3jg…`). Confirm whether the archive is case-sensitive.
- Tapbacks still `ValueError` (`private_api=false`).
