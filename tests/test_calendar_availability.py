import io
import json
import unittest
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from app.calendar_availability import (
    AvailabilityError, fetch_availability, find_slots,
)
from app.calendar import CalendarCredentials


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.credentials = CalendarCredentials("client", "secret", "refresh")
        self.start = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
        self.end = datetime(2026, 10, 2, 18, tzinfo=timezone.utc)

    def opener_with(self, payload):
        calls = []

        def opener(request, timeout):
            calls.append(request)
            if len(calls) == 1:
                return io.BytesIO(b'{"access_token":"token"}')
            return io.BytesIO(json.dumps(payload).encode())
        return opener, calls

    def test_fetches_busy_intervals_and_reports_per_calendar_coverage(self):
        payload = {"calendars": {
            "primary": {"busy": [{"start": "2026-10-02T13:00:00Z", "end": "2026-10-02T14:00:00Z"}]},
            "shared": {"busy": []},
            "denied": {"errors": [{"domain": "global", "reason": "forbidden"}]},
        }}
        opener, calls = self.opener_with(payload)
        result = fetch_availability(self.credentials, ["primary", "shared", "denied", "missing"],
                                    self.start, self.end, opener=opener)
        self.assertEqual(result.covered_calendar_ids, frozenset({"primary", "shared"}))
        self.assertEqual(result.unknown_calendar_ids, frozenset({"denied", "missing"}))
        self.assertEqual(result.busy_by_calendar["primary"][0].start,
                         datetime(2026, 10, 2, 13, tzinfo=timezone.utc))
        self.assertEqual(len(calls), 2)
        self.assertEqual(urlparse(calls[1].full_url).path, "/calendar/v3/freeBusy")
        body = json.loads(calls[1].data)
        self.assertEqual(body["items"], [{"id": x} for x in ("primary", "shared", "denied", "missing")])

    def test_transport_or_token_failure_returns_unknown_coverage(self):
        def opener(request, timeout):
            raise URLError("offline")

        result = fetch_availability(self.credentials, ["primary", "shared"], self.start,
                                    self.end, opener=opener)
        self.assertEqual(result.covered_calendar_ids, frozenset())
        self.assertEqual(result.unknown_calendar_ids, frozenset({"primary", "shared"}))
        self.assertEqual(result.busy_by_calendar, {})

    def test_rejects_unbounded_or_naive_requests_before_network(self):
        def fail(request, timeout):
            self.fail("Unexpected network request")

        cases = (
            ([], self.start, self.end),
            (["primary"] * 51, self.start, self.end),
            (["primary"], datetime(2026, 10, 2), self.end),
            (["primary"], self.start, datetime(2028, 10, 2, tzinfo=timezone.utc)),
        )
        for ids, start, end in cases:
            with self.subTest(ids=ids, start=start), self.assertRaises(AvailabilityError):
                fetch_availability(self.credentials, ids, start, end, opener=fail)

    def test_slots_need_complete_required_coverage_and_obey_busy_boundaries(self):
        opener, _ = self.opener_with({"calendars": {
            "primary": {"busy": [{"start": "2026-10-02T17:00:00Z", "end": "2026-10-02T17:30:00Z"}]},
            "partner": {"busy": []},
        }})
        result = fetch_availability(self.credentials, ["primary", "partner"], self.start,
                                    self.end, opener=opener)
        slots = find_slots(result, required_calendar_ids=["primary", "partner"],
                           duration_minutes=30, zone="America/New_York", start_hour=9, end_hour=15)
        self.assertTrue(all(slot["start"].astimezone(timezone.utc) != datetime(2026, 10, 2, 17, tzinfo=timezone.utc)
                            for slot in slots))
        self.assertIn(datetime(2026, 10, 2, 13, 30, tzinfo=ZoneInfo("America/New_York")),
                      [slot["start"] for slot in slots])
        with self.assertRaises(AvailabilityError):
            find_slots(result, required_calendar_ids=["primary", "unknown"], duration_minutes=30,
                       zone="America/New_York")

    def test_slots_use_wall_clock_days_and_reject_invalid_dst_times(self):
        from app.calendar_availability import AvailabilityResult
        result = AvailabilityResult(self.start, self.end, {}, frozenset({"primary"}),
                                    frozenset(), datetime.now(timezone.utc))
        slots = find_slots(result, required_calendar_ids=["primary"], duration_minutes=60,
                           zone="America/New_York", start_hour=9, end_hour=11)
        self.assertEqual([s["start"].hour for s in slots], [9, 9, 10])
        spring = AvailabilityResult(datetime(2026, 3, 8, 5, tzinfo=timezone.utc),
                                    datetime(2026, 3, 8, 10, tzinfo=timezone.utc), {},
                                    frozenset({"primary"}), frozenset(), datetime.now(timezone.utc))
        spring_slots = find_slots(spring, required_calendar_ids=["primary"], duration_minutes=30,
                                  zone="America/New_York", start_hour=1, end_hour=4)
        self.assertFalse(any(s["start"].hour == 2 for s in spring_slots))


if __name__ == "__main__":
    unittest.main()
