from datetime import date, datetime, timezone
import unittest

from app.availability import AvailabilityWindow, choose_slot, parse_availability


class AvailabilityTests(unittest.TestCase):
    def test_parses_example_general_availability_for_matching_plan_date(self):
        saturday = date(2026, 10, 3)
        all_day = parse_availability("I'm free all day Saturday", saturday)
        after_four = parse_availability("only after 4pm on weekdays", date(2026, 10, 2))
        self.assertTrue(all_day and all_day.start.isoformat() == "00:00:00")
        self.assertTrue(after_four and after_four.start.isoformat() == "16:00:00")
        self.assertIsNone(parse_availability("I'm free all day Saturday", date(2026, 10, 2)))
        self.assertIsNone(parse_availability("maybe in the evening", saturday))


    def test_slot_intersects_reports_and_owner_busy_intervals(self):
        day = date(2026, 10, 3)
        reports = [
            AvailabilityWindow(datetime.strptime("16:00", "%H:%M").time(),
                               datetime.strptime("23:59", "%H:%M").time(), "after 4pm Saturday"),
            AvailabilityWindow(datetime.strptime("17:00", "%H:%M").time(),
                               datetime.strptime("22:00", "%H:%M").time(), "after 5pm Saturday"),
        ]
        busy = [(datetime(2026, 10, 3, 21, tzinfo=timezone.utc),
                 datetime(2026, 10, 3, 23, tzinfo=timezone.utc))]
        self.assertEqual(choose_slot(day, reports, busy, "UTC"), "17:00")
        self.assertIsNone(choose_slot(day, reports, [
            (datetime(2026, 10, 3, 16, tzinfo=timezone.utc),
             datetime(2026, 10, 3, 22, tzinfo=timezone.utc))], "UTC"))
