"""Owner-scoped local projection of relationship attention and stalled plans."""

from datetime import datetime

from app.relationships.schedule import due_at, eligible


def build_attention(store, owner: str, now: datetime, *, followups=None, plans=()) -> dict:
    """Build evidence-labeled cards from private records; this function never sends messages."""
    if now.tzinfo is None:
        raise ValueError('A time zone is required')
    profile = store.profile(owner)
    cards = []
    for person in store.list_relationships(owner):
        if person['paused']:
            continue
        snooze_until = person.get('snooze_until')
        if snooze_until and now < datetime.fromisoformat(snooze_until):
            continue
        anchor = person.get('last_confirmed_at')
        evidence = {'kind': 'none', 'summary': 'No confirmed interaction recorded'}
        state = 'unknown'
        due = None
        if anchor:
            anchor_dt = datetime.fromisoformat(anchor)
            events = store.contact_events(owner, person['label'])
            confirmed = next((event for event in events if event['at'] == anchor and
                              event['mode'] == person['mode']), None)
            if confirmed:
                evidence = {'kind': 'confirmed_contact', 'mode': confirmed['mode'],
                            'at': confirmed['at'], 'summary': f"You recorded a {confirmed['mode']}"}
            elif person['mode'] == 'message':
                evidence = {'kind': 'selected_message', 'mode': 'message', 'at': anchor,
                            'summary': 'Latest eligible message in a selected conversation'}
            else:
                # In particular, text history cannot prove a call or an in-person visit.
                anchor = None
                evidence = {'kind': 'none', 'summary': 'No confirmed interaction recorded'}
            if anchor:
                due_dt = due_at(anchor_dt, person['days'], profile['zone'], profile['hour'])
                due = due_dt.isoformat()
                state = 'overdue' if eligible(now, due_dt, profile['zone'], profile['hour']) else 'on_track'
        if state in ('unknown', 'overdue'):
            cards.append({
                'person_id': person['id'], 'label': person['label'], 'category': person.get('category', 'other'),
                'intention': person.get('intention', ''), 'mode': person['mode'], 'cadence_days': person['days'],
                'state': state, 'due_at': due, 'evidence': evidence,
            })
    cards.sort(key=lambda card: (card['state'] != 'overdue', card['label'].casefold()))
    result = {'owner': owner, 'generated_at': now.isoformat(), 'cards': cards,
              'plans': list(plans or ())}
    if followups is not None:
        result['followups'] = list(followups)
    return result
