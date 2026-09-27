"""Build or catch up the group knowledge base: python -m scripts.build_knowledge"""

from app.agent import GrokClient
from app.config import Settings
from app.knowledge import KnowledgeBuilder, KnowledgeStore
from app.portal_store import PortalStore


def main() -> None:
    settings = Settings.from_env()
    agent = GrokClient(settings.xai_api_key, settings.grok_model,
                       extraction_timeout=settings.grok_extraction_timeout,
                       extraction_reasoning_effort=settings.grok_extraction_effort)
    builder = KnowledgeBuilder(KnowledgeStore(settings.database_path),
                               PortalStore(settings.database_path), agent,
                               owner_name=settings.owner_display_name)
    for chat_id in sorted(settings.allowed_chat_ids):
        try:
            print(chat_id, "saved", builder.run(chat_id), "facts")
        except Exception as exc:
            print(chat_id, "stopped early:", exc, "(re-run to continue from the saved cursor)")


if __name__ == "__main__":
    main()
