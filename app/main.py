"""HTTP entry point for BlueBubbles, demo evaluation, and plan inspection."""

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from app.bluebubbles import normalize_webhook
from app.debug_view import render_debug_view
from app.models import ChatMessage


logger = logging.getLogger(__name__)


def create_app(service=None, *, webhook_token: str | None = None,
               demo_mode: bool | None = None, schedule: bool = True,
               tick_seconds: int | None = None) -> FastAPI:
    if service is None:
        from app.config import Settings, build_service
        settings = Settings.from_env()
        service = build_service(settings)
        webhook_token = settings.webhook_token
        demo_mode = settings.demo_mode
        tick_seconds = settings.tick_seconds
    tick_seconds = tick_seconds or 60

    def authorize(token: str | None):
        if not webhook_token or not token or not hmac.compare_digest(token, webhook_token):
            raise HTTPException(403, "Forbidden")

    async def periodic():
        while True:
            await asyncio.sleep(tick_seconds)
            try:
                await asyncio.to_thread(service.tick)
            except Exception:
                logger.exception("Scheduled plan evaluation failed")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(periodic()) if schedule else None
        try:
            yield
        finally:
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

    return app
