"""HTTP entry point for BlueBubbles, demo evaluation, and plan inspection."""

import asyncio
import hmac
import logging
from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from app.bluebubbles import normalize_webhook
from app.debug_view import render_debug_view
from app.history import BlueBubblesHistoryClient, HistoryImporter, normalize_archive_message
from app.models import ChatMessage
from app.portal_commands import portal_reply
from app.portal_data import build_portal_data
from app.portal_store import PortalStore
from app.portal_view import render_portal


logger = logging.getLogger(__name__)


def create_app(service=None, *, webhook_token: str | None = None,
               demo_mode: bool | None = None, schedule: bool = True,
               tick_seconds: int | None = None, portal_store: PortalStore | None = None,
               history_client: BlueBubblesHistoryClient | None = None,
               app_url: str | None = None, media_root: str | Path | None = None,
               history_enabled: bool = True) -> FastAPI:
    if service is None:
        from app.config import Settings, build_service
        settings = Settings.from_env()
        service = build_service(settings)
        webhook_token = settings.webhook_token
        demo_mode = settings.demo_mode
        tick_seconds = settings.tick_seconds
        app_url = app_url or settings.app_url
        history_enabled = settings.history_enabled
        if history_enabled and settings.bluebubbles_url and settings.bluebubbles_password:
            history_client = BlueBubblesHistoryClient(settings.bluebubbles_url,
                                                       settings.bluebubbles_password)
        publish_enabled = settings.portal_publish_approved
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
    if app_url:
        service.portal_handler = lambda message: portal_reply(message, portal_store, app_url)

    def import_one_page():
        if importer is None:
            return
        for chat_id in allowed_chats:
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
            else:
                try:
                    importer.import_page(chat_id)
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
            try:
                await asyncio.to_thread(service.tick)
            except Exception:
                logger.exception("Scheduled plan evaluation failed")
            await asyncio.to_thread(import_one_page)
            if publish_enabled and ticks % max(1, 300 // tick_seconds) == 0:
                try:
                    from scripts.publish_portal import publish
                    await asyncio.to_thread(publish, settings)
                except Exception:
                    logger.exception("Portal publication failed")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(periodic()) if schedule else None
        initial_import = asyncio.create_task(asyncio.to_thread(import_one_page)) if schedule else None
        try:
            yield
        finally:
            if initial_import:
                initial_import.cancel()
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app = FastAPI(title="Rally", lifespan=lifespan)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/webhooks/bluebubbles")
    def webhook(payload: dict, token: str | None = None):
        authorize(token)
        data = payload.get("data")
        if history_enabled and payload.get("type") == "new-message" and isinstance(data, dict):
            for chat in data.get("chats") or []:
                chat_id = chat.get("guid") if isinstance(chat, dict) else None
                if chat_id and chat_id in allowed_chats:
                    archived = normalize_archive_message(data, chat_id)
                    if archived:
                        portal_store.ensure_group(chat_id)
                        portal_store.upsert_messages(chat_id, [archived])
        incoming = normalize_webhook(payload)
        if incoming is None:
            return {"accepted": False}
        message = ChatMessage(**incoming.__dict__)
        try:
            return {"accepted": service.receive(message)}
        except Exception:
            raise HTTPException(503, "Rally could not process this message") from None

    @app.post("/demo/evaluate")
    def evaluate(chat_id: str, token: str | None = None):
        authorize(token)
        if not demo_mode:
            raise HTTPException(404, "Demo trigger disabled")
        return {"intervened": service.evaluate(chat_id)}

    @app.get("/debug", response_class=HTMLResponse)
    def debug(chat_id: str, token: str | None = None):
        authorize(token)
        plan = service.store.get_plan(chat_id)
        if plan is None:
            raise HTTPException(404, "No plan in this chat")
        proposal = service.store.latest_proposal(plan.id)
        reservation = service.store.reservation(proposal.id) if proposal else None
        return HTMLResponse(render_debug_view(plan, proposal, reservation))

    @app.post("/portal/admin/{chat_id}/import")
    def import_history(chat_id: str, token: str | None = None):
        authorize(token)
        if chat_id not in allowed_chats or importer is None:
            raise HTTPException(404, "History import unavailable")
        return {"imported": importer.import_page(chat_id),
                "state": portal_store.import_state(chat_id)}

    @app.post("/portal/admin/{chat_id}/settings")
    def update_portal_settings(chat_id: str, updates: dict, token: str | None = None):
        authorize(token)
        if chat_id not in allowed_chats:
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
        if group is None or group["chat_id"] not in allowed_chats or not group["sections"].get("history", True) or not group["sections"].get("media", True):
            raise HTTPException(404, "Media not found")
        item = portal_store.get_attachment(group["chat_id"], attachment_id)
        if not item or item["status"] != "available" or not item["local_path"]:
            raise HTTPException(404, "Media not available")
        path = Path(item["local_path"]).resolve()
        if not path.is_relative_to(media_root.resolve()) or not path.is_file():
            raise HTTPException(404, "Media not available")
        return FileResponse(path, media_type=item["mime_type"] or "application/octet-stream",
                            filename=item["filename"] or "attachment")

    @app.get("/{group_id}", response_class=HTMLResponse)
    def portal(group_id: str, before: str | None = None,
               old_plan_query: str | None = None):
        group = portal_store.get_group(group_id)
        if group is None or group["chat_id"] not in allowed_chats:
            raise HTTPException(404, "Group not found")
        return HTMLResponse(render_portal(build_portal_data(
            service, portal_store, group, before=before, old_plan_query=old_plan_query)))

    return app
