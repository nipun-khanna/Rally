# Google Calendar and group-reported availability

Rally uses one configured Google account: the Rally owner. With Calendar enabled, Rally can read that account's free/busy intervals for a proposed date and add an event to that same calendar after the group's explicit approval. It does not read other members' calendars, add guests, or send invitations.

When Rally needs a time, it asks the group to share general availability in iMessage. Rally understands a deliberately small set of clear statements, including “free all day Saturday” and “weekdays after 4pm.” It stores each report against the active plan and plan version, and waits for the known participant count from the plan before suggesting a time. Unsupported or ambiguous replies are clarified. A proposed slot must fit the reports and the owner's Google Calendar; Rally describes member availability as self-reported and does not imply that silent members are free. If members prefer another date, they can explicitly ask Rally to change the plan date, which clears the existing reports.

## Setup

1. Create or choose a Google Cloud project, enable Google Calendar API, configure its OAuth consent screen, and create an OAuth client for the Rally owner's account.
2. Authorize both `https://www.googleapis.com/auth/calendar.events` and `https://www.googleapis.com/auth/calendar.events.freebusy` with offline access. The second scope enables the FreeBusy query; an existing event-only refresh token needs renewed consent. Store credentials server-side and keep `RALLY_CALENDAR_ENABLED=0` until setup is complete.
3. Set `RALLY_GOOGLE_CLIENT_ID`, `RALLY_GOOGLE_CLIENT_SECRET`, `RALLY_GOOGLE_REFRESH_TOKEN`, `RALLY_GOOGLE_CALENDAR_ID` (normally `primary`), `RALLY_TIME_ZONE`, and `RALLY_MAX_CALENDAR_REQUESTS`. The default persisted application cap is 20 Calendar operations per UTC day and applies to free/busy checks and event attempts.
4. For a plan that needs a time, Rally asks group members to report availability. Once it can find a candidate against those reports and the owner's free/busy response, it proposes the venue and time. Reply `Book it and add a calendar event` to approve the demo reservation and owner-calendar event.

Google's [FreeBusy API](https://developers.google.com/workspace/calendar/api/v3/reference/freebusy/query) returns only busy intervals, which Rally keeps; it does not read event titles. If the calendar is inaccessible or the response has errors, Rally treats owner availability as unknown and does not make a shared-slot suggestion. Reports are tied to the active plan version; changing plan terms clears them. Rally checks the owner's calendar when choosing a slot and again immediately before writing an approved event. A calendar can still change after a check.

The event uses the existing deterministic ID and reconciliation path. It is written only to the configured owner calendar, with no attendees, and an uncertain result remains unconfirmed for operator inspection. The reservation and event outcomes are reported separately.

Google currently documents standard Calendar API use as having no additional cost under its published daily threshold. Current thresholds may vary by project age; Google's quota page says rules may change later in 2026. Rally's much smaller local cap remains the operational guardrail. See [Google Calendar API quotas and pricing](https://developers.google.com/workspace/calendar/api/guides/quota).

Adapter and service tests use fake transports and local fixtures. They cover approval gating, OAuth refresh, FreeBusy errors, slot intersections, explicit-time conflicts, duplicate reconciliation, daylight-saving ambiguity, quota failure, and uncertain outcomes. Live Google validation requires an owner OAuth grant containing both scopes.
