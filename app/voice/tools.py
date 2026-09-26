"""Tool boundary for the Grok Voice relationship check-in agent.

Handlers are injected by trusted application code in build_voice_tools() below.
The realtime model can select a registered name and supply arguments that match
its declared JSON Schema, but it cannot add a tool or change what a handler does.
Only confirm_action has a real side effect (sending an iMessage or running the
existing planning check), and it only ever acts on a draft created by an earlier
propose_message/nudge_plan call in the same session -- never on freeform text
the model invents in the moment.

Calendar-availability and follow-up-detection data are owned by separate
teammate work (see docs/team-ownership.md) and are not implemented here. Their
tools return an explicit placeholder rather than an invented answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable


_JSON_TYPES = {'string': str, 'integer': int, 'boolean': bool}


@dataclass(frozen=True)
class VoiceTool:
    name: str
    description: str
    parameters: dict  # JSON Schema object, sent verbatim in session.update
    effect: str  # 'read' or 'commitment'
    handler: Callable[[dict], object]

    def __post_init__(self):
        if self.effect not in ('read', 'commitment'):
            raise ValueError('Invalid tool effect')
        if not callable(self.handler):
            raise ValueError('Tool handler is required')

    def validate(self, args: dict) -> dict:
        if not isinstance(args, dict):
            raise ValueError('Tool arguments must be an object')
        props = self.parameters.get('properties', {})
        required = set(self.parameters.get('required', ()))
        if not required.issubset(args) or not set(args).issubset(props):
            raise ValueError('Tool arguments do not match schema')
        for key, value in args.items():
            expected = _JSON_TYPES[props[key]['type']]
            if expected is bool:
                if not isinstance(value, bool):
                    raise ValueError('Tool argument has wrong type')
            elif expected is int:
                if not isinstance(value, int) or isinstance(value, bool):
                    raise ValueError('Tool argument has wrong type')
            elif not isinstance(value, str) or isinstance(value, bool):
                raise ValueError('Tool argument has wrong type')
            if expected is str and len(value) > 2000:
                raise ValueError('Tool text argument is too long')
        return args


class VoiceToolRegistry:
    def __init__(self):
        self._tools: dict[str, VoiceTool] = {}

    def register(self, tool: VoiceTool) -> None:
        if tool.name in self._tools:
            raise ValueError('Duplicate voice tool name')
        self._tools[tool.name] = tool

    def session_tools(self) -> list[dict]:
        return [{'type': 'function', 'name': tool.name, 'description': tool.description,
                 'parameters': tool.parameters} for tool in self._tools.values()]

    def call(self, name: str, args: dict) -> object:
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f'Unknown voice tool: {name}')
        return tool.handler(tool.validate(args or {}))


def _linked_chat_id(relationship_store, owner: str, label: str) -> str | None:
    try:
        person = relationship_store.person(owner, label)
    except ValueError:
        return None
    for source in relationship_store.sources(owner):
        if source['person_id'] == person['id'] and source['enabled']:
            return source['chat_id']
    return None


def build_voice_tools(owner: str, *, relationship_store, plan_store, service,
                      action_store) -> VoiceToolRegistry:
    registry = VoiceToolRegistry()

    def list_attention(_args: dict) -> dict:
        now = datetime.now(timezone.utc)
        overdue = []
        for person in relationship_store.list_relationships(owner):
            if person['paused']:
                continue
            anchor = person.get('last_confirmed_at')
            days_since = (now - datetime.fromisoformat(anchor)).days if anchor else None
            if anchor is None or days_since > person['days']:
                overdue.append({'label': person['label'], 'mode': person['mode'],
                                'target_days': person['days'], 'days_since_contact': days_since})
        stalled = []
        for plan in plan_store.active_plans():
            if service.allowed_chat_ids is not None and plan.chat_id not in service.allowed_chat_ids:
                continue
            if plan.state in ('BLOCKED', 'ALIGNMENT', 'READY'):
                stalled.append({'chat_id': plan.chat_id, 'state': plan.state,
                                'goal': plan.facts.goal or plan.facts.activity,
                                'date': plan.facts.date, 'blockers': plan.facts.blockers})
        return {'overdue_relationships': overdue, 'stalled_plans': stalled,
                'unfinished_followups': [],
                'unfinished_followups_note': ('Follow-up detection is separate teammate work '
                    'and is not implemented; this is always empty until that lands.')}

    registry.register(VoiceTool(
        'list_attention',
        'List people overdue for contact based on their set intention, and group plans '
        'that have stalled waiting on a decision. Use this to answer "who am I falling '
        'behind with" or "what needs my attention".',
        {'type': 'object', 'properties': {}, 'required': []}, 'read', list_attention))

    def get_person(args: dict) -> dict:
        matches = [p for p in relationship_store.list_relationships(owner)
                  if p['label'].casefold() == args['label'].strip().casefold()]
        if not matches:
            return {'found': False}
        person = matches[0]
        events = relationship_store.contact_events(owner, person['label'])[-5:]
        return {'found': True, 'label': person['label'], 'mode': person['mode'],
                'target_days': person['days'], 'paused': bool(person['paused']),
                'last_confirmed_at': person.get('last_confirmed_at'),
                'recent_contact_events': [{'mode': e['mode'], 'at': e['at']} for e in events]}

    registry.register(VoiceTool(
        'get_person', 'Get the relationship intention and recent contact history for one '
        'named person.', {'type': 'object', 'properties': {'label': {'type': 'string'}},
                          'required': ['label']}, 'read', get_person))

    def set_intention(args: dict) -> dict:
        if args['mode'] not in ('call', 'visit', 'message', 'other'):
            return {'ok': False, 'reason': 'mode must be call, visit, message, or other'}
        try:
            relationship_store.upsert(owner, args['label'], args['mode'],
                                      int(args['days']), datetime.now(timezone.utc))
        except ValueError as exc:
            return {'ok': False, 'reason': str(exc)}
        return {'ok': True, 'label': args['label'], 'mode': args['mode'], 'days': args['days']}

    registry.register(VoiceTool(
        'set_intention', 'Create or update how often the user wants to stay in touch with '
        'someone, e.g. "call Grandma every week".',
        {'type': 'object', 'properties': {'label': {'type': 'string'}, 'mode': {'type': 'string'},
                                          'days': {'type': 'integer'}},
         'required': ['label', 'mode', 'days']}, 'read', set_intention))

    def check_plan_status(args: dict) -> dict:
        chat_id = _linked_chat_id(relationship_store, owner, args['label'])
        if chat_id is None:
            return {'linked': False, 'note': f"No linked conversation configured for "
                    f"{args['label']}."}
        plan = plan_store.get_plan(chat_id)
        if plan is None:
            return {'linked': True, 'chat_id': chat_id, 'status': 'none'}
        return {'linked': True, 'chat_id': chat_id, 'status': plan.state,
                'goal': plan.facts.goal or plan.facts.activity, 'date': plan.facts.date,
                'time': plan.facts.time, 'blockers': plan.facts.blockers}

    registry.register(VoiceTool(
        'check_plan_status', 'Check the status of a group plan linked to a named person, '
        'such as whether dinner with them was ever actually scheduled.',
        {'type': 'object', 'properties': {'label': {'type': 'string'}},
         'required': ['label']}, 'read', check_plan_status))

    def find_hangout_slot(_args: dict) -> dict:
        return {'available': False, 'note': ('Calendar availability is separate teammate '
                'work and is not connected yet. I cannot claim a free time slot without it.')}

    registry.register(VoiceTool(
        'find_hangout_slot', 'Look up when the user and a named person are both free. '
        'Currently always reports unavailable until calendar integration is connected.',
        {'type': 'object', 'properties': {'label': {'type': 'string'}},
         'required': ['label']}, 'read', find_hangout_slot))

    def propose_message(args: dict) -> dict:
        chat_id = _linked_chat_id(relationship_store, owner, args['label'])
        if chat_id is None:
            return {'ok': False, 'reason': f"No linked conversation configured for "
                    f"{args['label']}."}
        text = args['text'].strip()
        if not text or len(text) > 800:
            return {'ok': False, 'reason': 'Draft text must be 1-800 characters'}
        action = action_store.create(owner, 'send_message', chat_id=chat_id, label=args['label'],
                                     summary=f"Send to {args['label']}: {text}",
                                     payload={'text': text})
        return {'ok': True, 'pending_action_id': action['id'], 'summary': action['summary']}

    registry.register(VoiceTool(
        'propose_message', 'Draft an iMessage to a named person. This only prepares the '
        'message; it is not sent until confirm_action is called with the returned '
        'pending_action_id after the user explicitly says to send it.',
        {'type': 'object', 'properties': {'label': {'type': 'string'}, 'text': {'type': 'string'}},
         'required': ['label', 'text']}, 'read', propose_message))

    def nudge_plan(args: dict) -> dict:
        chat_id = _linked_chat_id(relationship_store, owner, args['label'])
        if chat_id is None:
            return {'ok': False, 'reason': f"No linked conversation configured for "
                    f"{args['label']}."}
        plan = plan_store.get_plan(chat_id)
        summary = f"Run Rally's planning check on the conversation linked to {args['label']}"
        action = action_store.create(owner, 'trigger_plan', chat_id=chat_id, label=args['label'],
                                     summary=summary, payload={})
        return {'ok': True, 'pending_action_id': action['id'], 'summary': summary,
                'current_status': plan.state if plan else 'none'}

    registry.register(VoiceTool(
        'nudge_plan', 'Prepare running Rally\'s existing stalled-plan check for the '
        'conversation linked to a named person, e.g. to move a mentioned-but-unplanned '
        'dinner forward. Requires confirm_action to actually run.',
        {'type': 'object', 'properties': {'label': {'type': 'string'}},
         'required': ['label']}, 'read', nudge_plan))

    def confirm_action(args: dict) -> dict:
        action = action_store.get(owner, args['action_id'])
        if action is None:
            return {'ok': False, 'reason': 'Unknown or expired action'}
        if action['status'] != 'pending':
            return {'ok': False, 'reason': f"Action already {action['status']}"}
        if action['kind'] == 'send_message':
            try:
                service.send_fn(action['chat_id'], action['payload']['text'])
            except Exception:
                action_store.resolve(owner, action['id'], 'failed')
                return {'ok': False, 'reason': 'Message delivery failed'}
            action_store.resolve(owner, action['id'], 'done')
            return {'ok': True, 'sent': True, 'chat_id': action['chat_id']}
        try:
            intervened = service.evaluate(action['chat_id'])
        except Exception:
            action_store.resolve(owner, action['id'], 'failed')
            return {'ok': False, 'reason': 'Planning check failed'}
        action_store.resolve(owner, action['id'], 'done')
        return {'ok': True, 'intervened': intervened, 'chat_id': action['chat_id']}

    registry.register(VoiceTool(
        'confirm_action', 'Execute a previously drafted action (send a proposed message, or '
        'run a prepared plan check) by its pending_action_id. Only call this after the user '
        'gives explicit affirmative confirmation for that specific draft.',
        {'type': 'object', 'properties': {'action_id': {'type': 'string'}},
         'required': ['action_id']}, 'commitment', confirm_action))

    return registry
