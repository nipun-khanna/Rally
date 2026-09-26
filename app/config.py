"""Environment configuration and concrete Rally service wiring."""

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from app.agent import GrokClient
from app.bluebubbles import send_message
from app.calendar import (CalendarApproval, CalendarCredentials, CalendarError,
                          create_calendar_event)
from app.muse import MuseExtractor
from app.orchestrator import RallyService
from app.places import PlacesError, Venue, geocode_location, search_places
from app.store import Store


@dataclass(frozen=True)
class Settings:
    database_path: Path
    webhook_token: str
    bluebubbles_url: str
    bluebubbles_password: str
    xai_api_key: str
    meta_model_api_key: str
    extraction_provider: str
    grok_model: str
    geoapify_api_key: str
    default_city: str
    time_zone: str
    stall_minutes: int
    tick_seconds: int
    max_place_requests: int
    demo_mode: bool
    demo_venues: bool
    calendar_enabled: bool
    google_client_id: str
    google_client_secret: str
    google_refresh_token: str
    google_calendar_id: str
    max_calendar_requests: int
    allowed_chat_ids: frozenset[str]
    app_url: str = ""
    portal_publish_approved: bool = False
    history_enabled: bool = True
    grok_extraction_timeout: float = 60

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        source = env if env is not None else os.environ
        stall_minutes = int(source.get("RALLY_STALL_MINUTES", "30"))
        tick_seconds = int(source.get("RALLY_TICK_SECONDS", "60"))
        max_requests = int(source.get("RALLY_MAX_PLACE_REQUESTS", "100"))
        max_calendar_requests = int(source.get("RALLY_MAX_CALENDAR_REQUESTS", "20"))
        calendar_enabled = source.get("RALLY_CALENDAR_ENABLED", "0") == "1"
        extraction_timeout = float(source.get("RALLY_GROK_EXTRACTION_TIMEOUT", "60"))
        if not 1 <= extraction_timeout <= 120:
            raise ValueError("Extraction timeout must be between 1 and 120 seconds")
        extraction_provider = source.get("RALLY_EXTRACTION_PROVIDER", "grok").lower()
        if stall_minutes < 1 or tick_seconds < 1 or not 1 <= max_requests <= 1000:
            raise ValueError("Invalid Rally interval or place request cap")
        if extraction_provider not in ("grok", "muse"):
            raise ValueError("Invalid extraction provider")
        if max_calendar_requests < 1 or max_calendar_requests > 1000:
            raise ValueError("Invalid calendar request cap")
        calendar_keys = (source.get("RALLY_GOOGLE_CLIENT_ID", ""),
                         source.get("RALLY_GOOGLE_CLIENT_SECRET", ""),
                         source.get("RALLY_GOOGLE_REFRESH_TOKEN", ""),
                         source.get("RALLY_GOOGLE_CALENDAR_ID", ""))
        if calendar_enabled and not all(calendar_keys):
            raise ValueError("Calendar is enabled without complete Google credentials")
        return cls(
            database_path=Path(source.get("RALLY_DATABASE_PATH", "data/rally.sqlite3")),
            webhook_token=source.get("RALLY_WEBHOOK_TOKEN", ""),
            bluebubbles_url=source.get("RALLY_BLUEBUBBLES_URL", ""),
            bluebubbles_password=source.get("RALLY_BLUEBUBBLES_PASSWORD", ""),
            xai_api_key=source.get("RALLY_XAI_API_KEY", ""),
            meta_model_api_key=source.get("RALLY_META_MODEL_API_KEY", ""),
            extraction_provider=extraction_provider,
            grok_model=source.get("RALLY_GROK_MODEL", "grok-4.7"),
            geoapify_api_key=source.get("RALLY_GEOAPIFY_API_KEY", ""),
            default_city=source.get("RALLY_DEFAULT_CITY", ""),
            time_zone=source.get("RALLY_TIME_ZONE", "America/New_York"),
            stall_minutes=stall_minutes,
            tick_seconds=tick_seconds,
            max_place_requests=max_requests,
            demo_mode=source.get("RALLY_DEMO_MODE", "0") == "1",
            demo_venues=source.get("RALLY_DEMO_VENUES", "0") == "1",
            calendar_enabled=calendar_enabled,
            google_client_id=calendar_keys[0],
            google_client_secret=calendar_keys[1],
            google_refresh_token=calendar_keys[2],
            google_calendar_id=calendar_keys[3],
            max_calendar_requests=max_calendar_requests,
            allowed_chat_ids=frozenset(chat.strip() for chat in
                source.get("RALLY_ALLOWED_CHAT_GUIDS", "").split(",") if chat.strip()),
            app_url=source.get("RALLY_APP_URL", ""),
            portal_publish_approved=source.get("RALLY_PORTAL_PUBLISH_APPROVED", "0") == "1",
            history_enabled=source.get("RALLY_HISTORY_ENABLED", "1") == "1",
            grok_extraction_timeout=extraction_timeout,
        )


def build_service(settings: Settings) -> RallyService:
    store = Store(settings.database_path)
    agent = GrokClient(settings.xai_api_key, settings.grok_model,
                       default_city=settings.default_city, time_zone=settings.time_zone,
                       extraction_timeout=settings.grok_extraction_timeout)
    extractor = (MuseExtractor(settings.meta_model_api_key,
                               default_city=settings.default_city, time_zone=settings.time_zone)
                 if settings.extraction_provider == "muse" else agent)

    def search(facts):
        if settings.demo_mode and settings.demo_venues:
            location = ((facts.location if facts else "") or "").lower().strip()
            parts = [part.strip() for part in location.split(",")]
            recognized = ("new york" in location or "nyc" in location or
                          (parts[-1] == "ny" and len(parts) > 1) or
                          (len(parts) == 1 and location in ("midtown", "manhattan")))
            if location and not recognized:
                raise PlacesError("Demo venue fixture is only available in Midtown, New York")
            return [Venue("demo-italian", "An Italian Table", "123 Main St, Midtown, New York",
                          40.75, -73.98, ("italian",), source="demo")]
        if not settings.geoapify_api_key:
            raise PlacesError("Geoapify API key is missing")
        if not facts or not facts.location:
            raise PlacesError("Plan location is missing")
        location = facts.location
        if "," not in location and settings.default_city:
            location = f"{location}, {settings.default_city}"
        if "," not in location:
            raise PlacesError("The city is unclear")
        day = datetime.now(timezone.utc).date().isoformat()
        if not store.consume_quota(day, settings.max_place_requests):
            raise PlacesError("Free place-search budget reached")
        latitude, longitude = geocode_location(settings.geoapify_api_key, location)
        if not store.consume_quota(day, settings.max_place_requests):
            raise PlacesError("Free place-search budget reached")
        return search_places(settings.geoapify_api_key, latitude, longitude)

    def send(chat_id: str, text: str):
        if not settings.bluebubbles_url or not settings.bluebubbles_password:
            raise RuntimeError("BlueBubbles is not configured")
        return send_message(settings.bluebubbles_url, settings.bluebubbles_password, chat_id, text)

    calendar_fn = None
    if settings.calendar_enabled:
        credentials = CalendarCredentials(settings.google_client_id,
                                          settings.google_client_secret,
                                          settings.google_refresh_token,
                                          settings.google_calendar_id)

        def calendar_fn(proposal, approval_message_id, confirmation_id):
            day = datetime.now(timezone.utc).date().isoformat()
            if not store.consume_calendar_quota(day, settings.max_calendar_requests):
                raise CalendarError("Calendar request budget reached")
            return create_calendar_event(
                proposal, CalendarApproval(proposal.id, approval_message_id, True),
                credentials, settings.time_zone, confirmation_id)

    return RallyService(store, agent, search, send, settings.stall_minutes,
                        extractor=extractor, calendar_fn=calendar_fn,
                        allowed_chat_ids=settings.allowed_chat_ids)
