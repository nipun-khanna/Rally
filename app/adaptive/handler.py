"""Explicit adaptive requests in allowlisted iMessage groups."""

import json
import re


_PREFIX = re.compile(r'^\s*(?:hey\s+)?rally\b[\s,:!?-]*', re.I)
_INTENT = re.compile(r'^(?:can you\s+)?(?:do\b|build\b|automate\b|figure out\b|use tools\b|make me\b|create a workflow\b)', re.I)


def should_use_adaptive(text: str) -> bool:
    prefix = _PREFIX.match(text)
    return bool(prefix and _INTENT.match(text[prefix.end():]))


class AdaptiveHandler:
    def __init__(self, store, planner, registry, proposal_generator=None):
        self.store = store
        self.planner = planner
        self.registry = registry
        self.proposal_generator = proposal_generator

    def answer(self, message) -> str:
        request = self.store.create_request(message.chat_id, message.message_id, message.text)
        if request['status'] == 'pending':
            decision = self.planner.plan(message.text, message.chat_id, self.registry)
            if decision['status'] == 'blocked':
                request = self.store.record_missing(request['id'], request['revision'],
                                                    decision['missing_capability'])
                if self.proposal_generator:
                    try:
                        proposal = self.proposal_generator.generate(message.text,
                                                                     decision['missing_capability'])
                        request = self.store.link_proposal(request['id'], request['revision'],
                                                           proposal['id'])
                    except Exception:
                        # The missing capability remains recorded even when drafting fails.
                        pass
            else:
                request = self.store.set_plan(request['id'], request['revision'], decision['steps'])
        if request['status'] == 'pending_review':
            return (f"I can't do {request['missing_capability']} yet. "
                    "I drafted code for developer review; it has not been run.")
        if request['status'] == 'blocked':
            return (f"I can't do {request['missing_capability']} yet. "
                    "I recorded the missing capability for developer review.")
        if request['status'] == 'uncertain':
            return 'That request has an uncertain in-flight result. It needs review before retrying.'
        if request['status'] == 'failed':
            return 'That request failed. Send a new request to retry it.'
        if request['status'] == 'running':
            return 'That request is still running.'
        if request['status'] == 'complete':
            return 'That request is already complete.'
        results = []
        for index, step in enumerate(request['steps']):
            if step['status'] != 'pending':
                continue
            if step['effect'] == 'commitment':
                return 'That action needs approval of its exact details before I can run it.'
            self.store.claim_step(request['id'], index, request['revision'])
            try:
                result = self.registry.execute(step['tool'], step['args'], chat_id=message.chat_id,
                                               current_request=message.text)
            except Exception:
                self.store.complete_step(request['id'], index,
                                         'failed' if step['effect'] == 'read' else 'uncertain', {})
                raise
            self.store.complete_step(request['id'], index, 'complete', {'result':result})
            results.append(result)
        if not results:
            return 'That request is already planned.'
        return '\n'.join(json.dumps(result, ensure_ascii=False) if not isinstance(result,str) else result
                         for result in results)[:3000]
