"""Bounded Google Calendar free/busy lookup and conservative slot search."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.calendar import CalendarCredentials, CalendarError, _access_token


class AvailabilityError(ValueError):
    """The requested availability window or slot search is invalid."""


@dataclass(frozen=True)
class BusyInterval:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class AvailabilityResult:
    window_start: datetime
    window_end: datetime
    busy_by_calendar: dict[str, tuple[BusyInterval, ...]]
    covered_calendar_ids: frozenset[str]
    unknown_calendar_ids: frozenset[str]
    checked_at: datetime


_MAX_CALENDARS = 50
_MAX_WINDOW = timedelta(days=366)
_FREEBUSY_URL = "https://www.googleapis.com/calendar/v3/freeBusy"


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _unknown_result(start, end, calendar_ids):
    return AvailabilityResult(start, end, {}, frozenset(), frozenset(calendar_ids),
                              datetime.now(timezone.utc))


def fetch_availability(
    credentials: CalendarCredentials,
    calendar_ids: list[str],
    start: datetime,
    end: datetime,
    *,
    opener=urlopen,
) -> AvailabilityResult:
    """Fetch free/busy for explicit calendars; failures remain unknown, never free.

    Limits each call to 50 unique calendars and a 366-day window. Per-calendar
    errors and omitted response entries are recorded as unknown independently.
    """
    if (not _aware(start) or not _aware(end) or end <= start or
            end.astimezone(timezone.utc) - start.astimezone(timezone.utc) > _MAX_WINDOW):
        raise AvailabilityError("Availability window must be aware, ordered, and at most 366 days")
    if (not isinstance(calendar_ids, list) or not calendar_ids or
            len(calendar_ids) > _MAX_CALENDARS or
            any(not isinstance(value, str) or not value.strip() or value == "*" or len(value) > 1024
                for value in calendar_ids) or
            len(set(calendar_ids)) != len(calendar_ids)):
        raise AvailabilityError("Provide 1–50 unique explicit calendar IDs")
    ids = tuple(calendar_ids)
    try:
        token = _access_token(credentials, opener)
    except (CalendarError, HTTPError, URLError, OSError, ValueError):
        return _unknown_result(start, end, ids)

    body = {
        "timeMin": start.isoformat(),
        "timeMax": end.isoformat(),
        "items": [{"id": calendar_id} for calendar_id in ids],
    }
    request = Request(_FREEBUSY_URL, data=json.dumps(body).encode(),
                      headers={"Authorization": f"Bearer {token}",
                               "Content-Type": "application/json"}, method="POST")
    try:
        with opener(request, timeout=10) as response:
            payload = json.load(response)
    except (HTTPError, URLError, OSError, ValueError, TypeError):
        return _unknown_result(start, end, ids)
    if not isinstance(payload, dict) or not isinstance(payload.get("calendars"), dict):
        return _unknown_result(start, end, ids)

    response_calendars = payload["calendars"]
    covered: set[str] = set()
    busy_by_calendar: dict[str, tuple[BusyInterval, ...]] = {}
    unknown: set[str] = set()
    for calendar_id in ids:
        item = response_calendars.get(calendar_id)
        if not isinstance(item, dict) or item.get("errors") or not isinstance(item.get("busy"), list):
            unknown.add(calendar_id)
            continue
        intervals: list[BusyInterval] = []
        valid = True
        for raw in item["busy"]:
            try:
                if not isinstance(raw, dict):
                    raise ValueError
                interval_start = datetime.fromisoformat(raw["start"].replace("Z", "+00:00"))
                interval_end = datetime.fromisoformat(raw["end"].replace("Z", "+00:00"))
                if not _aware(interval_start) or not _aware(interval_end) or interval_end <= interval_start:
                    raise ValueError
            except (KeyError, TypeError, ValueError, AttributeError):
                valid = False
                break
            intervals.append(BusyInterval(interval_start, interval_end))
        if not valid:
            unknown.add(calendar_id)
            continue
        covered.add(calendar_id)
        busy_by_calendar[calendar_id] = tuple(intervals)
    return AvailabilityResult(start, end, busy_by_calendar, frozenset(covered),
                              frozenset(unknown), datetime.now(timezone.utc))


def _valid_local(naive: datetime, zone: ZoneInfo) -> datetime | None:
    """Resolve a wall time only when it maps to exactly one real instant."""
    early = naive.replace(tzinfo=zone, fold=0)
    late = naive.replace(tzinfo=zone, fold=1)
    if early.utcoffset() != late.utcoffset():
        return None
    if early.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != naive:
        return None
    return early


def find_slots(
    result: AvailabilityResult,
    *,
    required_calendar_ids: list[str],
    duration_minutes: int,
    zone: str,
    start_hour: int = 9,
    end_hour: int = 21,
) -> list[dict]:
    """Find 30-minute-start slots, only when all required calendars are covered.

    Hours are local wall-clock hours; every slot must fit wholly inside one local
    day, the requested availability window, and the configured daily range.
    Returned datetimes are timezone-aware and slot duration is elapsed time.
    """
    if not _aware(result.window_start) or not _aware(result.window_end) or result.window_end <= result.window_start:
        raise AvailabilityError("Availability result has an invalid window")
    if (not required_calendar_ids or any(not isinstance(x, str) or not x for x in required_calendar_ids)
            or len(set(required_calendar_ids)) != len(required_calendar_ids)):
        raise AvailabilityError("Required calendar IDs must be explicit and unique")
    if not set(required_calendar_ids).issubset(result.covered_calendar_ids):
        raise AvailabilityError("Required calendar availability is incomplete")
    if not isinstance(duration_minutes, int) or not 1 <= duration_minutes <= 24 * 60:
        raise AvailabilityError("Slot duration must be between 1 and 1440 minutes")
    if not isinstance(start_hour, int) or not isinstance(end_hour, int) or not 0 <= start_hour < end_hour <= 24:
        raise AvailabilityError("Local search hours must satisfy 0 <= start < end <= 24")
    try:
        local_zone = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, TypeError) as exc:
        raise AvailabilityError("Unknown time zone") from exc

    window_start = result.window_start.astimezone(timezone.utc)
    window_end = result.window_end.astimezone(timezone.utc)
    busy: list[tuple[datetime, datetime]] = []
    for calendar_id in required_calendar_ids:
        busy.extend((item.start.astimezone(timezone.utc), item.end.astimezone(timezone.utc))
                    for item in result.busy_by_calendar.get(calendar_id, ()))
    duration = timedelta(minutes=duration_minutes)
    local_first = result.window_start.astimezone(local_zone).date()
    local_last = result.window_end.astimezone(local_zone).date()
    slots: list[dict] = []
    day = local_first
    while day <= local_last:
        daily_start = datetime.combine(day, datetime.min.time()).replace(hour=start_hour)
        daily_end = datetime.combine(day, datetime.min.time()) + timedelta(hours=end_hour)
        candidate = daily_start
        while candidate < daily_end:
            local_start = _valid_local(candidate, local_zone)
            # Add elapsed duration so crossing a DST boundary remains accurate.
            if local_start is not None:
                utc_start = local_start.astimezone(timezone.utc)
                utc_end = utc_start + duration
                local_end = utc_end.astimezone(local_zone)
                end_within_day = (local_end.date() == day and
                                  (local_end.hour, local_end.minute, local_end.second) <=
                                  (daily_end.hour, daily_end.minute, daily_end.second))
                if end_hour == 24 and local_end.date() == day + timedelta(days=1):
                    end_within_day = local_end.timetz().replace(tzinfo=None) == datetime.min.time()
                if (utc_start >= window_start and utc_end <= window_end and end_within_day and
                        not any(utc_start < busy_end and busy_start < utc_end for busy_start, busy_end in busy)):
                    slots.append({"start": local_start, "end": local_end})
            candidate += timedelta(minutes=30)
        day += timedelta(days=1)
    return slots
