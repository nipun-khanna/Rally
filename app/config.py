"""Environment configuration and concrete Rally service wiring."""

import os
from dataclasses import dataclass
from datetime import datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from typing import Mapping

from app.agent import GrokClient
from app.bluebubbles import is_private_direct_chat, send_message
from app.history import BlueBubblesHistoryClient, planning_message_from_archive
from app.group_memory import GroupMemoryStore
from app.group_turns import GroupTurnStore
from app.message_text import add_rally_signature
from app.reactions import helper_status, send_reaction, set_typing
from app.calendar import (CalendarApproval, CalendarCredentials, CalendarError,
                          create_calendar_event, get_calendar_busy)
from app.muse import MuseExtractor
from app.orchestrator import RallyService
from app.places import PlacesError, Venue, geocode_location, search_places
from app.store import Store
from app.web import GrokWebClient
from app.adaptive.agent import AdaptivePlanner
from app.adaptive.handler import AdaptiveHandler
from app.adaptive.store import AdaptiveStore
from app.adaptive.tools import build_default_registry
from app.adaptive.generator import CapabilityDraft, CapabilityProposalGenerator
from app.adaptive.proposals import CapabilityProposalStore
from app.envfile import resolve_settings_env


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
    grok_extraction_effort: str = "low"
    grok_reply_model: str = "grok-4.3"
    grok_reply_effort: str = "none"
    grok_reply_timeout: float = 25
    web_enabled: bool = False
    web_daily_limit: int = 0
    web_max_tool_calls: int = 3
    adaptive_enabled: bool = True
    adaptive_code_proposals: bool = True
    admin_token: str = ""
    voice_enabled: bool = False
    voice_owner: str = "local-imessage-account"
    voice_model: str = "grok-voice-latest"
    browser_enabled: bool = False
    browser_owner_chat_id: str = ""
    browser_owner_sender_id: str = ""
    browser_admin_token: str = ""
    browser_profile_path: Path = Path("data/browser/profile")
    browser_download_path: Path = Path("data/browser/downloads")
    browser_max_actions: int = 6
    browser_max_text_chars: int = 6000

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, *,
                 dotenv_path: Path | str | None = None) -> "Settings":
        source = resolve_settings_env(env, dotenv_path=dotenv_path)
        stall_minutes = int(source.get("RALLY_STALL_MINUTES", "30"))
        tick_seconds = int(source.get("RALLY_TICK_SECONDS", "60"))
        max_requests = int(source.get("RALLY_MAX_PLACE_REQUESTS", "100"))
        max_calendar_requests = int(source.get("RALLY_MAX_CALENDAR_REQUESTS", "20"))
        web_enabled = source.get("RALLY_WEB_ENABLED", "0") == "1"
        web_daily_limit = int(source.get("RALLY_WEB_DAILY_LIMIT", "0"))
        web_max_tool_calls = int(source.get("RALLY_WEB_MAX_TOOL_CALLS", "3"))
        if not 0 <= web_daily_limit <= 1000 or not 1 <= web_max_tool_calls <= 10:
            raise ValueError("Invalid web search budget")
        calendar_enabled = source.get("RALLY_CALENDAR_ENABLED", "0") == "1"
        extraction_timeout = float(source.get("RALLY_GROK_EXTRACTION_TIMEOUT", "60"))
        if not 1 <= extraction_timeout <= 120:
            raise ValueError("Extraction timeout must be between 1 and 120 seconds")
        extraction_effort = source.get("RALLY_GROK_EXTRACTION_EFFORT", "low").lower()
        if extraction_effort not in ("low", "medium", "high"):
            raise ValueError("Invalid Grok extraction reasoning effort")
        reply_model = source.get("RALLY_GROK_REPLY_MODEL", "grok-4.3").strip()
        reply_effort = source.get("RALLY_GROK_REPLY_REASONING_EFFORT", "none").lower()
        reply_timeout = float(source.get("RALLY_GROK_REPLY_TIMEOUT", "25"))
        if reply_model not in ("grok-4.3", "grok-4.5", "grok-4.6", "grok-4.7"):
            raise ValueError("Unsupported Grok reply model")
        supported_reply_efforts = ("none", "low", "medium", "high") if reply_model == "grok-4.3" else ("low", "medium", "high")
        if reply_effort not in supported_reply_efforts or not 1 <= reply_timeout <= 120:
            raise ValueError("Invalid Grok reply configuration")
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
        voice_enabled = source.get("RALLY_VOICE_ENABLED", "0") == "1"
        admin_token = source.get("RALLY_ADMIN_TOKEN", "")
        xai_api_key = source.get("RALLY_XAI_API_KEY", "")
        if voice_enabled and not (admin_token and xai_api_key):
            raise ValueError("Voice is enabled without an admin token and xAI API key")
        browser_enabled = source.get("RALLY_BROWSER_ENABLED", "0") == "1"
        browser_owner_chat_id = source.get("RALLY_BROWSER_OWNER_CHAT_ID", "").strip()
        browser_owner_sender_id = source.get("RALLY_BROWSER_OWNER_SENDER_ID", "").strip()
        browser_admin_token = source.get("RALLY_BROWSER_ADMIN_TOKEN", "")
        browser_profile_path = Path(source.get("RALLY_BROWSER_PROFILE_PATH", "data/browser/profile"))
        browser_download_path = Path(source.get("RALLY_BROWSER_DOWNLOAD_PATH", "data/browser/downloads"))
        browser_max_actions = int(source.get("RALLY_BROWSER_MAX_ACTIONS", "6"))
        browser_max_text_chars = int(source.get("RALLY_BROWSER_MAX_TEXT_CHARS", "6000"))
        if browser_enabled:
            if not is_private_direct_chat(browser_owner_chat_id):
                raise ValueError("Browser owner must be a private {service};-;{id} chat")
            if not browser_owner_sender_id:
                raise ValueError("Browser owner sender ID is required")
            browser_root = Path("data/browser").absolute()
            if browser_root.resolve() != browser_root:
                raise ValueError("Browser data directory must not be a symlink")
            for path in (browser_profile_path, browser_download_path):
                if not path.resolve().is_relative_to(browser_root) or path.resolve() == browser_root:
                    raise ValueError("Browser paths must stay under data/browser/")
            if not 1 <= browser_max_actions <= 12 or not 1000 <= browser_max_text_chars <= 12000:
                raise ValueError("Invalid browser action or observation limit")
            if browser_admin_token and (len(browser_admin_token) < 32 or browser_admin_token == admin_token):
                raise ValueError("Browser admin token must be separate and at least 32 characters")
        return cls(
            database_path=Path(source.get("RALLY_DATABASE_PATH", "data/rally.sqlite3")),
            webhook_token=source.get("RALLY_WEBHOOK_TOKEN", ""),
            bluebubbles_url=source.get("RALLY_BLUEBUBBLES_URL", ""),
            bluebubbles_password=source.get("RALLY_BLUEBUBBLES_PASSWORD", ""),
            xai_api_key=xai_api_key,
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
            grok_extraction_effort=extraction_effort,
            grok_reply_model=reply_model,
            grok_reply_effort=reply_effort,
            grok_reply_timeout=reply_timeout,
            web_enabled=web_enabled,
            web_daily_limit=web_daily_limit,
            web_max_tool_calls=web_max_tool_calls,
            adaptive_enabled=source.get("RALLY_ADAPTIVE_ENABLED", "1") == "1",
            adaptive_code_proposals=source.get("RALLY_ADAPTIVE_CODE_PROPOSALS", "1") == "1",
            admin_token=admin_token,
            voice_enabled=voice_enabled,
            voice_owner=source.get("RALLY_VOICE_OWNER", "local-imessage-account"),
            voice_model=source.get("RALLY_VOICE_MODEL", "grok-voice-latest"),
            browser_enabled=browser_enabled,
            browser_owner_chat_id=browser_owner_chat_id,
            browser_owner_sender_id=browser_owner_sender_id,
            browser_admin_token=browser_admin_token,
            browser_profile_path=browser_profile_path,
            browser_download_path=browser_download_path,
            browser_max_actions=browser_max_actions,
            browser_max_text_chars=browser_max_text_chars,
        )


def build_service(settings: Settings) -> RallyService:
    store = Store(settings.database_path)
    agent = GrokClient(settings.xai_api_key, settings.grok_model,
                       default_city=settings.default_city, time_zone=settings.time_zone,
                       extraction_timeout=settings.grok_extraction_timeout,
                       extraction_reasoning_effort=settings.grok_extraction_effort)
    reply_agent = GrokClient(settings.xai_api_key, settings.grok_reply_model,
                             default_city=settings.default_city, time_zone=settings.time_zone,
                             direct_reasoning_effort=settings.grok_reply_effort,
                             direct_timeout=settings.grok_reply_timeout)
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

    def send(chat_id: str, text: str, selected_message_guid: str | None = None):
        if not settings.bluebubbles_url or not settings.bluebubbles_password:
            raise RuntimeError("BlueBubbles is not configured")
        # selectedMessageGuid forces BlueBubbles onto Private API. Only thread
        # when the helper is already known connected so unthreaded text still
        # lands if SIP/helper is off.
        if selected_message_guid and helper_status(
                settings.bluebubbles_url, settings.bluebubbles_password, wait=False).status != "sent":
            selected_message_guid = None
        return send_message(settings.bluebubbles_url, settings.bluebubbles_password, chat_id,
                            add_rally_signature(text),
                            selected_message_guid=selected_message_guid)

    def warm_helper():
        if not settings.bluebubbles_url or not settings.bluebubbles_password:
            return None
        return helper_status(settings.bluebubbles_url, settings.bluebubbles_password, wait=True)

    calendar_fn = None
    availability_fn = None
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

        def availability_fn(day, time_zone):
            from zoneinfo import ZoneInfo
            local_day = datetime.fromisoformat(day).date()
            zone = ZoneInfo(time_zone)
            start = datetime.combine(local_day, clock_time.min, zone)
            end = datetime.combine(local_day + timedelta(days=1), clock_time.min, zone)
            quota_day = datetime.now(timezone.utc).date().isoformat()
            if not store.consume_calendar_quota(quota_day, settings.max_calendar_requests):
                raise CalendarError("Calendar request budget reached")
            return get_calendar_busy(credentials, start, end)

    web_answer_fn = None
    if settings.web_enabled:
        web = GrokWebClient(settings.xai_api_key, settings.grok_model,
                            max_tool_calls=settings.web_max_tool_calls)

        def web_answer_fn(request: str, *, tone: str = 'neutral') -> str:
            day = datetime.now(timezone.utc).date().isoformat()
            if not store.consume_web_quota(day, settings.web_daily_limit):
                return "Today's web search limit has been reached. Try again tomorrow."
            return web.answer(request, tone=tone)

    adaptive_handler = None
    if settings.adaptive_enabled and settings.xai_api_key and settings.allowed_chat_ids:
        proposal_generator = None
        if settings.adaptive_code_proposals:
            def draft_transport(payload):
                return agent._call(CapabilityDraft, payload['system'],
                                   {'request':payload['request'],
                                    'missing_capability':payload['missing_capability']})
            proposal_generator = CapabilityProposalGenerator(
                draft_transport, CapabilityProposalStore(settings.database_path.parent /
                                                         'capability_proposals'))
        from app.dashboard_live import generate_dashboard
        from app.portal_store import PortalStore
        portal_for_tools = PortalStore(settings.database_path)

        def generate_dashboard_fn(chat_id: str) -> dict:
            publisher = None
            if settings.portal_publish_approved:
                def publisher(target_chat):
                    from scripts.publish_portal import publish_live
                    return publish_live(settings, target_chat)
            return generate_dashboard(
                store, portal_for_tools, chat_id, app_url=settings.app_url,
                allowed_chat_ids=settings.allowed_chat_ids, publisher=publisher)

        adaptive_handler = AdaptiveHandler(
            AdaptiveStore(settings.database_path), AdaptivePlanner(agent._call),
            build_default_registry(settings.allowed_chat_ids, plan_store=store,
                                   web_answer_fn=web_answer_fn,
                                   generate_dashboard_fn=generate_dashboard_fn),
            proposal_generator)

    def react(chat_id: str, message_id: str, reaction: str):
        if not settings.bluebubbles_url or not settings.bluebubbles_password:
            return None
        try:
            return send_reaction(settings.bluebubbles_url, settings.bluebubbles_password,
                                 chat_id, message_id, reaction, wait_for_helper=False)
        except ValueError:
            return None

    def typing(chat_id: str, on: bool):
        if not settings.bluebubbles_url or not settings.bluebubbles_password:
            return None
        return set_typing(settings.bluebubbles_url, settings.bluebubbles_password, chat_id, on,
                          wait_for_helper=False)

    history_fn = None
    if settings.history_enabled and settings.bluebubbles_url and settings.bluebubbles_password:
        history_client = BlueBubblesHistoryClient(settings.bluebubbles_url,
                                                  settings.bluebubbles_password)

        def history_fn(chat_id: str, limit: int = 50):
            items = history_client.fetch_recent_messages(chat_id, limit=limit)
            messages = []
            for item in items:
                parsed = planning_message_from_archive(item, chat_id)
                if parsed is not None:
                    messages.append(parsed)
            return messages

    return RallyService(store, agent, search, send, settings.stall_minutes,
                        extractor=extractor, calendar_fn=calendar_fn,
                        reply_agent=reply_agent,
                        allowed_chat_ids=settings.allowed_chat_ids,
                        web_answer_fn=web_answer_fn, adaptive_handler=adaptive_handler,
                        availability_fn=availability_fn, time_zone=settings.time_zone,
                        group_memory=GroupMemoryStore(settings.database_path),
                        group_turns=GroupTurnStore(settings.database_path),
                        react_fn=react, typing_fn=typing, defer_heavy_work=True,
                        history_fn=history_fn, helper_warm_fn=warm_helper)
