# Local browser setup

Rally's browser is optional and disabled by default. It runs on the same Mac as Rally and BlueBubbles. Browser tasks, approvals, and local status routes are implemented in later phases; this setup only prepares an isolated login profile.

## Install and configure

From the repository root, install the pinned Python dependencies, then install only Chromium:

```sh
python -m pip install -r requirements.txt
python -m playwright install chromium
```

The Chromium download adds a few hundred megabytes. Rally does not download it during tests or startup. Copy `.env.example` to `.env` if needed, set `RALLY_BROWSER_ENABLED=1`, `RALLY_BROWSER_OWNER_CHAT_ID` to the exact private `iMessage;-;...` chat GUID, and `RALLY_BROWSER_OWNER_SENDER_ID` to the exact sender handle from BlueBubbles. A group GUID is rejected. Export the variables before running Rally or the login script:

```sh
set -a
. ./.env
set +a
python scripts/browser_login.py
```

The script opens a visible Chromium window using `data/browser/profile`, separate from your everyday browser. Sign in manually and complete MFA in that window. The script waits until you close the window. It does not print passwords, cookies, or storage state. Keep the Mac's local account and `data/browser/` private. The profile and downloads stay under the ignored `data/browser/` directory; the script restricts their directory permissions to `0700`.

`RALLY_BROWSER_MAX_ACTIONS` defaults to 6 and accepts 1–12. `RALLY_BROWSER_MAX_TEXT_CHARS` defaults to 6000 and accepts 1000–12000. You may move the profile and download directories only within `data/browser/`.

For future local browser status and lifecycle routes, generate a separate admin token with `python -c 'import secrets; print(secrets.token_urlsafe(32))'` and set `RALLY_BROWSER_ADMIN_TOKEN`. Use a token distinct from `RALLY_ADMIN_TOKEN`; these routes require it when they are added.

## Reset or disable

Close the browser window before resetting its profile. Delete `data/browser/profile` to clear saved website sessions; delete `data/browser/downloads` to clear downloaded files. To disable browser support, set `RALLY_BROWSER_ENABLED=0` and restart Rally. Disabling does not delete the profile, so remove it separately if you no longer want saved sessions.
