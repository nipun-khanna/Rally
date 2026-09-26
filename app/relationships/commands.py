"""Explicit, deterministic private commands; no text history is sent to an LLM."""

from datetime import datetime, timedelta
import re
from zoneinfo import ZoneInfo


HELP = ('Try “remind me to call Mom every week”, “I called Mom today”, '
        '“relationship status”, “change Mom to every 10 days”, '
        '“snooze Mom until Friday”, “pause reminders for Mom”, '
        '“resume reminders for Mom”, or “remove Mom”.')
MODES = {'call': 'call', 'visit': 'visit', 'message': 'message', 'text': 'message', 'connect with': 'other'}
PAST = {'called': 'call', 'visited': 'visit', 'messaged': 'message', 'texted': 'message', 'connected with': 'other'}


def cadence(text: str) -> int:
    text = text.strip().lower()
    if text in ('week', 'weekly'):
        return 7
    if text in ('day', 'daily'):
        return 1
    match = re.fullmatch(r'(\d+)\s+(days?|weeks?)', text)
    if not match:
        raise ValueError('Specify a cadence in days or weeks')
    days = int(match[1]) * (7 if match[2].startswith('week') else 1)
    if not 1 <= days <= 90:
        raise ValueError('Cadence must be 1–90 days')
    return days


def date_value(text: str, now: datetime, zone: str, *, future: bool = False) -> datetime:
    local = now.astimezone(ZoneInfo(zone))
    text = re.sub(r'^on\s+', '', text.strip().lower())
    if text == 'today':
        result = local
    elif text == 'yesterday':
        result = local - timedelta(days=1)
    elif text == 'tomorrow':
        result = local + timedelta(days=1)
    elif text in ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'):
        if not future:
            raise ValueError('For past contact, use today, yesterday, or an ISO date')
        weekday = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday').index(text)
        result = local + timedelta(days=(weekday - local.weekday()) % 7 or 7)
    else:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
            raise ValueError('Use today, yesterday, an ISO date, or a future weekday for snooze')
        day = datetime.strptime(text, '%Y-%m-%d').date()
        result = datetime(day.year, day.month, day.day, local.hour, local.minute, local.second, tzinfo=ZoneInfo(zone))
    if future and result <= now:
        raise ValueError('Snooze date must be in the future')
    if not future and result > now:
        raise ValueError('Cannot confirm contact in the future')
    return result


def reply(store, owner: str, text: str, message_id: str, now: datetime, learner=None) -> str:
    command = re.sub(r'^\s*(?:hey\s+)?rally[\s,:!?—-]*', '', text, flags=re.I).strip().rstrip('.!?')
    try:
        config = store.config(owner)
        if re.fullmatch(r'(?:relationship|reminder) status|(?:my )?relationships|help', command, re.I):
            rows = store.list_relationships(owner)
            if not rows:
                return 'No relationships configured. ' + HELP
            lines = [f"{p['label']}: {p['mode']} every {p['days']} days; "
                     f"{'paused' if p['paused'] else 'active'}; last recorded contact "
                     f"{p['last_confirmed_at'][:10] if p['last_confirmed_at'] else 'unknown'}"
                     + (f"; snoozed until {p['snooze_until'][:10]}" if p['snooze_until'] else '') for p in rows]
            uncertain = sum(d['status'] == 'uncertain' for d in store.deliveries(owner))
            return '\n'.join(lines) + (f'\n{uncertain} delivery outcome(s) uncertain; no automatic resend.' if uncertain else '')
        match = re.fullmatch(r'remind me to (call|visit|message|text|connect with) (.+?) every (.+)', command, re.I)
        if match:
            mode, label, frequency = match.groups()
            store.upsert(owner, label, MODES[mode.lower()], cadence(frequency), now)
            return f"I'll remind you to {mode.lower()} {label} every {cadence(frequency)} days, privately after {config['hour']:02d}:00 {config['zone']}."
        match = re.fullmatch(r'I (called|visited|messaged|texted|connected with) (.+?) (today|yesterday|tomorrow|on \d{4}-\d{2}-\d{2})', command, re.I)
        if match:
            mode, label, when = match.groups()
            at = date_value(when, now, config['zone'])
            store.confirm(owner, label, PAST[mode.lower()], at, message_id)
            return f'Recorded that you {mode.lower()} {label} on {at.date().isoformat()}.'
        match = re.fullmatch(r'change (.+?) to every (.+)', command, re.I)
        if match:
            label, frequency = match.groups()
            person = store.person(owner, label)
            days = cadence(frequency)
            store.upsert(owner, person['label'], person['mode'], days, now)
            return f"Changed {person['label']} to every {days} days."
        match = re.fullmatch(r'(pause|resume)(?: reminders for)? (.+)', command, re.I)
        if match:
            action, label = match.groups()
            store.control(owner, label, action.lower(), now)
            return f'{action.capitalize()}d reminders for {label}.'
        match = re.fullmatch(r'remove(?: reminders for)? (.+)', command, re.I)
        if match:
            store.control(owner, match[1], 'remove', now)
            return f'Removed {match[1]} and their stored relationship evidence.'
        match = re.fullmatch(r'snooze (.+?) until (.+)', command, re.I)
        if match:
            label, when = match.groups()
            until = date_value(when, now, config['zone'], future=True)
            store.control(owner, label, 'snooze', now, until)
            return f'Snoozed {label} until {until.date().isoformat()}.'
        return 'I need a supported, explicit relationship request. ' + HELP
    except ValueError as exc:
        return str(exc) + '. ' + HELP
