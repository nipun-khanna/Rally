"""Google Calendar event creation for an explicitly approved Rally proposal.

The caller owns durable approval and result persistence. A stable provider event ID
allows a retry after a lost response to reconcile rather than create a second event.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models import Proposal


class CalendarError(RuntimeError):
    """Calendar creation is unavailable, unapproved, or its outcome is uncertain."""


@dataclass(frozen=True)
class CalendarApproval:
    proposal_id: str
    message_id: str
    includes_calendar: bool


@dataclass(frozen=True)
class CalendarCredentials:
    client_id: str
    client_secret: str
    refresh_token: str
    calendar_id: str = "primary"


@dataclass(frozen=True)
class CalendarEvent:
    proposal_id: str
    event_id: str
    url: str | None


def _local_datetime(proposal: Proposal, time_zone: str) -> datetime:
    try:
        zone = ZoneInfo(time_zone)
        local = datetime.strptime(f"{proposal.date} {proposal.time}", "%Y-%m-%d %H:%M")
    except (ValueError, ZoneInfoNotFoundError, KeyError) as exc:
        raise CalendarError("Calendar date, time, or time zone is invalid") from exc
    early = local.replace(tzinfo=zone, fold=0)
    late = local.replace(tzinfo=zone, fold=1)
    if early.utcoffset() != late.utcoffset():
        raise CalendarError("Calendar time is ambiguous or missing due to daylight saving")
    if early.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != local:
        raise CalendarError("Calendar time does not exist in the selected time zone")
    return early


def _event_body(proposal: Proposal, approval: CalendarApproval,
                time_zone: str, confirmation_id: str, duration_minutes: int) -> dict:
    if duration_minutes < 1 or duration_minutes > 24 * 60:
        raise CalendarError("Calendar event duration is invalid")
    start = _local_datetime(proposal, time_zone)
    end = (start.astimezone(timezone.utc) + timedelta(minutes=duration_minutes)).astimezone(start.tzinfo)
    if end <= start:
        raise CalendarError("Calendar event end must follow its start")
    event_id = "r" + hashlib.sha256(proposal.id.encode()).hexdigest()
    terms = {
        "proposal_id": proposal.id,
        "venue_id": proposal.venue_id,
        "venue_name": proposal.venue_name,
        "venue_address": proposal.venue_address,
        "date": proposal.date,
        "time": proposal.time,
        "party_size": proposal.party_size,
        "time_zone": time_zone,
        "confirmation_id": confirmation_id,
        "duration_minutes": duration_minutes,
    }
    digest = hashlib.sha256(json.dumps(terms, sort_keys=True).encode()).hexdigest()
    return {
        "id": event_id,
        "summary": f"Dinner at {proposal.venue_name}",
        "location": proposal.venue_address,
        "description": (f"Rally plan for {proposal.party_size}. "
                        f"Demo reservation confirmation: {confirmation_id}."),
        "start": {"dateTime": start.isoformat(), "timeZone": time_zone},
        "end": {"dateTime": end.isoformat(), "timeZone": time_zone},
        "extendedProperties": {"private": {
            "rallyProposalId": proposal.id,
            "rallyApprovalMessageId": approval.message_id,
            "rallyTermsDigest": digest,
        }},
    }


def _read_json(request: Request, opener) -> dict:
    try:
        with opener(request, timeout=10) as response:
            payload = json.load(response)
    except (HTTPError, URLError, OSError, ValueError) as exc:
        raise CalendarError("Calendar API request failed") from exc
    if not isinstance(payload, dict):
        raise CalendarError("Calendar API returned an invalid response")
    return payload


def _access_token(credentials: CalendarCredentials, opener) -> str:
    form = urlencode({
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "refresh_token": credentials.refresh_token,
        "grant_type": "refresh_token",
    }).encode()
    request = Request("https://oauth2.googleapis.com/token", data=form,
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
    payload = _read_json(request, opener)
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise CalendarError("Google OAuth did not provide an access token")
    return token


def get_calendar_busy(
    credentials: CalendarCredentials,
    start: datetime,
    end: datetime,
    *,
    opener=urlopen,
) -> list[tuple[datetime, datetime]]:
    """Read busy intervals for the single configured owner calendar.

    The OAuth grant must include ``calendar.events.freebusy`` (or an equivalent
    broader read scope). A missing/error calendar is an error, never free time.
    """
    if not all((credentials.client_id, credentials.client_secret,
                credentials.refresh_token, credentials.calendar_id)):
        raise CalendarError("Google Calendar is not configured")
    if (not isinstance(start, datetime) or not isinstance(end, datetime) or
            start.tzinfo is None or end.tzinfo is None or end <= start):
        raise CalendarError("Calendar availability window is invalid")
    token = _access_token(credentials, opener)
    request = Request(
        "https://www.googleapis.com/calendar/v3/freeBusy",
        data=json.dumps({
            "timeMin": start.astimezone(timezone.utc).isoformat(),
            "timeMax": end.astimezone(timezone.utc).isoformat(),
            "timeZone": "UTC",
            "items": [{"id": credentials.calendar_id}],
        }).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    payload = _read_json(request, opener)
    calendars = payload.get("calendars")
    record = calendars.get(credentials.calendar_id) if isinstance(calendars, dict) else None
    if not isinstance(record, dict) or record.get("errors"):
        raise CalendarError("Owner calendar availability could not be confirmed")
    intervals = record.get("busy")
    if not isinstance(intervals, list):
        raise CalendarError("Google Calendar returned invalid availability")
    result = []
    try:
        for item in intervals:
            busy_start = datetime.fromisoformat(item["start"].replace("Z", "+00:00"))
            busy_end = datetime.fromisoformat(item["end"].replace("Z", "+00:00"))
            if busy_start.tzinfo is None or busy_end.tzinfo is None or busy_end <= busy_start:
                raise ValueError
            result.append((busy_start.astimezone(timezone.utc), busy_end.astimezone(timezone.utc)))
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise CalendarError("Google Calendar returned invalid availability") from exc
    return result


def _verified_event(response: dict, expected: dict, proposal_id: str) -> CalendarEvent:
    if response.get("status", "confirmed") != "confirmed":
        raise CalendarError("Existing calendar event is not confirmed")
    for key in ("id", "summary", "location"):
        if response.get(key) != expected[key]:
            raise CalendarError("Existing calendar event does not match approved proposal")
    for key in ("start", "end"):
        actual = response.get(key)
        if not isinstance(actual, dict) or any(actual.get(k) != v for k, v in expected[key].items()):
            raise CalendarError("Existing calendar event does not match approved proposal")
    properties = response.get("extendedProperties")
    private = properties.get("private") if isinstance(properties, dict) else None
    if not isinstance(private, dict) or any(
        private.get(k) != v for k, v in expected["extendedProperties"]["private"].items()
    ):
        raise CalendarError("Existing calendar event does not match approved proposal")
    link = response.get("htmlLink")
    return CalendarEvent(proposal_id, expected["id"], link if isinstance(link, str) else None)


def create_calendar_event(
    proposal: Proposal,
    approval: CalendarApproval | None,
    credentials: CalendarCredentials,
    time_zone: str,
    confirmation_id: str,
    *,
    duration_minutes: int = 120,
    opener=urlopen,
) -> CalendarEvent:
    """Create exactly one event for a reservation with calendar-scoped consent.

    No guests are added or emailed. On a lost insert response, the deterministic
    event ID is read back. If readback also fails, the result is uncertain and the
    caller must retain it for reconciliation rather than claiming success.
    """
    if (approval is None or not approval.includes_calendar or
            approval.proposal_id != proposal.id or not approval.message_id):
        raise CalendarError("Calendar creation requires explicit proposal-bound approval")
    if not all((credentials.client_id, credentials.client_secret,
                credentials.refresh_token, credentials.calendar_id)):
        raise CalendarError("Google Calendar is not configured")
    if not confirmation_id:
        raise CalendarError("Calendar creation requires a confirmed reservation")
    body = _event_body(proposal, approval, time_zone, confirmation_id, duration_minutes)
    token = _access_token(credentials, opener)
    endpoint = ("https://www.googleapis.com/calendar/v3/calendars/"
                + quote(credentials.calendar_id, safe="") + "/events")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    insert = Request(endpoint + "?sendUpdates=none", data=json.dumps(body).encode(),
                     headers=headers, method="POST")
    try:
        with opener(insert, timeout=10) as response:
            result = json.load(response)
    except HTTPError as exc:
        if exc.code != 409:
            raise CalendarError(f"Google Calendar returned HTTP {exc.code}") from exc
        result = None
    except (URLError, OSError) as exc:
        result = None
    except ValueError as exc:
        raise CalendarError("Google Calendar returned an invalid response") from exc
    if result is None:
        lookup = Request(endpoint + "/" + quote(body["id"], safe=""),
                         headers={"Authorization": f"Bearer {token}"}, method="GET")
        try:
            result = _read_json(lookup, opener)
        except CalendarError as exc:
            raise CalendarError("Calendar creation outcome is uncertain; inspect the event before retrying") from exc
    if not isinstance(result, dict):
        raise CalendarError("Google Calendar returned an invalid event")
    return _verified_event(result, body, proposal.id)
