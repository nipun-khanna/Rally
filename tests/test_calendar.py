import io
import json
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

from app.calendar import (
    CalendarApproval,
    CalendarCredentials,
    CalendarError,
    create_calendar_event,
)
from app.models import Proposal


class CalendarTests(unittest.TestCase):
    def setUp(self):
        self.proposal = Proposal(
            "proposal-123", "plan-1", 1, "place-1", "Pasta House", "12 Main St",
            "2026-10-02", "20:00", 4,
        )
        self.credentials = CalendarCredentials("client-id", "client-secret", "refresh-token", "primary")
        self.approval = CalendarApproval("proposal-123", "message-123", True)

    def test_calendar_scope_required_before_network(self):
        def fail(request, timeout):
            self.fail("Unexpected network request")

        for approval in (None,
                         CalendarApproval("proposal-123", "message-123", False),
                         CalendarApproval("wrong-proposal", "message-123", True),
                         CalendarApproval("proposal-123", "", True)):
            with self.subTest(approval=approval), self.assertRaises(CalendarError):
                create_calendar_event(self.proposal, approval, self.credentials,
                                      "America/New_York", "RLY-123", opener=fail)

    def test_refreshes_token_and_creates_event_without_attendees(self):
        calls = []

        def opener(request, timeout):
            calls.append((request, timeout))
            if len(calls) == 1:
                self.assertEqual(request.full_url, "https://oauth2.googleapis.com/token")
                form = parse_qs(request.data.decode())
                self.assertEqual(form["grant_type"], ["refresh_token"])
                self.assertEqual(form["refresh_token"], ["refresh-token"])
                return io.BytesIO(b'{"access_token":"access-token","token_type":"Bearer"}')
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(request.get_header("Authorization"), "Bearer access-token")
            self.assertEqual(urlparse(request.full_url).path,
                             "/calendar/v3/calendars/primary/events")
            self.assertEqual(parse_qs(urlparse(request.full_url).query), {"sendUpdates": ["none"]})
            body = json.loads(request.data)
            self.assertNotIn("attendees", body)
            self.assertEqual(body["summary"], "Dinner at Pasta House")
            self.assertEqual(body["location"], "12 Main St")
            self.assertEqual(body["start"]["dateTime"], "2026-10-02T20:00:00-04:00")
            self.assertEqual(body["end"]["dateTime"], "2026-10-02T22:00:00-04:00")
            self.assertEqual(body["start"]["timeZone"], "America/New_York")
            self.assertEqual(body["extendedProperties"]["private"]["rallyProposalId"],
                             "proposal-123")
            return io.BytesIO(json.dumps({**body, "htmlLink": "https://calendar.google.com/event?eid=abc"}).encode())

        result = create_calendar_event(self.proposal, self.approval, self.credentials,
                                       "America/New_York", "RLY-123", opener=opener)
        self.assertEqual(result.proposal_id, self.proposal.id)
        self.assertEqual(result.event_id, json.loads(calls[1][0].data)["id"])
        self.assertRegex(result.event_id, r"^[0-9a-v]{5,1024}$")
        self.assertEqual(result.url, "https://calendar.google.com/event?eid=abc")
        self.assertEqual(len(calls), 2)

    def test_conflict_reconciles_matching_event(self):
        requested = {}

        def opener(request, timeout):
            if request.full_url.endswith("/token"):
                return io.BytesIO(b'{"access_token":"token"}')
            if request.get_method() == "POST":
                requested.update(json.loads(request.data))
                raise HTTPError(request.full_url, 409, "Conflict", {}, None)
            self.assertEqual(request.get_method(), "GET")
            return io.BytesIO(json.dumps({**requested, "htmlLink": "https://calendar.google.com/event"}).encode())

        result = create_calendar_event(self.proposal, self.approval, self.credentials,
                                       "America/New_York", "RLY-123", opener=opener)
        self.assertEqual(result.event_id, requested["id"])

    def test_conflict_rejects_different_event(self):
        requested = {}

        def opener(request, timeout):
            if request.full_url.endswith("/token"):
                return io.BytesIO(b'{"access_token":"token"}')
            if request.get_method() == "POST":
                requested.update(json.loads(request.data))
                raise HTTPError(request.full_url, 409, "Conflict", {}, None)
            return io.BytesIO(json.dumps({**requested, "location": "Different place"}).encode())

        with self.assertRaisesRegex(CalendarError, "does not match"):
            create_calendar_event(self.proposal, self.approval, self.credentials,
                                  "America/New_York", "RLY-123", opener=opener)

    def test_conflict_rejects_canceled_event(self):
        requested = {}

        def opener(request, timeout):
            if request.full_url.endswith("/token"):
                return io.BytesIO(b'{"access_token":"token"}')
            if request.get_method() == "POST":
                requested.update(json.loads(request.data))
                raise HTTPError(request.full_url, 409, "Conflict", {}, None)
            return io.BytesIO(json.dumps({**requested, "status": "cancelled"}).encode())

        with self.assertRaisesRegex(CalendarError, "not confirmed"):
            create_calendar_event(self.proposal, self.approval, self.credentials,
                                  "America/New_York", "RLY-123", opener=opener)

    def test_ambiguous_insert_reconciles_before_reporting_failure(self):
        requested = {}

        def opener(request, timeout):
            if request.full_url.endswith("/token"):
                return io.BytesIO(b'{"access_token":"token"}')
            if request.get_method() == "POST":
                requested.update(json.loads(request.data))
                raise URLError("connection reset")
            return io.BytesIO(json.dumps(requested).encode())

        result = create_calendar_event(self.proposal, self.approval, self.credentials,
                                       "America/New_York", "RLY-123", opener=opener)
        self.assertEqual(result.event_id, requested["id"])

    def test_rejects_missing_credentials_or_invalid_local_time(self):
        def fail(request, timeout):
            self.fail("Unexpected network request")

        for credentials, tz in ((CalendarCredentials("", "", "", ""), "America/New_York"),
                                (self.credentials, "Invalid/Zone")):
            with self.subTest(credentials=credentials, tz=tz), self.assertRaises(CalendarError):
                create_calendar_event(self.proposal, self.approval, credentials, tz,
                                      "RLY-123", opener=fail)

    def test_rejects_daylight_saving_gap_and_overlap(self):
        def fail(request, timeout):
            self.fail("Unexpected network request")

        for date, local_time in (("2026-03-08", "02:30"), ("2026-11-01", "01:30")):
            proposal = Proposal("proposal-123", "plan-1", 1, "place-1", "Pasta House",
                                "12 Main St", date, local_time, 4)
            with self.subTest(date=date), self.assertRaisesRegex(CalendarError, "daylight saving"):
                create_calendar_event(proposal, self.approval, self.credentials,
                                      "America/New_York", "RLY-123", opener=fail)

    def test_quota_error_is_reported_without_claiming_created_event(self):
        def opener(request, timeout):
            if request.full_url.endswith("/token"):
                return io.BytesIO(b'{"access_token":"token"}')
            raise HTTPError(request.full_url, 429, "quota exceeded", {}, None)

        with self.assertRaisesRegex(CalendarError, "HTTP 429"):
            create_calendar_event(self.proposal, self.approval, self.credentials,
                                  "America/New_York", "RLY-123", opener=opener)

    def test_unreconciled_lost_response_is_uncertain(self):
        def opener(request, timeout):
            if request.full_url.endswith("/token"):
                return io.BytesIO(b'{"access_token":"token"}')
            if request.get_method() == "POST":
                raise URLError("reset")
            raise HTTPError(request.full_url, 404, "not found", {}, None)

        with self.assertRaisesRegex(CalendarError, "outcome is uncertain"):
            create_calendar_event(self.proposal, self.approval, self.credentials,
                                  "America/New_York", "RLY-123", opener=opener)


if __name__ == "__main__":
    unittest.main()
