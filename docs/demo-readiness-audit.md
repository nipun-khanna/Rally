# Demo readiness audit

## Workflow

Checked 2026-09-27. This section is the synthetic FastAPI workflow only. No BlueBubbles text was sent, no Vapi call was placed, the portal was not deployed, and nothing was committed. The production database was not opened. A prior live group web-search text and a public archive deploy stayed unauthorized.

### Command

```text
.venv/bin/python -m pytest tests/test_demo_end_to_end.py -q --tb=short
```

Result: **1 failed, 4 passed**, 1 Starlette deprecation warning, 0.70s. Exit code 1.

The run patched `socket.create_connection` to raise. The four passing tests did not open a socket. Discovery HTML was served by an in-test fetch, not DuckDuckGo. The dialer was `InMemoryVapi` on a temp SQLite file under pytest `tmp_path`, with `schedule=False` and sender `+15555550123`.

### What passed through `create_app`

`tests/test_demo_end_to_end.py` posts synthetic BlueBubbles bodies to `/webhooks/bluebubbles` on an app built by `main.create_app`. The handler, `CallAttemptStore`, and `PortalStore` share that temp database.

| Check | Result |
| --- | --- |
| Malformed input | Missing or wrong token returns 403. A JSON list returns 422. An `updated-message` and a `new-message` without a guid are `accepted: false`. |
| Unlisted group | `accepted: false`. No public fetch and no Vapi body. |
| Public web discovery | `PublicRestaurantLookup` fetches synthetic search HTML, ignores the snippet number `(212) 555-0199`, and saves `+12125550144` from `https://carbone.example/contact`. |
| Saved terms | Collecting snapshot stores Carbone, party 4, `2026-10-02`, `19:30`, `America/New_York`, guest Tarun, and the verified phone. Owner and callback stay empty until a later message. |
| Same-chat authorization | `yes, party of 6` updates the party and does not prepare a call. A later `yes` prepares one body whose opening is `I am calling on behalf of Ada` and whose customer number is the verified phone. `dry_run=True` leaves `place_call` empty and the snapshot `authorized` with no call id. |
| Wrong chat | `Rally, yes` in the other allowlisted group does not prepare a call or attach that chat to the brief. |
| Repeated webhook | Posting the same ask guid again does not send a second reply, refetch, or add a second archive row. Posting the same `yes` again does not prepare a second body. |
| Archive | The allowlisted ask is stored once with the fake sender. |
| Reply prefix | Restaurant, browser, web, and ordinary replies do not start with `Rally:`. The ordinary route returns `pong`. |
| Browser search and web answer | `Hey Rally, search for Example Domain` is answered from the scripted public page and does not claim a booking. The weather request is handled by the injected web function. A temp-db sentinel was not copied into the fetch URL, the browser planner payload, the web request, or the Vapi body. |
| Host evidence | An in-memory `place_call` (not `api.vapi.ai`) plus `reconcile_calls` and `deliver_pending` sends one line: `booked Carbone for 4 on 2026-10-02 at 19:30 America/New_York under Tarun. confirmation AB12.` A second reconcile sends nothing. Snapshot state is `confirmed`. |
| Assistant evidence | The same sentence from `assistant`, plus structured `confirmed` / `AB12` and an unlabeled transcript, delivers one `unresolved` line. It does not contain `booked`, `AB12`, or `confirmation`. State is `unresolved`. |

### Logged-out public browser

Before the fix, `test_public_browser_discovery_does_not_open_the_owner_profile` failed. The webhook still read `+12125550177` from `https://carbone.example/visit`, but `page_for_venue` called the browser with the owner profile:

```text
AssertionError: [('act', True), ('observe', True)]
assert [('act', True), ('observe', True)] == [('act', False), ('observe', False)]
```

`authenticated=True` opens the persistent owner context (`_open_owner_context`). `authenticated=False` does not reject the action. It launches a separate ephemeral Chromium context with no owner cookies, then runs search or navigate. Owner-chat browser tasks still pass `authenticated=True`. Allowlisted group tasks and restaurant discovery pass `authenticated=False`. A configured vendor on the runtime only supplies a public URL; that page is read in the same logged-out session. If the vendor call fails, discovery still searches there.

After the fix, the same end-to-end test passes. `tests/test_browser_runtime.py` navigates the owner profile and `restaurant-lookup` in one runtime: the public page loads, and only the owner chat keeps `owner-cookie-value`. Vendor tests show a group Browser Use search and a lookup vendor URL do not call the owner reader.

### Commands after the fix

```text
.venv/bin/python -m pytest tests/test_demo_end_to_end.py tests/test_browser_agent.py tests/test_browser_integration.py tests/test_browser_runtime.py -q --tb=short
```

Focused: **49 passed**, 1 Starlette deprecation warning, 0.85s.

```text
.venv/bin/python -m pytest -q --tb=line
```

Full suite: **770 passed**, 57 subtests passed, 1 Starlette deprecation warning, 10.05s. Exit code 0.

The demo end-to-end file still uses a temp SQLite database, `schedule=False`, sender `+15555550123`, and a `socket.create_connection` guard. No BlueBubbles text, Vapi call, portal deploy, or production database write was made.

The running Rally process was not restarted. It still has the previous browser code loaded. Restart that process before a live public lookup should use the logged-out session.

### Gaps

- Dry-run authorization does not store a provider call id, so `reconcile_calls` returns 0 and queues no outcome. Host and assistant evidence were checked on a separate in-memory `place_call` with `dry_run=False`. That method never uses `httpx`.
- There is no HTTP route for Vapi status. The scheduler calls `ReservationCallInbound.reconcile_calls` and then `deliver_pending`. The test calls those two methods on the same objects passed into `create_app`. `schedule=False` keeps the lifespan loop from running.
- Configured Browser Use and Grok were not called. The web reply is an injected function, and the browser page is a scripted observation. A live group text and a public archive upload were not attempted.
- The ordinary `say pong` path does pass the temp chat thread into `answer_direct`. Public lookup, the web function, the browser planner payload, and the Vapi body did not receive that sentinel.
