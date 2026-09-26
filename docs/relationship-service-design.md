# Rally relationship service — proposed design

## Purpose

Help the user maintain chosen relationships through reminders based on confirmed
contact and user-selected rhythms. Example: remind the user to call Mom when a week
has passed since the last confirmed call. Preserve the existing group planning app.

## Relationship records

Each user owns named relationships with a preferred contact mode, cadence, time zone,
reminder window, pause state, and last confirmed contact. Names are labels until the
user chooses a real contact mapping. Records are private and excluded from the
public group portal and its static exports.

Contact events record mode (call, visit, message, or other), occurrence time, source,
and confidence. A call is confirmed only by an explicit user report or a future
authorized call-data connector. Messaging activity never proves a call happened.

## User interaction

Support setup, status, contact confirmation, cadence changes, snooze, pause, resume,
and removal through explicit Rally requests. Examples: “remind me to call Mom every
week,” “I called Mom today,” “snooze Mom until Friday,” and “pause reminders for Mom.”
Ambiguous names, dates, or frequency require clarification before changing state.
Repeated incoming messages are idempotent. Replies use the authorized destination.

## Scheduling and delivery

The existing scheduler evaluates due relationships in the user's local reminder
window. One reminder per due cycle is persisted through the outbox. Confirmation
starts a new cycle; snoozing changes its next eligible delivery time. Overdue cycles
do not produce repeated messages every tick. Pause and removal cancel unsent
reminders. Failure or uncertain delivery is never reported as successful.

Personal reminders require an explicitly selected private destination or explicit
consent to use the test group. A private destination needs separate transport
allowlisting; normal direct chats remain ignored until configured.

## Learning

Confirmed contact events and accepted cadence changes provide the initial learning
source. Rally can suggest a cadence from sufficient repeated activity, displaying
the supporting pattern; suggestions require acceptance and never silently change
the schedule. Unknown contact state produces “Have you called Mom recently?” rather
than claiming no contact happened. Historical archive reading remains disabled.
Selected-conversation learning is included, scoped by user and source, and must
distinguish communication channels from confirmed calls or visits. Sources are
explicit chat GUIDs selected through authenticated local setup; no wildcard or
global opt-in. Import complete available text history in resumable pages into
private tables, without attachments or portal publication. Show import coverage.
Run initial pattern analysis locally without transmitting private history to an
LLM. Distinct days on which the owner sends a human message count as messaging
contact evidence; incoming-only messages, reactions, and Rally output do not.
At least four distinct contact days produce a median-gap cadence suggestion,
bounded to 1–90 days. The suggestion includes its sample size and source and
requires explicit acceptance. Message-derived cadence applies to messaging only.
Disabling a source stops imports and observation immediately; removing it deletes
its imported text and derived evidence. Existing manual contact events remain.

## Architecture and verification

Separate relationship persistence, request parsing, scheduler, and delivery adapter
from group plan extraction. Reuse SQLite connections and the transport, with a
dedicated relationship outbox. The existing group outbox feeds public portal
activity, so personal reminders and acknowledgments must never enter that table.
Route relationship commands before group storage, extraction, and archive ingestion.
When a configured personal destination overlaps a group, suppress archiving of
recognized personal commands and responses. Scope every record and command to a
configured owner identity; group membership alone does not confer access.

Persist a unique cycle key for each reminder. Claim pending delivery atomically
before calling BlueBubbles; mark a timeout or crash during delivery uncertain and
do not automatically resend it. Explicit send rejection may be retried with a
bounded delay. Startup must recover abandoned claims as uncertain. Calendar-day
cadences use the configured IANA time zone, including daylight saving transitions.
If the scheduler misses the reminder window, deliver in the next eligible window.

Test ownership
isolation, restart recovery, duplicate messages and ticks, overdue boundaries,
time zones, snooze/pause/resume, cancellation, cadence suggestions, incomplete
evidence, and failed or uncertain sends. Verify a live reminder only in the
user-selected destination; do not contact Mom or another relationship directly.

## Approved choices and setup

The user approved private Rally reminders and support for selected conversations.
Global archive reading remains disabled. Enable personal delivery only after local
setup supplies the owner's sender identity and an existing private conversation
GUID. This uses the current iMessage account; a dedicated Rally account remains
deferred. When that account is both owner and transport, recognize owner commands
sent from the account while ignoring Rally-prefixed output to prevent loops.
Validate that the reminder destination is a direct conversation rather than a
group. Do not invent a destination or enable any learning sources during setup.
