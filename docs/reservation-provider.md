# Real reservation provider assessment

Checked 2026-09-25 against provider documentation. Rally's MVP uses a clearly labeled local demo reservation. A real reservation must not be reported as confirmed until a provider returns a durable booking identifier for the exact approved terms.

## Current finding

No reviewed provider offers a verified, self-serve, free API path for Rally to create restaurant reservations. Do not connect a live booking endpoint, scrape a consumer site, or turn a booking link into a `confirmed` result under the current “non-LLM APIs must be free” requirement.

| Provider | Official capability | Access and cost gate | Fit now |
| --- | --- | --- | --- |
| OpenTable | Online Booking API supports availability search, slot locks, and reservation creation. Its Directory API can provide restaurant reservation links. | API access requires approved partner registration and a production agreement. OpenTable says costs may vary by API or tier. Its documentation distinguishes online Consumer API from Voice AI API and prohibits using either for the other's purpose. | A candidate after written approval, pricing confirmation, and use-case review; a link can only be offered as a user-completed handoff. |
| Yelp Reservations | Search, openings, holds, booking, status, and cancellation are documented. The booking request needs guest name, email, and phone. Credit-card-hold restaurants cannot be booked through this endpoint. | Reservations is a Partner API, disabled by default and limited to contracted partners. No self-serve free reservation entitlement is documented. | A candidate after partner access and cost terms are confirmed; guest contact and payment-policy work would also be needed. |
| Reserve with Google Actions Center | Dining reservation integration is documented. | This is for booking providers that have direct merchant contracts and real-time inventory to make their inventory bookable on Google. Partner eligibility and onboarding are required. It is not a public consumer booking API for Rally. | Not a Rally booking client integration. |

Sources: [OpenTable API documentation](https://docs.opentable.com/), [OpenTable partner FAQ](https://www.opentable.com/restaurant-solutions/api-partners/faqs/), [OpenTable partner application](https://www.opentable.com/restaurant-solutions/api-partners/become-a-partner/), [Yelp Reservations guide](https://docs.developer.yelp.com/docs/reservation), [Yelp Partner APIs](https://docs.developer.yelp.com/docs/yelp-partner-apis), [Yelp reservation endpoint](https://docs.developer.yelp.com/reference/v3_reservations), [Google Actions Center eligibility](https://developers.google.com/actions-center/verticals/reservations/e2e/overview).

## Integration contract once access is secured

1. Obtain a provider agreement that explicitly permits Rally's iMessage/agent-assisted use case, confirms a usable free tier or other user-approved cost policy, and grants booking API credentials.
2. Search actual bookable inventory for the proposed restaurant, local date/time, party size, and restrictions. A Geoapify place result alone does not prove bookability. Match the place to a provider restaurant ID explicitly; unresolved matches cannot be booked.
3. Present the group's exact venue, date, time, party size, payment/deposit and cancellation terms. Collect any required guest contact data separately and securely. Record an approval tied to those terms, provider ID, and inventory slot.
4. On approval, recheck slot validity and use a stable idempotency key based on Rally proposal ID. OpenTable's docs specify `X-Request-Id` for idempotent POST operations; provider-specific retry semantics still need verification in its approved environment.
5. Persist the outbound booking attempt *before* calling the provider. If the response is lost or times out, mark the outcome `unknown`, reconcile through the provider's status API or operator, and do not automatically send a second booking request.
6. Mark `confirmed` and message the group only after a successful provider response with a durable external booking ID. A rejection remains unresolved; a payment/deposit requirement returns to the user without attempting payment.

## Work gate

Keep `app/reservations.py` as the local demo implementation until partner access and free-use terms are evidenced. At that point, add a provider adapter and transport-level tests using the approved API contract, then test against the provider's approved test restaurants. A live test must use provider-designated test inventory and must never create a booking at a real restaurant without the group's exact-term approval.
