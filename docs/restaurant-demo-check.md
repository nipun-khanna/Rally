# Restaurant demo check

Checked 2026-09-27. This is the group path for a real restaurant reservation
by phone. It is not the local demo reservation in `app/reservations.py`, and
it is not a browser checkout.

No live Vapi call was placed for this check. No assistant, phone number, or
call was created or updated at the provider.

## What has to be true before a call

Rally will ask, and will not dial, until every item below is in the saved
brief:

| Item | Accepted example | Not accepted |
| --- | --- | --- |
| Restaurant | Carbone | "the restaurant" with no public listing |
| Phone | One number on a fetched page that names the restaurant | A search snippet, a number typed in chat, or an image-URL digit run |
| Date | `October 2`, `tonight`, or `tomorrow`, saved as a full date | Friday, or two different days |
| Time | `7:30pm` or `19:30` | `at 8` |
| Timezone | `Eastern Time`, or a known city such as New York | `ET` with no city and no zone |
| Party | `for 4` | missing |
| Reservation name | `under Tarun` | the first person on a plan |
| Owner | `on behalf of Ada` | `RALLY_VOICE_OWNER` / `local-imessage-account` |
| Callback | `callback (404) 555-0199`, or `RALLY_CALLBACK_NUMBER` if that setting is already a phone | the restaurant's own number |
| Authorization | A later `yes` in the same chat, after the brief is complete | `yes` in another chat, or `yes, party of 6` |

The opening line sent to Vapi is `I am calling on behalf of [owner]...`.
The model is told not to volunteer that it is automated, and to answer
truthfully if the restaurant asks. Card numbers are never supplied.

## Dry-run

Unit coverage builds the create-call body with `assistantOverrides` and does
not contact `api.vapi.ai`:

- `tests/test_restaurant_workflow.py`
- `tests/test_vapi.py` (`prepare_call` and evidence parsing)
- `tests/test_vapi_workflow.py` (ordinary direct calls, including "ended" is not a booking)
- `tests/test_browser_agent.py` and `tests/test_browser_integration.py` (a reservation request does not submit a browser booking)

`ReservationCaller(dry_run=True)` saves an authorized snapshot and returns the
payload. `VapiDialer.prepare_call` returns the JSON and does not use the HTTP
client. A non-dry-run authorization calls `place_call` once; tests use an
in-memory fake, not the network.

## Evidence

Checked with `python -m pytest` on `tests/test_restaurant_workflow.py`,
`tests/test_vapi.py`, `tests/test_vapi_workflow.py`, `tests/test_voice_caller.py`,
`tests/test_browser_agent.py`, and `tests/test_browser_integration.py`:
114 passed. Those tests use fixtures and in-memory fakes. They build the
`assistantOverrides` body and do not POST to Vapi.

A read-only fetch of
`https://www.williamsburguide.com/restaurants/peter-luger-steak-house/` on
2026-09-27 contains the words Williamsburg and Brooklyn on the page itself.
With location Brooklyn, that page verifies one telephone, `+17183877400`, and
`America/New_York`. The same page does not verify for Miami. The requested
city was not pasted onto the page text. `https://peterluger.com/` still had
no parseable phone. No Browser Use run was created.

A dry-run body for `+17183877400`, party of 4 on 2026-09-28 at 19:30
America/New_York under Tarun on behalf of Ada, opens with "I am calling on
behalf of Ada." It was not posted. A booking is confirmed only from
restaurant-side speech, not from an assistant recap.

## Limitations

- Public search HTML changes. Rally uses result links only as pages to fetch.
  A snippet phone is ignored. Digits that appear only inside an `http` or
  `https` URL are ignored. If several locations are published, Rally asks
  which location.
- Browser Use, when configured, is asked for a page URL past the homepage.
  The number still has to be on the page Rally fetches. This check did not
  start a Browser Use run. `peterluger.com` did not include a parseable phone
  in the fetched HTML, so the verified number is the guide page's telephone,
  not a number read from the restaurant's own homepage.
- Restaurant overrides set the per-call model to the saved assistant file's
  `xai` / `grok-4.3` pair so the system prompt replaces the relationship
  check-in script. A saved assistant on a different model is overridden for
  that call only.
- Confirmation requires the transcript to repeat the saved terms and a real
  confirmation code. Structured model output alone does not confirm, and
  `set` is not a code. `ended` by itself stays unresolved.
- `RALLY_CALLBACK_NUMBER` is used only when it is already configured. There is
  no separate owner-name setting; the group has to say who the call is for.
- The Mac Phone / Grok loopback path is unchanged and is not a restaurant
  booking. The test CLI remains pinned to `+16785991244`; the app is not.
