"""Plan-scoped, self-reported group availability and slot selection."""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class AvailabilityError(ValueError):
    pass


@dataclass(frozen=True)
class AvailabilityWindow:
    start: time
    end: time
    source_text: str


_DAYS = {name.lower(): i for i, name in enumerate(
    ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"))}
_DAY_RE = r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"


def _parse_time(value: str) -> time | None:
    value = value.strip().lower().replace(" ", "")
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm)?", value)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    suffix = match.group(3)
    if not suffix and match.group(2) is None:
        return None
    if minute > 59 or hour > (12 if suffix else 23) or hour < 1 and suffix:
        return None
    if suffix:
        hour = hour % 12 + (12 if suffix == "pm" else 0)
    if hour > 23:
        return None
    return time(hour, minute)


def parse_availability(text: str, on_date: date) -> AvailabilityWindow | None:
    """Parse a deliberately small, safe grammar for the plan's concrete date.

    Supports all-day named days and one daily window such as "weekdays after 4pm".
    Unsupported or ambiguous statements return None and must be clarified.
    """
    if not isinstance(text, str) or len(text) > 1000:
        return None
    lowered = text.lower().strip()
    weekday = on_date.weekday()
    day_match = re.search(_DAY_RE, lowered)
    weekday_group = re.search(r"\bweekdays\b", lowered)
    if day_match and _DAYS[day_match.group(1)] != weekday:
        return None
    if weekday_group and weekday > 4:
        return None
    if not day_match and not weekday_group:
        return None

    if re.search(r"\b(all day|anytime|free all day)\b", lowered):
        return AvailabilityWindow(time(0), time(23, 59), text[:1000])
    if re.search(r"\b(morning|afternoon|evening|night)\b", lowered):
        return None

    match = re.search(r"\b(after|before|from)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)"
                      r"(?:\s*(?:to|through|until|-)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?))?", lowered)
    if match:
        first = _parse_time(match.group(2))
        second = _parse_time(match.group(3)) if match.group(3) else None
        if first is None:
            return None
        if match.group(1) == "after":
            start, end = first, second or time(23, 59)
        elif match.group(1) == "before":
            start, end = time(0), first
        else:
            start, end = first, second or time(23, 59)
        if end <= start:
            return None
        return AvailabilityWindow(start, end, text[:1000])
    return None


def choose_slot(on_date: date, reports: list[AvailabilityWindow], busy: list[tuple[datetime, datetime]],
                time_zone: str, *, duration_minutes: int = 120,
                start_hour: int = 9, end_hour: int = 21,
                not_before: time | None = None) -> str | None:
    """Return the earliest 30-minute slot within every supplied report and owner free time."""
    if not reports or duration_minutes < 1 or start_hour < 0 or end_hour > 24 or end_hour <= start_hour:
        return None
    try:
        zone = ZoneInfo(time_zone)
    except ZoneInfoNotFoundError as exc:
        raise AvailabilityError("Invalid availability time zone") from exc
    earliest = max(time(start_hour), not_before or time(start_hour))
    cursor = datetime.combine(on_date, earliest, zone)
    minutes = cursor.minute % 30
    if minutes:
        cursor += timedelta(minutes=30 - minutes)
    limit = datetime.combine(on_date, time.min, zone) + timedelta(hours=end_hour)
    while cursor + timedelta(minutes=duration_minutes) <= limit:
        finish = cursor + timedelta(minutes=duration_minutes)
        if all(cursor.time() >= window.start and finish.time() <= window.end for window in reports):
            # Calendar free/busy timestamps are absolute; compare in UTC.
            start_utc, end_utc = cursor.astimezone(timezone.utc), finish.astimezone(timezone.utc)
            if not any(start_utc < busy_end and end_utc > busy_start for busy_start, busy_end in busy):
                return cursor.strftime("%H:%M")
        cursor += timedelta(minutes=30)
    return None


def looks_like_availability(text: str) -> bool:
    return bool(re.search(r"\b(free|available|availability|weekdays|weekends|after|before|all day)\b",
                          text, re.I))
