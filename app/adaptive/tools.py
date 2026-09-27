"""Small, chat-scoped boundary for adaptive request tools.

Handlers and approval checks are injected by trusted application code. Model output
may select a registered name and supply arguments, but cannot add capabilities.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping


_ARG_TYPES = (str, int, float, bool)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    schema: Mapping[str, type]
    effect: str
    handler: Callable[[str, dict], object]

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.isidentifier():
            raise ValueError('Invalid tool name')
        if self.effect not in ('read', 'commitment') or not callable(self.handler):
            raise ValueError('Invalid tool effect or handler')
        if not isinstance(self.schema, Mapping) or any(
                not isinstance(key, str) or not key.isidentifier() or value not in _ARG_TYPES
                for key, value in self.schema.items()):
            raise ValueError('Invalid tool schema')
        object.__setattr__(self, 'schema', MappingProxyType(dict(self.schema)))


class ToolRegistry:
    def __init__(self, allowed_chat_ids):
        self._allowed_chat_ids = frozenset(allowed_chat_ids)
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if not isinstance(spec, ToolSpec) or spec.name in self._tools:
            raise ValueError('Invalid or duplicate tool')
        self._tools[spec.name] = spec

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def describe(self) -> tuple[dict, ...]:
        """Expose metadata only; the planner never receives handlers."""
        return tuple({'name': spec.name, 'effect': spec.effect,
                      'schema': {key: kind.__name__ for key, kind in spec.schema.items()}}
                     for spec in self._tools.values())

    def validate(self, name: str, args: dict, *, chat_id: str) -> ToolSpec:
        if not isinstance(chat_id, str) or chat_id not in self._allowed_chat_ids:
            raise PermissionError('Chat is not allowed to use adaptive tools')
        spec = self._tools.get(name)
        if spec is None:
            raise ValueError('Unknown adaptive tool')
        if not isinstance(args, dict) or set(args) != set(spec.schema):
            raise ValueError('Tool arguments do not match schema')
        for key, kind in spec.schema.items():
            value = args[key]
            if type(value) is not kind:
                raise ValueError('Tool argument has wrong type')
            if kind is str and (not value.strip() or len(value) > 2000):
                raise ValueError('Tool text argument is invalid')
        return spec

    def execute(self, name: str, args: dict, *, chat_id: str, approval=None,
                request_id: str | None = None, step_index: int | None = None,
                revision: int | None = None, current_request: str | None = None):
        spec = self.validate(name, args, chat_id=chat_id)
        if name == 'web_research':
            if args['tone'] not in ('neutral', 'casual', 'formal'):
                raise ValueError('Invalid tone')
            if (not isinstance(current_request, str) or not current_request.strip()
                    or args['request'] != current_request):
                raise PermissionError('Web research must use the current explicit request')
        if spec.effect == 'commitment':
            if (not callable(approval) or not isinstance(request_id, str) or not request_id
                    or type(step_index) is not int or step_index < 0
                    or type(revision) is not int or revision < 1):
                raise PermissionError('Current step approval is required')
            args_hash = hashlib.sha256(json.dumps(args, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            if approval(chat_id, request_id, step_index, revision, args_hash) is not True:
                raise PermissionError('Current step approval is required')
        return spec.handler(chat_id, dict(args))


def build_default_registry(allowed_chat_ids, *, plan_store, web_answer_fn=None,
                           generate_dashboard_fn=None) -> ToolRegistry:
    registry = ToolRegistry(allowed_chat_ids)

    def plan_status(chat_id: str, args: dict) -> dict:
        plan = plan_store.get_plan(chat_id)
        if plan is None:
            return {'status': 'none'}
        return {'status': plan.state, 'activity': plan.facts.activity,
                'goal': plan.facts.goal, 'date': plan.facts.date,
                'time': plan.facts.time, 'version': plan.version}

    registry.register(ToolSpec('get_plan_status', {}, 'read', plan_status))
    if web_answer_fn is not None:
        registry.register(ToolSpec('web_research', {'request': str, 'tone': str}, 'read',
                                   lambda chat_id, args: web_answer_fn(args['request'], tone=args['tone'])))
    if generate_dashboard_fn is not None:
        def publish_dashboard(chat_id: str, args: dict) -> dict:
            result = generate_dashboard_fn(chat_id)
            if not isinstance(result, dict) or 'public_id' not in result or 'url' not in result:
                raise ValueError('Dashboard generate did not return a public url')
            return {'public_id': result['public_id'], 'url': result['url']}
        registry.register(ToolSpec('generate_dashboard', {}, 'read', publish_dashboard))
        registry.register(ToolSpec('publish_archive', {}, 'read', publish_dashboard))
    return registry
