"""Local personal setup. No messages sent and no learning enabled implicitly."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from app.relationships.store import RelationshipStore


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path(os.environ.get('RALLY_DATABASE_PATH', 'data/rally.sqlite3')))
    parser.add_argument('--owner', default='local-imessage-account', help='Current account identity, or exact incoming handle for an external owner')
    commands = parser.add_subparsers(dest='command', required=True)
    configure = commands.add_parser('configure', help='Choose a private direct conversation; its other recipient sees reminders')
    configure.add_argument('--destination', required=True)
    configure.add_argument('--zone', default='America/New_York')
    configure.add_argument('--hour', type=int, default=18)
    commands.add_parser('status')
    commands.add_parser('sources')
    person = commands.add_parser('add-relationship')
    person.add_argument('--name', required=True)
    person.add_argument('--mode', choices=('call', 'visit', 'message', 'other'), required=True)
    person.add_argument('--days', type=int, required=True)
    add = commands.add_parser('add-source')
    add.add_argument('--chat', required=True)
    add.add_argument('--relationship', required=True)
    for name in ('disable-source', 'enable-source', 'remove-source'):
        sub = commands.add_parser(name)
        sub.add_argument('--chat', required=True)
    args = parser.parse_args(argv)
    store = RelationshipStore(args.database, recover=False)
    try:
        if args.command == 'configure':
            store.configure(args.owner, args.destination, args.zone, args.hour)
            print('Private reminder destination configured. No message sent; no sources selected.')
        elif args.command == 'status':
            configs = [c for c in store.configs() if c['owner'] == args.owner]
            print(json.dumps({'configured': bool(configs), 'configuration': configs,
                              'relationships': len(store.list_relationships(args.owner)),
                              'sources': len(store.sources(args.owner)),
                              'uncertain_deliveries': sum(d['status'] == 'uncertain' for d in store.deliveries(args.owner))}, indent=2))
        elif args.command == 'sources':
            # Only selection and coverage metadata; never imported message content.
            print(json.dumps(store.sources(args.owner), indent=2))
        elif args.command == 'add-relationship':
            store.upsert(args.owner, args.name, args.mode, args.days, datetime.now(timezone.utc))
            print('Relationship configured.')
        elif args.command == 'add-source':
            store.add_source(args.owner, args.chat, args.relationship)
            print('Conversation selected for local learning. No messages sent.')
        else:
            store.set_source(args.owner, args.chat, args.command.split('-')[0])
            print('Source preference updated.')
        return 0
    except ValueError as exc:
        print(str(exc))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
