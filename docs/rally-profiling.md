# Rally receive-path bottlenecks

Profiled 2026-09-26. Method: local `cProfile` + stage timers via `scripts/_profile_receive.py` (FakeAgent, no live iMessage). Live SQLite inbound→`rally-out` deltas and BlueBubbles `helper_status` against the running Mac server. **8770 was not sampling-profiled** (py-spy/scalene not installed; uvicorn was idle or recycling). No extra iMessages sent.

## Method

| Source | What it measured |
| --- | --- |
| `PYTHONPATH=. .venv/bin/python scripts/_profile_receive.py` | FakeAgent receive, defer vs sync extract, payload size |
| `data/rally.sqlite3` | HackGT13 inbound `sent_at` → `rally-out:{id}` `sent_at` (no message text) |
| Prior 8770 stdout | `GrokProviderError … groupconversationdecision kind=timeout` |
| `helper_status` once | Live BlueBubbles `/api/v1/server/info` only (no send) |
| `GET /health` | 8770 was up during measurement; later recycled |

## Numbers

Local FakeAgent, 12-message seed, `defer_heavy_work=True`:

| Case | `receive()` return | Background extract/learn |
| --- | --- | --- |
| Instant Grok + send | **9–11 ms** | ~3 ms |
| Sync extract 200 ms (`defer=False`) | **214 ms** | n/a (on request) |
| Deferred extract 200 ms | **11 ms** | 208 ms |
| Simulated live (decide 800 + send 350 + extract 1200) | **1286 ms** | 1210 ms |
| Local recap (`_can_recap_locally`) | **8 ms**, 0 `decide_conversation` calls | extract still scheduled |

cProfile on 8 instant receives (~101 ms total): after thread-join noise, top user time is `RallyService._handle_addressed_message` (~10 ms/call), then `_react` / `GroupTurnStore.remember_reaction`, then SQLite `commit`. `Store._db` opened ~34 times per receive. Local SQLite is not the live cost.

Grok payload for `decide_conversation` (last 12 + plan + 12 memory lines): **~6.9 KB**, system prompt ~2800 chars. Not the timeout cause.

Live HackGT13 (`any;+;chat…03103142`), no extra send:

| Inbound UTC | Path | Inbound → `rally-out` |
| --- | --- | --- |
| 01:46:16 | Grok `decide_conversation` hit HTTP timeout, then fallback | **26.2 s** |
| 01:48:11 | Dashboard priority command (no Grok) | **1.06 s** |
| 01:48:53 | Local recap (no Grok) | **1.11 s** |

Live-iterate wall times for the last two were **0.62 s / 0.65 s** from send POST; the extra ~0.4 s is BlueBubbles ingest before Rally stores the inbound row. Prior 8770 log: `groupconversationdecision kind=timeout` and later `memorylearnresult kind=timeout`. Decision timeout in `GrokClient._call` is **10 s** now (was 25 s when the 26 s failure happened). Extract stays **60 s**.

`helper_status` against live BlueBubbles: **1152 ms** cold, **0.0 ms** cached (15 s TTL), status `unsupported` (`private_api` off). Live chat GUIDs are `any;+;…`, so `send_reaction` / `set_typing` raise `ValueError` in `app/reactions.py` (`_GROUP_GUID` requires `iMessage;+;`) **before** preflight. Tapback/info HTTP is not on the live webhook path.

## Does extract still block the webhook?

**No**, when `build_service` sets `defer_heavy_work=True` (`app/config.py`). `_handle_addressed_message` replies first; `_extract_and_learn` is `ThreadPoolExecutor.submit`’d and `_receive` returns. Confirmed: 200 ms extract left `receive()` at 11 ms.

`_handle_addressed_message` still returns `False` after a normal reply, so extract **is scheduled**, just not on the request. `_learn_from_chat` (`GrokClient.learn_memory`) runs only in that background job, and is skipped if the decision already saved candidates (`_remembered_ids`).

The webhook **does** wait for conversation decision + BlueBubbles send. `RallyService.receive` holds the per-chat `RLock` across that window.

## Top bottlenecks

1. **`GrokClient._call` / `decide_conversation`** — only provider call on the addressed path. 10 s HTTP timeout (httpx per-phase). Live miss ≈ full timeout + local fallback + ~1 s send. Prompt size is not the cost.
2. **`bluebubbles.send_message`** via `_queue_and_send` → `deliver_pending` — ~0.6–1.1 s on successful local replies; adapter timeout 45 s (historical 17 s BB completion).
3. **Per-chat lock in `receive`** — same-chat inbound queues behind Grok+send (up to timeout + 45 s). Cross-chat is fine. Extract no longer holds this lock.
4. **Not the request:** extract/learn Grok (60 s / 10 s), SQLite (~10 ms), `helper_status` (cached; live GUID mismatch skips it).

## Fixes (impact order)

1. **Keep non-recap replies off the 10 s timeout.** Widen local/plan-backed answers (already used for recap + decision timeout). Or fail over sooner (3–5 s) to `_local_decision_reply` instead of sitting on `httpx` until the budget burns. Highest user-visible win.
2. **Release the chat lock before Grok**, or run `decide_conversation` off the webhook thread and send when it returns. Stops same-chat pile-up (67 unprocessed humans in SQLite at profile time). Bigger than a one-liner.
3. **Treat BlueBubbles send as the remaining ~1 s** after local/short-Grok replies. Do not add `helper_status` to the live `any;+;` GUID path without the existing 15 s cache — a cold info GET is 1.15 s and would sit in front of the reply (`_react(SEEN)` is before decision).

Do not grow the `decide_conversation` prompt to chase latency.

## Instrumentation added

uvicorn 8770 uses `--log-level warning`, so the old `logger.info` `elapsed_ms` lines were invisible.

- `group_conversation stage=receive|decision|send|extract|learn elapsed_ms=…` is now **warning**
- `grok stage=<schema> elapsed_ms=…` from `GrokClient._call` (no payload, no key)

Reload 8770 to see them. `defer_heavy_work` and `helper_status` TTL were already in place.
