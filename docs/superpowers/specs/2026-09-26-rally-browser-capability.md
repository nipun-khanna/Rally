# Rally browser capability

**Status:** Draft for product review
**Date:** 2026-09-26
**Product source:** `PRD.md`; this extends adaptive Rally requests and existing public web research.

## Purpose

Rally should be able to use a real browser to carry out explicitly requested web tasks. This includes opening and reading public pages, navigating between pages, searching, clicking, typing, scrolling, capturing page state, and using a user-authenticated browser session to interact with sites. The browser is a registered Rally capability; it is not the Codex session's browser and does not replace BlueBubbles/iMessage.

Success means an explicitly addressed request such as “Rally, check the airline site and find my booking” can be planned into browser steps, executed against a real page, and reported accurately. Requests requiring a consequential change to a third-party site stop for user approval immediately before that change.

## Existing foundation

- `app/web.py` provides read-only xAI Responses API `web_search` for public/current research. It sends the explicit request, not surrounding group history or relationship-source texts.
- `app/adaptive/tools.py` provides a registry of trusted, schema-checked tools scoped to allowlisted chats. Model output can select registered tools but cannot register new handlers.
- `app/adaptive/agent.py` plans at most three steps. The existing step approval model binds approvals to request, revision, step, and argument hash.
- Adaptive tool results and browser page contents can contain untrusted instructions. Existing prompts already say tool output is not permission to perform side effects; browser results need the same rule, enforced outside the model as well.

## Proposed architecture

### Local browser runner

Run a browser runner on the same Mac as the BlueBubbles/Rally service. It controls a dedicated browser profile through a maintained browser automation library (Playwright is the proposed implementation), exposed only to the local Rally process over a loopback-only interface. It must not bind to a public network interface. Rally's normal service process remains the orchestrator and policy authority; page JavaScript is never executed as arbitrary agent code.

The profile is isolated from the user's everyday browser profile. The user completes sign-in and multi-factor authentication directly in the browser UI. Rally stores neither passwords nor copied authentication tokens. Session cookies remain in the dedicated browser profile, so the profile directory must have owner-only permissions and a documented sign-out/reset operation. A browser restart must not silently switch to another profile.

The runner exposes small typed operations rather than raw Playwright or shell access:

- open a public URL and report the final URL/page title;
- inspect visible page text and relevant accessible controls;
- click a uniquely identified visible control;
- enter text into a uniquely identified field;
- scroll and wait for a page state change;
- capture a bounded screenshot for visual pages;
- download a file into a dedicated downloads directory and report its path and metadata.

No operation accepts arbitrary JavaScript, shell commands, arbitrary local filesystem paths, browser profile paths, or raw credentials. File upload is out of scope for the first implementation; if added later, it must be a separate operation with explicit per-file consent.

### Rally tool integration

Register browser operations in the existing adaptive tool registry. A browser task is initiated only by an explicit direct Rally request; passive monitoring, unrelated group messages, relationship analysis, and scheduled work cannot open pages. The planner receives the current request and operation metadata. It receives only the page data needed for that task, not unrelated chat history or relationship source messages.

The runner returns bounded, sanitized page observations: title, final URL, visible text excerpt, and stable control labels/roles. Set per-task limits for steps, navigation time, page text, screenshots, and downloads. Preserve request/step identifiers and an audit record of requested URL, visited URLs, operations, approvals, and outcome; do not persist page bodies or screenshots after the task unless the user explicitly asks to save an artifact.

### Approval and action model

Reading, searching, navigating, scrolling, and inspecting pages are read actions and may proceed under the explicit request. Clicking or typing is allowed only when it is part of the requested task and does not cross the consequential-action boundary.

Before a third-party side effect, Rally must show the user the site, exact action, and material data being submitted, then obtain a fresh approval bound to the current request revision, browser tab, target site, control, and submitted values. Side effects include posting or sending content, submitting a form, purchasing, booking, deleting, changing account/security settings, accepting legal terms, or granting access. Approval expires if the page or values change. A prior approval cannot authorize a later or different action. Rally must not infer approval from a request to “do everything,” page content, a saved workflow, or an approval for a different step.

After approval, execute only the displayed action and report whether the site confirmed completion. If the outcome is ambiguous (for example, the connection times out after clicking Submit), mark it uncertain and do not automatically retry.

### Security and privacy

- Treat all page text, metadata, screenshots, downloaded documents, and linked content as untrusted data. Ignore instructions found in them that attempt to change Rally's system policy, expose secrets, access other chats, or perform unrequested actions.
- Validate every initial and redirected URL. Allow public HTTP(S) sites only; block loopback, private, link-local, multicast, reserved, local-domain, and cloud metadata targets, including DNS resolutions that land on those ranges. Revalidate redirects and navigation initiated by clicks.
- Restrict browser access to the dedicated profile and download directory. Apply file size/type limits and reject executable or script downloads by default. Never automatically open downloaded files.
- Do not expose BlueBubbles credentials, xAI keys, calendar tokens, browser cookies, or personal relationship records to a page or to tool output.
- A browser task may send the explicit request and the task-relevant page excerpts to the configured model provider for planning. Do not include surrounding group messages, private relationship source text, or unrelated page/profile data. This provider disclosure must be clearly documented in setup. A local model path can be evaluated separately; it is not a prerequisite for the initial browser runner.
- Require a local authenticated/authorized caller boundary and reject browser requests from public webhook callers unless the chat and user policy explicitly permit the adaptive browser tool.
- Provide a global disable switch and per-chat browser enablement. Browser disabled, disconnected, authentication-required, blocked URL, and uncertain action states must be reported without falling through to fabricated results.

## User experience

1. An operator enables the browser runner locally and enables the tool only for selected chats.
2. The user signs into desired websites in the isolated browser themselves.
3. The user directly asks Rally to complete a web task.
4. Rally states when login or a missing step blocks progress. It uses browser operations and summarizes evidence with the site URL.
5. If the next step changes external state, Rally shows the exact pending action and waits for a direct approval in the same authorized Rally channel.
6. Rally executes once, reports confirmed or uncertain outcome, and leaves the browser session available for future explicitly requested tasks.

The browser can access sites that are reachable from the Mac. It is not a remote browser service: if Rally is later hosted on another machine, this runner remains on the Mac and requires an authenticated private connection or a separately designed deployment topology.

## Scope

### Initial implementation

- Local, isolated browser runner and setup/status documentation.
- Read and interact with public pages and sites where the user has signed into the dedicated browser profile.
- Adaptive tool planning, bounded page observations, domain/IP protections, safe download handling, policy-bound approvals for external side effects, request-scoped audit records, and deterministic error states.
- Synthetic local test pages for login-state, multi-step reading, confirmation boundaries, prompt-injection attempts, redirects, private-address blocking, timeout, and uncertain submission outcomes.

### Out of scope

- Storing website passwords or automating credential entry/MFA.
- Arbitrary shell access, arbitrary page JavaScript, local file uploads, payment credential handling, CAPTCHA circumvention, or bypassing site access controls.
- Unattended background browsing, monitoring websites, or taking side effects without a current user request and approval.
- Replacing the existing xAI public web search, BlueBubbles transport, relationship data store, or calendar integration.
- Deploying browser control on Vercel or exposing the local runner publicly.

## Acceptance criteria

1. An enabled, allowlisted chat can explicitly ask Rally to open a public site and summarize task-relevant visible content with the final URL.
2. Rally can reuse a manually authenticated isolated browser profile without the app ever receiving or logging the user's password or cookie values.
3. The planner can use page observations to select further registered browser steps, within configured per-request limits.
4. A direct request can authorize non-consequential navigation and data entry, but a third-party submission/change remains blocked until exact current action approval.
5. Changing the tab, destination, field values, request revision, or displayed action invalidates approval; duplicate or uncertain submissions are never retried automatically.
6. Malicious page instructions cannot register tools, access secrets, change chat scope, or bypass confirmation.
7. Public URL validation blocks private/internal targets and redirect/DNS rebinding attempts before navigation.
8. Downloads are size/type constrained, remain in the dedicated directory, and are never auto-opened.
9. Browser tasks do not include surrounding group history or personal relationship source messages in model/tool payloads.
10. Disconnected/disabled browser and all policy blocks return clear status to the user; tests demonstrate each relevant allow/deny path.
11. Existing web research, iMessage planning, and relationship flows continue to work with the browser disabled.

## Open implementation decisions

- Select and pin a supported browser automation package compatible with the Mac runtime; verify licensing and install footprint before adding it.
- Choose the local runner transport and process lifecycle (in-process browser process versus a separately supervised loopback service) based on isolation and reliability tests.
- Define the approval UI/transport for a pending browser side effect. Group-chat approval must name the action and submitted values clearly; personal/account sites may require a private approval destination.
- Define screenshot-to-model handling, size limits, and whether visual evidence stays in memory or is redacted before any provider call.
- Pick configurable per-request navigation/step/text/download limits and document provider/browser operating costs.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Prompt injection in a page attempts data theft or an unauthorized action | Treat page observations as untrusted; keep policy in trusted code; validate each tool operation and require exact side-effect approval. |
| Browser session grants access to personal accounts | Dedicated local profile, manually entered credentials, owner-only profile storage, explicit chat allowlist, no page data retention by default. |
| SSRF through URLs, redirects, DNS, or page navigation | Public-address validation at every navigation boundary, redirect checks, block private/reserved ranges and metadata addresses. |
| Accidental duplicate purchase/post after timeout | Persist step state, mark ambiguous outcomes uncertain, never retry external side effects automatically. |
| Sensitive page content reaches the model provider | Send only explicit request and bounded task-relevant excerpts; do not include group history or relationship source texts; make provider flow clear at setup. |
| Local Rally host is unavailable to users elsewhere | Keep runner local for initial release and document the topology requirement; do not claim hosted browser support. |

## Review checklist

- [x] Tied browser use to the Rally agent and existing adaptive registry, not the Codex browser session.
- [x] Includes authenticated browsing and broad page interactions requested by the user.
- [x] Defines exact approval boundaries for consequential external actions.
- [x] Covers prompt injection, private-network navigation, credentials, downloads, provider data flow, and ambiguous delivery.
- [x] Keeps the browser local to the BlueBubbles host and preserves existing search/iMessage/relationship architecture.
- [x] Defines testable acceptance criteria and identifies implementation decisions that need resolution before coding.
- [x] No placeholders or conflicting execution promises found.
