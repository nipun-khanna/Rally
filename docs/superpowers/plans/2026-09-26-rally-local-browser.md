# Rally Local Browser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Rally carry out explicit browser tasks on the same Mac as BlueBubbles, including manually authenticated website workflows, while preventing group chats from using or seeing private account sessions.

**Architecture:** Add a local Playwright/Chromium runtime behind Rally's existing schema-checked adaptive tool registry. Group chats get an ephemeral unauthenticated, read-only browser; one locally configured private chat can use the dedicated persistent profile and request-bound approvals for external actions. A SOCKS5 egress guard resolves public addresses once, rejects private/reserved destinations, and connects to the checked address.

**Tech Stack:** Python 3.13; Playwright Python 1.63.0; Playwright-managed Chromium; existing FastAPI, Pydantic, SQLite, BlueBubbles, xAI structured-output client, and pytest.

**Spec:** `docs/superpowers/specs/2026-09-26-rally-browser-capability.md`

## Global Constraints

- Run Rally's browser on the Mac hosting Rally/BlueBubbles; do not add a remote browser service or publicly reachable browser endpoint.
- Keep browser use disabled by default and install only Chromium with `python -m playwright install chromium` when enabled.
- Keep the persistent browser profile separate from the user's regular profile and set its directory permissions to `0700`.
- Allow group-chat tasks only in an ephemeral unauthenticated context; allow authenticated browsing and external side effects only in the configured private chat and for its configured sender ID.
- Do not store or log website passwords, cookies, page bodies, screenshots, or downloaded file contents.
- Never give model output arbitrary JavaScript, shell, filesystem, or credential access; accept only registered, schema-checked browser actions.
- Require exact, fresh approval for form submission and other third-party side effects; do not retry an uncertain action automatically.
- Treat all page content as untrusted instructions and send only the current request plus bounded, relevant page observations to xAI.
- Use synthetic local sites for automated tests; tests must not sign in to real accounts or make external changes.
- Pin Playwright to `1.63.0`; its Python package is Apache-2.0 and its supported browser builds are separately installed. Its documentation notes macOS 14+ support and that managed browser binaries take a few hundred megabytes. [Python package](https://pypi.org/project/playwright/1.63.0/), [installation and system requirements](https://playwright.dev/python/docs/intro), [browser installation and disk usage](https://playwright.dev/python/docs/browsers).

## Review Focus

1. A hostname resolves to a private or reserved address, including after a redirect; the browser must reject it before connecting. Test mixed public/private DNS answers and a redirect to `127.0.0.1`.
2. A group asks Rally to inspect a site while the persistent profile is signed in; Rally must use the clean ephemeral profile and must not expose account data. Test that cookies from the owner profile are absent in a group task.
3. A malicious page instructs Rally to reveal secrets or change policy; Rally must treat it as page text and continue only within the user request. Test a fixture containing prompt-injection text.
4. A task is about to submit a form, post, purchase, delete, or change settings; Rally must wait for exact current-action approval from the initiating owner in the same private chat. Test wrong actor, wrong token, edited values, and duplicate approval.
5. The browser closes, authentication expires, a download exceeds policy, or a submission times out; Rally must return a specific status and never invent success or retry an uncertain action. Test each status with injected browser/provider failures.

## File Structure

- `app/browser/url_policy.py`: public URL, hostname, and IP validation.
- `app/browser/egress.py`: loopback SOCKS5 proxy; resolve DNS once, reject non-global addresses, connect only to the validated address, and tunnel bytes without decrypting HTTPS.
- `app/browser/runtime.py`: Playwright startup/shutdown, isolated profiles, safe page observations, typed browser actions, and bounded downloads.
- `app/browser/agent.py`: structured one-action-at-a-time planner for the browser; page observations are explicitly untrusted.
- `app/browser/store.py`: durable browser request, pending approval, and minimal audit metadata in SQLite; no page body persistence.
- `app/adaptive/tools.py`: tool context with chat/sender/request metadata, per-chat visibility, and the `browser_task` registration.
- `app/adaptive/handler.py`: execute the single registered browser task and format pending approval/completion states.
- `app/orchestrator.py`, `app/main.py`, and `app/bluebubbles.py`: owner-bound private-chat routing and approval/cancel handling before normal extraction; explicitly allow only the configured browser owner thread through webhook normalization.
- `app/config.py`, `.env.example`, `requirements.txt`, `.gitignore`: opt-in configuration, package pin, and ignored profile/download storage.
- `scripts/browser_login.py`: local headed browser launch for manually completing login/MFA in the isolated persistent profile.
- `app/main.py`: local-authenticated browser status and task review routes; bind approval actions to the task's current action digest.
- `tests/test_browser_*.py`: policy, proxy, runtime, agent, store, route, privacy, and synthetic end-to-end tests.
- `docs/browser.md`: install/start/login/reset/disable, privacy, approval, and troubleshooting guide.

## Interfaces

```python
@dataclass(frozen=True)
class ToolContext:
    chat_id: str
    sender_id: str
    message_id: str
    request_text: str

@dataclass(frozen=True)
class BrowserObservation:
    url: str
    title: str
    text: str
    controls: tuple[dict[str, str], ...]

class BrowserRuntime:
    def observe(self, *, chat_id: str, authenticated: bool) -> BrowserObservation: ...
    def act(self, *, chat_id: str, authenticated: bool, action: dict) -> dict: ...

class BrowserTaskService:
    def run(self, context: ToolContext, request: str) -> dict: ...
    def resolve_approval(self, context: ToolContext, code: str, approve: bool) -> dict | None: ...
```

`authenticated` is true only when `context.chat_id == RALLY_BROWSER_OWNER_CHAT_ID`, the chat is a direct `iMessage;-;...` thread, and `context.sender_id == RALLY_BROWSER_OWNER_SENDER_ID`. Group requests always use a new nonpersistent context and reject any action classified as externally state changing.

## Tasks

### Task 1: Opt-in local browser configuration and setup

**Files:** `requirements.txt`, `.env.example`, `.gitignore`, `app/config.py`, `scripts/browser_login.py`, `tests/test_config.py`, `tests/test_browser_setup.py`, `docs/browser.md`.

**Interfaces:** `Settings` gains `browser_enabled`, `browser_owner_chat_id`, `browser_owner_sender_id`, `browser_admin_token`, `browser_profile_path`, `browser_download_path`, `browser_max_actions`, and `browser_max_text_chars`. The feature defaults off. If enabled, it requires a direct owner chat, a sender ID, and limits in the ranges 1–12 actions and 1000–12000 observation characters. Local status/lifecycle routes require a separately configured high-entropy admin token.

- [ ] Add a failing settings test asserting browser defaults off and owner identity is mandatory when enabled.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_config.py::test_browser_defaults_off_and_requires_private_owner` and confirm the missing settings assertion fails.
- [ ] Pin `playwright==1.63.0`, add opt-in environment examples, and add `data/browser/` to `.gitignore`.
- [ ] Add typed settings and reject a group GUID, missing sender, profile path outside `data/browser/`, or out-of-range limits when browser support is enabled.
- [ ] Implement `scripts/browser_login.py` to launch only the dedicated headful persistent Chromium profile, create it with mode `0700`, and exit after the user closes the browser; never print storage state or credentials.
- [ ] Document `python -m playwright install chromium`, `python scripts/browser_login.py`, profile reset, disable, and the fact that Chromium download adds a few hundred megabytes.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_config.py tests/test_browser_setup.py` and confirm setup/configuration tests pass without needing a browser download.
- [ ] Commit as `feat: add opt-in local browser setup`.

### Task 2: Public URL policy and DNS-pinned local egress

**Files:** `app/browser/url_policy.py`, `app/browser/egress.py`, `tests/test_browser_url_policy.py`, `tests/test_browser_egress.py`.

**Interfaces:** `validate_public_url(value: str, resolver=socket.getaddrinfo) -> str` accepts only HTTP(S), rejects credentials, nonstandard ports, local names, and any non-global resolved address. `PublicEgressProxy.start() -> str` returns its loopback SOCKS5 URL; `close()` stops it. CONNECT requests resolve once, reject the full answer set if any address is non-global, and dial the selected validated IP rather than resolving the hostname a second time.

- [ ] Write failing URL tests for schemes other than HTTP(S), embedded credentials, malformed hostnames, loopback/private/IPv6 link-local ranges, local suffixes, DNS failure, and mixed public/private answers.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_browser_url_policy.py` and verify each disallowed input is rejected.
- [ ] Implement URL canonicalization using `urllib.parse.urlsplit`, `ipaddress.ip_address`, and injected `getaddrinfo`; accept only ports 80 and 443.
- [ ] Write failing async SOCKS5 proxy tests for private destinations, unsupported ports, DNS rebinding, connection refusal, and a public resolution whose socket receives the exact validated IP.
- [ ] Implement the loopback SOCKS5 handshake and CONNECT tunnel with a single pinned DNS result; cap concurrent connections, header size, and connection duration; log only a rejection reason, never URL query strings.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_browser_url_policy.py tests/test_browser_egress.py` and confirm the proxy cannot dial any rejected address.
- [ ] Commit as `feat: guard local browser network egress`.

### Task 3: Isolated Playwright runtime and bounded operations

**Files:** `app/browser/runtime.py`, `tests/test_browser_runtime.py`, `tests/browser_fixtures.py`, `requirements.txt`.

**Interfaces:** `BrowserRuntime(profile_path, downloads_path, proxy_url, max_text_chars)` starts the owner profile lazily and keeps one page per authorized chat. `observe(chat_id, authenticated)` returns only final public URL, title, bounded visible text, and accessible control labels. `act(chat_id, authenticated, action)` accepts only `navigate`, `inspect`, `click_link`, `fill`, `scroll`, `screenshot`, and `download`; it rejects selectors and paths outside the typed schema.

- [ ] Create a local synthetic fixture server with public test hostname resolution injected into the egress proxy; add failing tests for navigation, redirect blocking, visible text bounds, control descriptions, cross-chat isolation, and popup rejection.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_browser_runtime.py` and confirm tests fail because the runtime is absent.
- [ ] Implement a synchronous Playwright manager that runs tasks headlessly by default; launch headed Chromium only from the explicit local login/setup command. Attach the SOCKS proxy with no bypass list, block service workers, disable non-proxied UDP, and close cleanly at application shutdown.
- [ ] Create a new ephemeral context for every group task; create an owner-only persistent context only for the configured private chat and sender. Never expose the owner context's cookies/storage state to any tool result.
- [ ] Implement typed locators using role/name pairs with strict uniqueness; bound each navigation/action to the configured timeout; downloads land only in the configured directory, must satisfy size/type limits, and are never opened automatically.
- [ ] Add fixed local routing checks for every top-level, redirect, popup, frame, and subresource URL before continuing through the DNS-pinned proxy; route tests cover a page attempting to fetch localhost.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_browser_runtime.py tests/test_browser_url_policy.py tests/test_browser_egress.py` and confirm all runtime and egress fixtures pass.
- [ ] Commit as `feat: add isolated Playwright browser runtime`.

### Task 4: Structured browser agent loop

**Files:** `app/browser/agent.py`, `app/adaptive/agent.py`, `app/adaptive/tools.py`, `app/adaptive/handler.py`, `tests/test_browser_agent.py`, `tests/test_adaptive_tools.py`, `tests/test_adaptive_handler.py`.

**Interfaces:** `BrowserActionDecision` is a strict Pydantic model with action enum, target URL, role/name locator, field text, scroll direction, and completion answer. `BrowserTaskService.run(context, request)` sends the model only the explicit request and current bounded observation, takes at most 12 steps, and returns a result with URLs/evidence or an approval-required record. `ToolContext` is injected by trusted message handling; it is never model supplied.

- [ ] Add tests that reject arbitrary tool names, JavaScript, filesystem paths, unsupported actions, extra JSON fields, and requests to use page content as system instructions.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_browser_agent.py tests/test_adaptive_tools.py` and verify malformed agent decisions fail closed.
- [ ] Implement one-step structured decisions with page observations labeled untrusted and explicit instructions to ignore embedded page commands; constrain action count to `browser_max_actions` and text to `browser_max_text_chars`.
- [ ] Extend adaptive tool metadata with per-chat visibility and trusted `ToolContext`; preserve existing handler behavior for plan status and web research.
- [ ] Register a single `browser_task(request)` tool only when enabled; the inner browser agent selects typed actions and cannot call unregistered Rally tools.
- [ ] Update adaptive routing to recognize direct browser requests such as “open this site,” “log in,” “click,” and “fill this form” while preserving existing portal, relationship, and planning route precedence.
- [ ] Add a browser-owner inbound path for the single configured direct thread: verify the BlueBubbles sender ID, pass the current message as trusted `ToolContext`, and never send it through group plan/portal/history processing. Keep other direct chats rejected unless independently configured for the relationship service.
- [ ] Test that page injection cannot cause a second chat request, leak an environment value, or change the authenticated-context decision.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_browser_agent.py tests/test_adaptive_tools.py tests/test_adaptive_handler.py` and confirm existing web and plan tools still route correctly.
- [ ] Commit as `feat: add registered browser task agent`.

### Task 5: Durable action approvals and owner-only session policy

**Files:** `app/browser/store.py`, `app/browser/agent.py`, `app/browser/runtime.py`, `app/orchestrator.py`, `tests/test_browser_store.py`, `tests/test_browser_approval.py`.

**Interfaces:** Store one request row per `(chat_id, message_id)`, an approval row containing a random short code plus action digest, and minimal audit metadata. `resolve_approval(context, code, approve)` succeeds only for the same chat, same sender, current action digest, pending state, and unexpired code. No body text or screenshots are persisted.

- [ ] Add failing SQLite tests for request deduplication, private owner binding, hashed approval codes, changed-value invalidation, expiry, cancellation, restart recovery to `uncertain`, and no automatic replay.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_browser_store.py tests/test_browser_approval.py` and verify approval cannot cross chats or senders.
- [ ] Implement transactional browser state tables in the configured SQLite file, with owner-only rows keyed by chat and message; persist only request/action hashes, state, URL host/path without query, timestamps, and approval outcome.
- [ ] Classify every form submit and high-impact button action (send/post/purchase/book/delete/settings/permissions/legal acceptance) as a commitment. Stop before clicking, display the site/action/values and one-time code, and expire approval after 10 minutes or any page/value/request change.
- [ ] Route exact `approve CODE` and `cancel CODE` messages before normal extraction in both the configured owner thread and permitted group thread; authenticated tasks can be continued only by their initiating configured owner. A group task may inspect public pages but cannot perform commitments.
- [ ] Treat transport/provider failure after a committed click as `uncertain`; never retry the click. Report confirmed success only after the page provides a verifiable completion state.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_browser_store.py tests/test_browser_approval.py tests/test_orchestrator.py` and confirm duplicate/expired/stale approvals are refused.
- [ ] Commit as `feat: require durable owner approval for browser actions`.

### Task 6: Local setup/status interface, full verification, and runbook

**Files:** `app/config.py`, `app/main.py`, `app/browser/runtime.py`, `app/browser/store.py`, `tests/test_browser_http.py`, `tests/test_browser_integration.py`, `tests/test_browser_security.py`, `docs/browser.md`, `.env.example`.

**Interfaces:** Add admin-authenticated `GET /browser/status`, `POST /browser/start`, and `POST /browser/stop` endpoints. Require a valid `X-Rally-Admin-Token` and a loopback ASGI peer address; do not trust forwarded-client headers. They control the Mac-local Playwright runtime only; they do not accept URLs, arbitrary code, credentials, or approval decisions.

- [ ] Add failing HTTP tests for missing/wrong admin token, non-loopback requests, disabled feature, missing browser install, and local start/status/stop state transitions.
- [ ] Run `.venv/bin/python -m pytest -q tests/test_browser_http.py` and confirm unauthenticated/nonlocal calls are denied.
- [ ] Implement loopback-only setup/status lifecycle routes with no URL query token; return generic errors without secrets or browser storage data.
- [ ] Add full synthetic integration scenarios for public group browse, authenticated private browse, prompt injection, redirect to private IP, one exact approved submission, wrong-owner approval, stale approval, download cap, browser crash, and uncertain submission.
- [ ] Run `.venv/bin/python -m playwright install chromium` on the Rally Mac and execute the synthetic tests with the real managed Chromium binary.
- [ ] Run `.venv/bin/python -m pytest -q` and verify the existing relationship, iMessage, voice, web-search, calendar, and portal suites remain green with browser disabled.
- [ ] Update the runbook with model-provider data flow, local Mac requirement, profile storage/reset, private-chat configuration, costs, startup, disable, and known limitations.
- [ ] Commit as `docs: document Rally local browser setup and verification`.

## Handoff

Implementation should start on a new `feat/local-browser-tool` branch from current `main`, with no changes made to the pushed main branch. Before execution, review the private-chat boundary and the local Chromium install size; these are the main product trade-offs in this plan.
