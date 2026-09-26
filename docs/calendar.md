# Google Calendar integration

Rally can add a two-hour event to a configured Google Calendar after the group explicitly approves **both** the concrete plan and calendar creation. It does not invite attendees or send email. The event belongs to the Google account that authorized the configured calendar.

Google's [Calendar API quota and pricing page](https://developers.google.com/workspace/calendar/api/guides/quota) says standard use currently has no additional cost and lists a daily no-charge threshold of 1,000,000 requests per project, plus per-minute limits. Google says billing rules may change later in 2026. Keep a much smaller application request cap and stop at provider errors. The adapter makes one OAuth refresh request and one [event insert](https://developers.google.com/workspace/calendar/api/v3/reference/events/insert) request; it makes an [event get](https://developers.google.com/workspace/calendar/api/v3/reference/events/get) request only when insert returns a duplicate ID or its response is lost.

## Setup

1. Create a Google Cloud project, enable the Google Calendar API, configure an OAuth consent screen, and create an OAuth client for the account that owns the target calendar.
2. Authorize the `https://www.googleapis.com/auth/calendar.events` scope with `access_type=offline` and obtain a refresh token. See Google's [web-server OAuth guide](https://developers.google.com/identity/protocols/oauth2/web-server-app). Store the client ID, client secret, refresh token, and calendar ID as server-side secrets. Use `primary` only if the authorized account's primary calendar is intended.
   Set `RALLY_CALENDAR_ENABLED=1`, `RALLY_GOOGLE_CLIENT_ID`, `RALLY_GOOGLE_CLIENT_SECRET`, `RALLY_GOOGLE_REFRESH_TOKEN`, and `RALLY_GOOGLE_CALENDAR_ID` in the server environment. The default `RALLY_MAX_CALENDAR_REQUESTS=20` caps event attempts per UTC day; configure a smaller positive value if needed. The calendar option is disabled by default, and incomplete credentials fail at startup when it is enabled.
3. Include “create a calendar event” in the exact proposal shown to the group. Store the approving message against that proposal. Only then call `create_calendar_event` with a `CalendarApproval` whose `includes_calendar` field is true and whose proposal/message IDs match the persisted approval.
4. Report the calendar outcome separately from the demo reservation. If the Calendar API fails, the reservation can still be confirmed; do not say a calendar event was created.

The adapter uses a deterministic event ID derived from the proposal ID and includes the approved terms and approval message in private event properties. A duplicate ID is accepted only when Google returns matching proposal details. When an insert outcome cannot be confirmed, retain an uncertain state for operator inspection. Calendar invitations are not sent, because chat sender IDs are not verified email addresses.

No live Google Calendar call can be made until the OAuth application and authorized refresh token are configured. The code-level adapter tests use a fake HTTP transport and cover approval gating, OAuth refresh, event payload, duplicate reconciliation, daylight saving ambiguity, quota failure, and an uncertain network outcome. An unconfirmed calendar result is retained for operator inspection rather than retried automatically.
