# Live web-text plan

One authorized HackGT13 text. Branch `feat/mac-phone-grok-voice` stays dirty. No commit, deploy, portal upload, phone POST, or provider-account change.

## Preflight already checked

- Sole listener pid 440 on `127.0.0.1:8770`, started 2026-09-27 05:59:27 local, `RALLY_PORTAL_PUBLISH_APPROVED=0`, `GET /health` 200 `{"status":"ok"}`.
- Loaded settings: web search on, daily limit 0, max tool calls 3, xAI key present, allowlist 4 with 3 groups, exact guid `any;+;chat536074477903103142`.
- BlueBubbles 1.9.9, `private_api` false, one HackGT13 chat, that guid. Webhook is `new-message` to `127.0.0.1:8770/webhooks/bluebubbles` with a token present.
- App files that serve this path are older than pid 440. Messages is running. Outbox was 196 `sent`. Pending human rows 0. Restaurant snapshots 0. Replies in the last minute for this chat 0.
- `[Rally web test] Rally, ...` does not match `explicitly_addresses_rally`. `Rally, search the web: [Rally web test] ...` does, and `should_search_web` is true. It does not match browser, restaurant, or call intent.

## The one send

POST BlueBubbles `/api/v1/message/text` directly. Do not call `app.bluebubbles.send_message`, which remembers the temp guid and text fingerprint before the webhook arrives.

Text:

```text
Rally, search the web: [Rally web test] what is the latest stable Python release? Include the official source link.
```

If that POST is not status 200, or the connection drops, stop. Do not send a second time.

## Outcome

The single POST returned status 200. Probe guid `B890F64B-FF5B-43DE-9994-98DC91ADFCA1` was accepted, processed, and answered by one prefix-free `direct_reply` (`sent`) citing `https://www.python.org/downloads/release/python-3147/`. Reply guid `51A56A11-1EB3-4DC0-AC41-959B47A9A3BF` is the remembered echo. Details are in `docs/live-web-text-check.md`. No retry.

Bookkeeping after that send did not send again. The same probe still has one `sent` reply. Pid 440 stayed up with publication 0. Ignored `data/portal_build` was refreshed locally (3 groups, 135 pages, 970 media) and was not uploaded. The only remaining approval is the public archive upload, recorded in `docs/final-demo-audit.md`.

## What to wait for

Poll the production database for at most 90 seconds for one `direct_reply` whose `ref_id` is the returned message guid.

Pass when all of these are true:

- BlueBubbles accepted the probe and a later history row is that guid.
- The app stored the probe as a human message and marked it processed.
- One outbox row for that guid is `sent`, body does not start with `Rally:`, and the body cites a public Python source URL.
- The server log shows one receive and one send for that webhook, and the reply echo does not create a second outbox row.
- Portal publication stays 0. No phone call and no upload.
