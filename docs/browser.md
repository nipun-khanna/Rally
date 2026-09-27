# Local browser setup

Rally's browser is optional and disabled by default. It runs on the same Mac as Rally and BlueBubbles. Only the configured private owner chat can use it. That GUID contains `;-;` (semicolon-minus), usually `iMessage;-;…` or `any;-;…` on this Mac's BlueBubbles. Group chats use `;+;` (including HackGT13) and never receive the owner profile, cookies, or browser tool.

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
| `RALLY_BROWSER_OWNER_CHAT_ID` | Exact private chat GUID (`iMessage;-;…` or `any;-;…`). Group GUIDs (`*;+;*`) are rejected. |
| `RALLY_BROWSER_OWNER_SENDER_ID` | Exact BlueBubbles sender handle (phone, email, or `local-imessage-account` if you text from this Mac). |
| `RALLY_BROWSER_ADMIN_TOKEN` | Separate from `RALLY_ADMIN_TOKEN`. At least 32 characters. Required for `/browser/status`, `/browser/start`, and `/browser/stop`. |
| `RALLY_BROWSER_PROFILE_PATH` | Isolated profile. Must stay under `data/browser/`. Default `data/browser/profile`. |
| `RALLY_BROWSER_DOWNLOAD_PATH` | Download directory under `data/browser/`. Default `data/browser/downloads`. |
| `RALLY_BROWSER_MAX_ACTIONS` | 1–12 planner steps. Default 6. |
| `RALLY_BROWSER_MAX_TEXT_CHARS` | 1000–12000 observation characters. Default 6000. |

Generate the admin token with `python -c 'import secrets; print(secrets.token_urlsafe(32))'`. Do not reuse `RALLY_ADMIN_TOKEN`.

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
