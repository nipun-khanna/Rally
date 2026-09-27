# Local browser setup

Rally's browser is optional and disabled by default. It runs on the same Mac as Rally and BlueBubbles. Anyone in an allowlisted Rally chat (`RALLY_ALLOWED_CHAT_GUIDS`) can ask Rally to search, open a site, fill a public form, or walk a reservation up to the sign-in page. Off-allowlist chats are ignored. A message must ping Rally or arrive during the 5-minute active turn. Rally never invents passwords or claims a booking is done; it waits on the Mac for a human to confirm.

## Install and configure

From the repository root, install the pinned Python dependencies, then install only Chromium:

```sh
python -m pip install -r requirements.txt
python -m playwright install chromium
```

The Chromium download adds a few hundred megabytes. Rally does not download it during tests or startup. Copy `.env.example` to `.env` if needed and set:

| Variable | Purpose |
| --- | --- |
| `RALLY_BROWSER_ENABLED=1` | Opt in. Defaults off. |
| `RALLY_BROWSER_DEBUG=1` | DEBUG logs on `rally.browser` (launch args, tool calls, recover, Playwright tracebacks). Watch the 8770 process stdout. |
| `RALLY_BROWSER_OWNER_CHAT_ID` | Exact private chat GUID (`iMessage;-;…` or `any;-;…`). Group GUIDs (`*;+;*`) are rejected. |
| `RALLY_BROWSER_OWNER_SENDER_ID` | Exact BlueBubbles sender handle (phone, email, or `local-imessage-account` if you text from this Mac). |
| `RALLY_BROWSER_ADMIN_TOKEN` | Separate from `RALLY_ADMIN_TOKEN`. At least 32 characters. Required for `/browser/status`, `/browser/start`, and `/browser/stop`. |
| `RALLY_BROWSER_PROFILE_PATH` | Isolated profile. Must stay under `data/browser/`. Default `data/browser/profile`. |
| `RALLY_BROWSER_DOWNLOAD_PATH` | Download directory under `data/browser/`. Default `data/browser/downloads`. |
| `RALLY_BROWSER_MAX_ACTIONS` | 1–12 planner steps. Default 6. |
| `RALLY_BROWSER_MAX_TEXT_CHARS` | 1000–12000 observation characters. Default 6000. |
| `RALLY_BROWSER_USE_API_KEY` | Optional Browser Use Cloud key. When set, search/open/fill/reserve go through the vendor agent (`POST /api/v4/runs`). Also accepts `BROWSER_USE_API_KEY`. |
| `RALLY_BROWSERBASE_API_KEY` | Optional Browserbase key for stealth CDP on the local Grok planner fallback. Also accepts `BROWSERBASE_API_KEY`. |
| `RALLY_BROWSERBASE_PROJECT_ID` | Optional. Also accepts `BROWSERBASE_PROJECT_ID`. Inferred from the API key when omitted. |

Generate the admin token with `python -c 'import secrets; print(secrets.token_urlsafe(32))'`. Do not reuse `RALLY_ADMIN_TOKEN`.

## Hosted agent (Browser Use)

Search, open, fill, and reserve-until-human go through a vendor browser agent, not a raw `page.goto` script.

1. Create an API key at [cloud.browser-use.com/settings](https://cloud.browser-use.com/settings?tab=api-keys&new=1).
2. Set `RALLY_BROWSER_USE_API_KEY` (or `BROWSER_USE_API_KEY`) in `.env`.
3. Restart 8770. `/browser/status` reports `backend=browser-use` when the key is loaded.

Rally sends the chat request plus a no-password / `WAIT_FOR_HUMAN` policy to Browser Use Cloud (`POST https://api.browser-use.com/api/v4/runs`). The vendor agent plans clicks, types, and extracts. CAPTCHA and stealth stay on their side.

Without a Browser Use key, Rally falls back to the local one-thread Playwright worker and Rally's Grok planner. Local search uses Google Maps to avoid `/sorry` interstitials. An optional `RALLY_BROWSERBASE_API_KEY` still attaches stealth CDP to that local fallback. Reservations always stop at `wait_for_human` and never submit passwords.

## Find the owner chat GUID and sender

Use a private 1:1 thread, never a group.

**BlueBubbles Server UI:** open the server app → **Chats**. Select the DM (empty title is normal; match the contact name, for example Tarun Devi). Copy the chat **GUID**. Private chats contain `;-;`. Groups contain `;+;` — do not use those, including HackGT13.

**Or query the API** (password stays in the environment, never printed):

```sh
set -a
. ./.env
set +a
curl -s -X POST "$RALLY_BLUEBUBBLES_URL/api/v1/chat/query?password=$RALLY_BLUEBUBBLES_PASSWORD" \
  -H 'Content-Type: application/json' \
  -d '{"limit":200,"sort":"lastmessage"}'
```

Match `displayName` case-insensitively. Unnamed DMs have an empty `displayName`; fall back to participant `address` and local contacts. Confirm the GUID has `;-;` and not `;+;`.

Set `RALLY_BROWSER_OWNER_SENDER_ID` to `local-imessage-account` if you send from this Mac (BlueBubbles `isFromMe`). That is how Rally identifies the signed-in Apple account. If the owner texts from another handle, use that exact phone or email address instead.

Export the variables before running Rally or the login script:

```sh
set -a
. ./.env
set +a
python scripts/browser_login.py
```

The script opens a visible Chromium window using `data/browser/profile`, separate from your everyday browser. Sign in manually and complete MFA in that window. The script waits until you close the window. It does not print passwords, cookies, or storage state. Keep the Mac's local account and `data/browser/` private. Directory permissions are `0700`.

Then start Rally. Live Rally on this Mac binds **8770** (BlueBubbles webhooks already point there). Use that port, or whichever port uvicorn actually printed if you overrode it:

```sh
curl -X POST http://127.0.0.1:8770/browser/start \
  -H "X-Rally-Admin-Token: $RALLY_BROWSER_ADMIN_TOKEN"
```

`GET /browser/status` and `POST /browser/stop` use the same header. These routes accept loopback clients only and do not take URLs, credentials, or approval codes.

In the configured private chat, ask Rally to open a public site or continue a signed-in workflow. Form submit, purchase, and other third-party changes wait for `approve CODE` or `cancel CODE` from the same owner sender. Approvals expire in 10 minutes or if the page values change. Uncertain submissions are not retried.

## Provider data flow

A browser task sends the current owner request plus bounded, labeled-untrusted page excerpts to the configured xAI model. It does not send group history, relationship source texts, cookies, passwords, or page screenshots. All page content is treated as untrusted instructions.

## Reset or disable

Close the browser window before resetting its profile. Delete `data/browser/profile` to clear saved website sessions; delete `data/browser/downloads` to clear downloaded files. To disable browser support, set `RALLY_BROWSER_ENABLED=0` and restart Rally. Disabling does not delete the profile.

## Known limits

- The runner stays on this Mac. It is not a hosted or public browser service.
- Chromium must be installed with Playwright before `/browser/start` succeeds.
- File upload, arbitrary JavaScript, and storing website passwords are out of scope.
- Operating cost is the xAI planning calls plus local Chromium CPU/RAM.
