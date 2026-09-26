"""Calendar-day reminders in the owner's local time zone."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def due_at(anchor: datetime, days: int, zone: str, hour: int) -> datetime:
    local = anchor.astimezone(ZoneInfo(zone))
    day = local.date() + timedelta(days=days)
    return datetime(day.year, day.month, day.day, hour, tzinfo=ZoneInfo(zone))


def eligible(now: datetime, due: datetime, zone: str, hour: int) -> bool:
    return now >= due and now.astimezone(ZoneInfo(zone)).hour >= hour
