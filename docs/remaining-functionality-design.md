# Remaining Rally functionality

## Agreed scope

Keep the current iMessage account. Preserve the PRD's planning loop, quiet default,
same-chat replies, explicit approval for commitments, and labeled mock reservations.
Prepare Geoapify and Google Calendar setup without claiming either provider is ready
before its connection is verified. Adaptive requests may generate new code for review.

## Provider setup flow

A local CLI offers `status`, `configure-geoapify`, `authorize-calendar`, and
`verify`. Status prints only whether required values are present. Secret inputs use
hidden terminal prompts and are saved atomically to the ignored owner-only `.env`.
Existing unrelated configuration is preserved. No credential is placed in a command
argument, log, public portal, or Git commit.

Geoapify setup links to its account console, accepts the key, and performs a small
geocoding and venue query on explicit verification. It reports provider failures
without password-bearing URLs. Calendar setup accepts a downloaded Google OAuth
client configuration and uses a local loopback callback, random state, PKCE, and
offline access to obtain a refresh token. The user completes Google consent.
Verification checks token refresh and a read-only event-list request; it does not
create a calendar event. Calendar remains disabled until verification succeeds.

Google project creation, Calendar API enablement, and consent-screen configuration
remain user account prerequisites when no authenticated CLI can perform them.

## Adaptive request architecture

An explicit Rally address creates a durable request belonging to the originating
chat. Grok produces a structured plan referencing a registry of existing tools.
The registry supplies argument schemas, effects, approval requirements, and handler
implementations. The executor rejects unknown tools and invalid arguments, stores
step outcomes, and binds commitment approval to the exact proposed arguments.
Duplicate inbound messages never repeat execution. Missing credentials or tools
become explicit blocked outcomes rather than fabricated successes.

Reusable workflows preserve a validated sequence of registered tool steps. Each
new use requires fresh parameters and fresh approval where applicable; saved
workflows never preserve authorization to make future commitments.

For missing capabilities, Rally records a capability request and generates a
bounded source proposal with explanation, dependencies, proposed tests, and tool
schema. Generated source is stored as data under an ignored review-artifact
directory. Static syntax and schema validation can run without importing or
executing generated code. Status is `pending_review`; no automatic installation,
dependency download, import, or registration occurs. A developer reviews and adds
an accepted capability through the normal tested commit workflow.

The portal exposes request outcomes and a code-review summary through its existing
Rally activity section; source artifacts are available only through authenticated
local administration, not the bearer-link portal.

## Venue coverage

Map supported activities to verified Geoapify categories: meals to restaurants,
coffee to cafes, museums to museums, and outdoor meetups to parks. Unsupported
activities ask for clarification. Search results never claim table availability,
tickets, opening hours, or reservation capability absent verified data.

## Verification

Tests cover secret redaction, atomic configuration writes, OAuth state and PKCE,
provider errors, category mapping, request persistence and restart recovery,
same-chat routing, schema rejection, approval invalidation, duplicate messages,
workflow reuse, and generated code remaining inert. Live checks use the authorized
test group and separately record venue lookup, approved mock reservation, and
calendar creation. Missing credentials remain explicitly incomplete.
