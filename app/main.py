"""HTTP entry point for BlueBubbles, demo evaluation, and plan inspection."""

import asyncio
import hmac
import ipaddress
import logging
from time import perf_counter
from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import Cookie, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from app.agent import GrokProviderError
from app.bluebubbles import normalize_webhook
from app.debug_view import render_debug_view
from app.history import BlueBubblesHistoryClient, HistoryImporter, normalize_archive_message
from app.models import ChatMessage
from app.latency import record_latency
from app.portal_commands import portal_reply
from app.portal_data import build_knowledge_data, build_portal_data
from app.portal_store import PortalStore
from app.portal_view import render_knowledge, render_portal
from app.voice.page import render_voice_page
from app.voice.session import VoiceSessionError, build_session_payload, mint_ephemeral_token


logger = logging.getLogger(__name__)


def _log_failure(phase: str, exc: Exception):
    if isinstance(exc, GrokProviderError):
        logger.warning("%s failed: stage=%s kind=%s status=%s",
                       phase, exc.stage, exc.kind, exc.status_code)
    else:
        logger.warning("%s failed: type=%s", phase, type(exc).__name__)


async def _run_scheduled_checks(relationship_service, service):
    checks = []
    if relationship_service:
        if relationship_service.learner:
            checks.append(("Scheduled relationship learning", relationship_service.learner.sync))
        checks.append(("Scheduled relationship reminders", relationship_service.tick))
    checks.append(("Scheduled group evaluation", service.tick))
    for phase, check in checks:
        try:
            await asyncio.to_thread(check)
        except Exception as exc:
            _log_failure(phase, exc)


def create_app(service=None, *, webhook_token: str | None = None,
               demo_mode: bool | None = None, schedule: bool = True,
               tick_seconds: int | None = None, portal_store: PortalStore | None = None,
               history_client: BlueBubblesHistoryClient | None = None,
               app_url: str | None = None, media_root: str | Path | None = None,
               history_enabled: bool = True, relationship_service=None,
               admin_token: str | None = None, voice_registry=None,
               voice_model: str | None = None, xai_api_key: str | None = None,
               voice_owner: str | None = None, browser_runtime=None,
               browser_inbound=None, browser_admin_token: str | None = None,
               browser_enabled: bool = False, owner_display_name: str = "") -> FastAPI:
    settings = None
    if service is None:
        from app.config import Settings, build_service
        settings = Settings.from_env()
        service = build_service(settings)
        webhook_token = settings.webhook_token
        admin_token = settings.admin_token
        demo_mode = settings.demo_mode
        tick_seconds = settings.tick_seconds
        app_url = app_url or settings.app_url
        history_enabled = settings.history_enabled
        owner_display_name = settings.owner_display_name
        if history_enabled and settings.bluebubbles_url and settings.bluebubbles_password:
            history_client = BlueBubblesHistoryClient(settings.bluebubbles_url,
                                                       settings.bluebubbles_password)
        publish_enabled = settings.portal_publish_approved
        if relationship_service is None:
            from app.relationships.store import RelationshipStore
            from app.relationships.learning import RelationshipLearner
            from app.relationships.service import RelationshipService
            private_store = RelationshipStore(service.store.path)
            private_client = (BlueBubblesHistoryClient(settings.bluebubbles_url, settings.bluebubbles_password)
                              if settings.bluebubbles_url and settings.bluebubbles_password else None)
            relationship_service = RelationshipService(private_store, service.send_fn,
                                                       RelationshipLearner(private_store, private_client))
        xai_api_key = settings.xai_api_key
        voice_model = settings.voice_model
        voice_owner = settings.voice_owner
        if settings.voice_enabled:
            from app.voice.store import VoiceActionStore
            from app.voice.tools import build_voice_tools
            voice_bluebubbles_client = (
                history_client if history_client is not None else
                BlueBubblesHistoryClient(settings.bluebubbles_url, settings.bluebubbles_password)
                if settings.bluebubbles_url and settings.bluebubbles_password else None)
            voice_registry = build_voice_tools(
                settings.voice_owner, relationship_store=relationship_service.store,
                plan_store=service.store, service=service,
                action_store=VoiceActionStore(service.store.path),
                bluebubbles_client=voice_bluebubbles_client)
        if settings.browser_enabled:
            from app.browser.agent import BrowserTaskService
            from app.browser.handler import BrowserInbound
            from app.browser.log import configure_browser_logging
            from app.browser.runtime import BrowserRuntime
            from app.browser.store import BrowserStore
            configure_browser_logging()
            browser_enabled = True
            browser_admin_token = settings.browser_admin_token
            hosted = None
            vendor = None
            if settings.browser_use_api_key:
                from app.browser.hosted import BrowserUseClient
                vendor = BrowserUseClient(settings.browser_use_api_key)
            if settings.browserbase_api_key:
                from app.browser.hosted import BrowserbaseClient
                hosted = BrowserbaseClient(
                    settings.browserbase_api_key, settings.browserbase_project_id)
            browser_runtime = BrowserRuntime(
                settings.browser_profile_path, settings.browser_download_path,
                None, settings.browser_max_text_chars, hosted=hosted, vendor=vendor)
            browser_inbound = BrowserInbound(
                settings.browser_owner_chat_id, settings.browser_owner_sender_id,
                BrowserTaskService(browser_runtime, BrowserStore(settings.database_path),
                                   service.agent._call, settings, vendor_agent=vendor),
                service.send_fn,
                allowed_chat_ids=settings.allowed_chat_ids,
                group_turns=service.group_turns)
    else:
        publish_enabled = False
    tick_seconds = tick_seconds or 60
    portal_store = portal_store or PortalStore(service.store.path)
    media_root = Path(media_root or service.store.path.parent / "portal_media")
    importer = HistoryImporter(history_client, portal_store, media_root) if history_client and history_enabled else None
    allowed_chats = service.allowed_chat_ids or frozenset()
    if not history_enabled:
        for chat_id in allowed_chats:
            portal_store.update_settings(chat_id, sections={"history": False, "media": False, "analytics": False})
    owner = voice_owner or 'local-imessage-account'

    def resolve_public_id(chat_id):
        from app.bluebubbles import is_private_direct_chat
        from app.dashboard_live import generate_dashboard
        if is_private_direct_chat(chat_id):
            hosted = portal_store.hosted_group_public_id()
            if hosted:
                return hosted
        publisher = None
        if publish_enabled and settings is not None:
            def publisher(target_chat):
                from scripts.publish_portal import publish_live
                try:
                    return publish_live(settings, target_chat)
                except Exception:
                    logger.exception("Live dashboard publish failed")
                    return "publish_failed"
        result = generate_dashboard(
            service.store, portal_store, chat_id, app_url=app_url,
            allowed_chat_ids=allowed_chats, excluded_chat_ids=personal_chat_ids(),
            publisher=publisher)
        return result["public_id"]

    def command_reply(message):
        from app.group_admin_commands import admin_dashboard_reply
        admin = admin_dashboard_reply(
            message, portal_store, app_url, resolve_public_id=resolve_public_id)
        if admin is not None:
            return admin
        if not app_url:
            return None
        return portal_reply(message, portal_store, app_url, history_enabled=history_enabled,
                            resolve_public_id=resolve_public_id)

    service.portal_handler = command_reply

    def personal_chat_ids():
        if not relationship_service:
            return set()
        return ({c['destination'] for c in relationship_service.store.configs()} |
                {s['chat_id'] for s in relationship_service.store.sources()})

    service.excluded_chat_ids = personal_chat_ids

    def import_one_page():
        if importer is None:
            return
        for chat_id in allowed_chats:
            if chat_id in personal_chat_ids():
                continue
            portal_store.ensure_group(chat_id)
            state = portal_store.import_state(chat_id)
            if state["status"] == "complete" and state["updated_at"]:
                age = datetime.now(timezone.utc) - datetime.fromisoformat(state["updated_at"])
                if age.total_seconds() >= 3600:
                    portal_store.set_import_state(chat_id, cursor="0", status="pending")
                    state = portal_store.import_state(chat_id)
            if state["status"] == "complete":
                try:
                    importer.hydrate_pending_media(chat_id)
                except Exception:
                    logger.exception("Group media sync failed")
                knowledge_fn = getattr(service, "knowledge_fn", None)
                if knowledge_fn:
                    knowledge_fn(chat_id)
            else:
                try:
                    # Backfill in bulk (up to ~2000 messages/tick) so a newly allowlisted
                    # chat's page goes live in one or two ticks instead of trickling in
                    # 100 messages per minute.
                    importer.import_all(chat_id, limit=100, max_pages=20)
                except Exception:
                    logger.exception("Group history import failed")

    def authorize(token: str | None):
        if not webhook_token or not token or not hmac.compare_digest(token, webhook_token):
            raise HTTPException(403, "Forbidden")

    async def periodic():
        ticks = 0
        while True:
            await asyncio.sleep(tick_seconds)
            ticks += 1
            await _run_scheduled_checks(relationship_service, service)
            await asyncio.to_thread(import_one_page)
            if publish_enabled and ticks % max(1, 60 // tick_seconds) == 0:
                try:
                    from scripts.publish_portal import publish
                    await asyncio.to_thread(publish, settings)
                except Exception:
                    logger.exception("Portal publication failed")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(periodic()) if schedule else None
        initial_import = asyncio.create_task(asyncio.to_thread(import_one_page)) if schedule else None
        proxy = None
        from app.browser.runtime import BrowserRuntime
        if (browser_enabled and isinstance(browser_runtime, BrowserRuntime)
                and browser_runtime.hosted is None):
            from app.browser.egress import PublicEgressProxy
            proxy = PublicEgressProxy()
            browser_runtime.proxy_url = await proxy.start()
        try:
            yield
        finally:
            if browser_runtime is not None:
                try:
                    browser_runtime.stop()
                except Exception:
                    pass
            if proxy is not None:
                await proxy.close()
            if initial_import:
                initial_import.cancel()
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(title="Rally", lifespan=lifespan)

    @app.middleware("http")
    async def webhook_timing(request, call_next):
        if request.url.path != "/webhooks/bluebubbles":
            return await call_next(request)
        started = perf_counter()
        try:
            return await call_next(request)
        finally:
            record_latency("webhook_total", perf_counter() - started)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    def authorize_browser_admin(request: Request, candidate: str | None):
        if not browser_enabled or browser_runtime is None:
            raise HTTPException(404, "Browser is not enabled")
        host = request.client.host if request.client else ""
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise HTTPException(403, "Forbidden")
        except ValueError:
            raise HTTPException(403, "Forbidden")
        if (not browser_admin_token or not candidate or
                not hmac.compare_digest(candidate, browser_admin_token)):
            raise HTTPException(403, "Forbidden")

    @app.get("/browser/status")
    def browser_status(request: Request, x_rally_admin_token: str | None = Header(default=None)):
        authorize_browser_admin(request, x_rally_admin_token)
        return browser_runtime.status()

    @app.post("/browser/start")
    def browser_start(request: Request, x_rally_admin_token: str | None = Header(default=None)):
        authorize_browser_admin(request, x_rally_admin_token)
        try:
            return browser_runtime.start(headed=True)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from None

    @app.post("/browser/stop")
    def browser_stop(request: Request, x_rally_admin_token: str | None = Header(default=None)):
        authorize_browser_admin(request, x_rally_admin_token)
        return browser_runtime.stop()

    @app.post("/webhooks/bluebubbles")
    def webhook(payload: dict, token: str | None = None):
        authorize(token)
        if browser_inbound is not None:
            handled = browser_inbound.try_receive(payload)
            if handled is not None:
                return {"accepted": handled}
        if relationship_service:
            private_destinations = {c['destination'] for c in relationship_service.store.configs()}
            incoming_private = normalize_webhook(payload, allowed_direct_chat_ids=private_destinations)
            if incoming_private and incoming_private.chat_id in private_destinations:
                try:
                    return {'accepted': relationship_service.receive(ChatMessage(**incoming_private.__dict__))}
                except Exception:
                    raise HTTPException(503, 'Rally could not process this private request') from None
            if relationship_service.learner:
                relationship_service.learner.observe(payload)
            data = payload.get('data')
            if isinstance(data, dict) and any(isinstance(c, dict) and c.get('guid') in private_destinations
                                              for c in data.get('chats') or []):
                return {'accepted': False}
            if isinstance(data, dict) and any(isinstance(c, dict) and c.get('guid') in personal_chat_ids()
                                              for c in data.get('chats') or []):
                # Selected conversations are private learning sources, not LLM planning input.
                return {'accepted': payload.get('type') in ('new-message', 'updated-message', 'message-updated')}
        data = payload.get("data")
        if history_enabled and payload.get("type") == "new-message" and isinstance(data, dict):
            for chat in data.get("chats") or []:
                chat_id = chat.get("guid") if isinstance(chat, dict) else None
                if chat_id and chat_id in allowed_chats:
                    archived = normalize_archive_message(data, chat_id)
                    if archived:
                        portal_store.ensure_group(chat_id)
                        portal_store.upsert_messages(chat_id, [archived])
                        knowledge_fn = getattr(service, "knowledge_fn", None)
                        if knowledge_fn:
                            knowledge_fn(chat_id)
        incoming = normalize_webhook(payload, allowed_direct_chat_ids=allowed_chats)
        if incoming is None:
            return {"accepted": False}
        message = ChatMessage(**incoming.__dict__)
        try:
            return {"accepted": service.receive(message)}
        except Exception as exc:
            _log_failure("Group request", exc)
            raise HTTPException(503, "Rally could not process this message") from None

    @app.post("/demo/evaluate")
    def evaluate(chat_id: str, token: str | None = None):
        authorize(token)
        if not demo_mode:
            raise HTTPException(404, "Demo trigger disabled")
        if chat_id in personal_chat_ids():
            raise HTTPException(404, 'Personal conversation is excluded from group planning')
        return {"intervened": service.evaluate(chat_id)}

    @app.get("/debug", response_class=HTMLResponse)
    def debug(chat_id: str, token: str | None = None):
        authorize(token)
        plan = service.store.get_plan(chat_id)
        if plan is None:
            raise HTTPException(404, "No plan in this chat")
        proposal = service.store.latest_proposal(plan.id)
        reservation = service.store.reservation(proposal.id) if proposal else None
        return HTMLResponse(render_debug_view(plan, proposal, reservation,
                                             messages=service.store.recent_messages(chat_id)))

    def authorize_admin(candidate: str | None, cookie: str | None = None):
        if not admin_token:
            raise HTTPException(403, 'Admin token required')
        for value in (candidate, cookie):
            if value and hmac.compare_digest(value, admin_token):
                return
        raise HTTPException(403, 'Admin token required')

    def remember_admin(response: HTMLResponse, presented: str | None):
        if admin_token and presented and hmac.compare_digest(presented, admin_token):
            response.set_cookie('rally_admin', admin_token, httponly=True, samesite='strict',
                                path='/admin', max_age=12 * 60 * 60)
        return response

    def _dashboard_grouped():
        if relationship_service is None:
            raise HTTPException(404, 'Relationship dashboard is not enabled')
        from app.relationships.dashboard_view import build_dashboard_data
        owner = voice_owner or 'local-imessage-account'
        return build_dashboard_data(relationship_service.store, owner)

    @app.get('/dashboard', response_class=HTMLResponse)
    def dashboard(token: str | None = None):
        authorize_admin(token)
        from app.relationships.dashboard_view import render_dashboard
        return HTMLResponse(render_dashboard(_dashboard_grouped()))

    @app.get('/dashboard/fragment', response_class=HTMLResponse)
    def dashboard_fragment(token: str | None = None):
        authorize_admin(token)
        from app.relationships.dashboard_view import render_dashboard_body
        return HTMLResponse(render_dashboard_body(_dashboard_grouped()))

    @app.get('/voice', response_class=HTMLResponse)
    def voice_page(token: str | None = None):
        authorize_admin(token)
        if voice_registry is None:
            raise HTTPException(404, 'Voice is not enabled')
        return HTMLResponse(render_voice_page(admin_token or '', voice_model or 'grok-voice-latest'))

    @app.post('/voice/session')
    def voice_session(x_rally_admin_token: str | None = Header(default=None)):
        authorize_admin(x_rally_admin_token)
        if voice_registry is None:
            raise HTTPException(404, 'Voice is not enabled')
        try:
            ephemeral_token = mint_ephemeral_token(xai_api_key or '')
        except VoiceSessionError as exc:
            raise HTTPException(502, str(exc)) from None
        return {'ephemeral_token': ephemeral_token,
                'session': build_session_payload(tools=voice_registry.session_tools())}

    @app.post('/voice/tool')
    def voice_tool(payload: dict, x_rally_admin_token: str | None = Header(default=None)):
        authorize_admin(x_rally_admin_token)
        if voice_registry is None:
            raise HTTPException(404, 'Voice is not enabled')
        name, args = payload.get('name'), payload.get('args') or {}
        if not isinstance(name, str) or not isinstance(args, dict):
            raise HTTPException(400, 'Invalid tool call')
        try:
            return {'result': voice_registry.call(name, args)}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.get('/admin/groups', response_class=HTMLResponse)
    def admin_group_picker(token: str | None = None,
                           x_rally_admin_token: str | None = Header(default=None),
                           rally_admin: str | None = Cookie(default=None)):
        presented = token or x_rally_admin_token
        authorize_admin(presented, rally_admin)
        from app.group_admin import list_admin_groups
        from app.group_admin_view import render_group_picker
        page = render_group_picker(
            list_admin_groups(service, portal_store, excluded_chat_ids=personal_chat_ids()))
        return remember_admin(HTMLResponse(page), presented)

    @app.post('/admin/groups/{chat_id:path}/knowledge/refresh')
    def refresh_group_knowledge(chat_id: str,
                                x_rally_admin_token: str | None = Header(default=None),
                                rally_admin: str | None = Cookie(default=None)):
        authorize_admin(x_rally_admin_token, rally_admin)
        if chat_id not in allowed_chats or chat_id in personal_chat_ids():
            raise HTTPException(404, 'Group not found')
        if importer is None or getattr(service, 'knowledge_refresh_fn', None) is None:
            raise HTTPException(409, 'Knowledge refresh is unavailable')
        try:
            # The archive cursor fetches only messages received since its last
            # completed scan; the KB cursor then limits extraction to messages it
            # has not already processed.
            imported = importer.import_all(chat_id, limit=100, max_pages=20)
            facts_updated = service.refresh_knowledge(chat_id)
            if (imported or facts_updated) and service.portal_publish_fn:
                service.portal_publish_fn()
            from app.group_admin import build_group_admin
            from app.group_admin_view import render_group_admin
            data = build_group_admin(
                service, chat_id, portal_store=portal_store,
                excluded_chat_ids=personal_chat_ids(),
                identity={'webhook_token': webhook_token, 'admin_token': admin_token})
            if data is None:
                raise HTTPException(404, 'Group not found')
            data['knowledge']['notice'] = (
                'Knowledge is already up to date.' if not (imported or facts_updated) else
                f'Updated: {imported} new messages, {facts_updated} facts changed.')
            return remember_admin(HTMLResponse(render_group_admin(data)), x_rally_admin_token)
        except Exception as exc:
            _log_failure('Knowledge refresh', exc)
            raise HTTPException(503, 'Knowledge refresh could not finish') from None

    @app.get('/admin/groups/{chat_id:path}', response_class=HTMLResponse)
    def admin_group_detail(chat_id: str, token: str | None = None,
                           x_rally_admin_token: str | None = Header(default=None),
                           rally_admin: str | None = Cookie(default=None)):
        presented = token or x_rally_admin_token
        authorize_admin(presented, rally_admin)
        from app.group_admin import build_group_admin
        from app.group_admin_view import render_group_admin
        data = build_group_admin(
            service, chat_id, portal_store=portal_store,
            excluded_chat_ids=personal_chat_ids(),
            identity={'webhook_token': webhook_token, 'admin_token': admin_token})
        if data is None:
            raise HTTPException(404, 'Group not found')
        return remember_admin(HTMLResponse(render_group_admin(data)), presented)

    @app.get('/adaptive/admin/requests/{request_id}')
    def adaptive_request(request_id: str, include_source: bool = False,
                         x_rally_admin_token: str | None = Header(default=None)):
        authorize_admin(x_rally_admin_token)
        handler = getattr(service, 'adaptive_handler', None)
        if handler is None:
            raise HTTPException(404, 'Adaptive requests unavailable')
        try:
            request = handler.store.get_request(request_id)
        except ValueError:
            raise HTTPException(404, 'Request not found') from None
        if request['chat_id'] not in allowed_chats or request['chat_id'] in personal_chat_ids():
            raise HTTPException(404, 'Request not found')
        result = {'request': request}
        proposal_id = request['capability_proposal_id']
        generator = handler.proposal_generator
        if proposal_id and generator:
            result['proposal'] = generator.store.get(proposal_id)
            if include_source:
                result['source'] = generator.store.read_source(proposal_id)
        return result

    @app.post("/portal/admin/{chat_id}/import")
    def import_history(chat_id: str, token: str | None = None):
        authorize(token)
        if chat_id not in allowed_chats or chat_id in personal_chat_ids() or importer is None:
            raise HTTPException(404, "History import unavailable")
        return {"imported": importer.import_page(chat_id),
                "state": portal_store.import_state(chat_id)}

    @app.post("/portal/admin/{chat_id}/settings")
    def update_portal_settings(chat_id: str, updates: dict, token: str | None = None):
        authorize(token)
        if chat_id not in allowed_chats or chat_id in personal_chat_ids():
            raise HTTPException(404, "Group not found")
        try:
            return portal_store.update_settings(chat_id, title=updates.get("title"),
                                                theme=updates.get("theme"),
                                                sections=updates.get("sections"))
        except ValueError:
            raise HTTPException(400, "Invalid portal settings") from None

    @app.get("/{group_id}/media/{attachment_id}")
    def portal_media(group_id: str, attachment_id: str):
        group = portal_store.get_group(group_id)
        if group is None or group['chat_id'] in personal_chat_ids() or group["chat_id"] not in allowed_chats or not group["sections"].get("history", True) or not group["sections"].get("media", True):
            raise HTTPException(404, "Media not found")
        item = portal_store.get_attachment(group["chat_id"], attachment_id)
        if not item or item["status"] != "available" or not item["local_path"]:
            raise HTTPException(404, "Media not available")
        path = Path(item["local_path"]).resolve()
        if not path.is_relative_to(media_root.resolve()) or not path.is_file():
            raise HTTPException(404, "Media not available")
        return FileResponse(path, media_type=item["mime_type"] or "application/octet-stream",
                            filename=item["filename"] or "attachment")

    @app.get("/{group_id}/knowledge", response_class=HTMLResponse)
    def portal_knowledge(group_id: str):
        group = portal_store.get_group(group_id)
        if (group is None or group['chat_id'] in personal_chat_ids() or group["chat_id"] not in allowed_chats
                or not group["sections"].get("knowledge", True)):
            raise HTTPException(404, "Group not found")
        from app.knowledge import KnowledgeStore
        overview = build_portal_data(service, portal_store, group, owner_name=owner_display_name)
        return HTMLResponse(render_knowledge(build_knowledge_data(
            portal_store, KnowledgeStore(portal_store.path), group,
            owner_name=owner_display_name, overview=overview)))

    @app.get("/{group_id}", response_class=HTMLResponse)
    def portal(group_id: str, before: str | None = None,
               old_plan_query: str | None = None):
        group = portal_store.get_group(group_id)
        if group is None or group['chat_id'] in personal_chat_ids() or group["chat_id"] not in allowed_chats:
            raise HTTPException(404, "Group not found")
        return HTMLResponse(render_portal(build_portal_data(
            service, portal_store, group, before=before, old_plan_query=old_plan_query,
            owner_name=owner_display_name)))

    return app
