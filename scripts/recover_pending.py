"""Inspect or explicitly recover pending group extraction without sending messages."""

import argparse
import json

from app.config import Settings, build_service
from app.store import Store


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('status', 'run'))
    parser.add_argument('--chat-id', help='Required when more than one group is allowlisted')
    parser.add_argument('--apply', action='store_true', help='Make one live model extraction call')
    parser.add_argument('--limit', type=int, default=75, help='Maximum messages in the complete recovery window')
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    if args.chat_id:
        if args.chat_id not in settings.allowed_chat_ids:
            parser.error('Chat is not allowlisted')
        chat_id = args.chat_id
    elif len(settings.allowed_chat_ids) == 1:
        chat_id = next(iter(settings.allowed_chat_ids))
    else:
        parser.error('Exactly one allowlisted group or --chat-id is required')
    store = Store(settings.database_path)
    before = store.pending_count(chat_id)
    if args.command == 'status':
        print(json.dumps({'pending': before, 'would_send_messages': False}))
        return 0
    if not args.apply:
        parser.error('run requires --apply; this sends current group context to the configured extractor')
    if settings.extraction_provider == 'grok' and not settings.xai_api_key:
        parser.error('Configured extractor lacks an xAI key')
    if settings.extraction_provider == 'muse' and not settings.meta_model_api_key:
        parser.error('Configured extractor lacks a key')
    service = build_service(settings)
    def no_send(chat, text):
        raise RuntimeError('Recovery must not send messages')
    service.send_fn = no_send
    recovered = service.recover_pending(chat_id, limit=args.limit)
    print(json.dumps({'pending_before': before, 'recovered': recovered,
                      'pending_after': store.pending_count(chat_id), 'sent_messages': 0}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
