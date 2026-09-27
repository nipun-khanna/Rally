from datetime import datetime, timezone
from app.models import ChatMessage
from app.tone import group_tone


def msg(text, index=0):
    return ChatMessage(str(index), 'chat', 'person', text, datetime.now(timezone.utc))


def test_casual_and_formal_group_tone():
    assert group_tone([msg('yo wanna grab food lol'), msg('yeah bro lets go', 1)]) == 'casual'
    assert group_tone([msg('this shit is so fucking late wtf'), msg('lmao fuck it ngl', 1)]) == 'casual'
    assert group_tone([msg('Good evening, could we please confirm our reservation?'),
                       msg('Certainly. Thank you for coordinating.', 1)]) == 'formal'
    assert group_tone([msg('Dinner Friday?')]) == 'neutral'


def test_rally_output_does_not_determine_tone():
    assert group_tone([ChatMessage('1','chat','rally','yo lol',datetime.now(timezone.utc),True)]) == 'neutral'


def test_formal_hint_comes_from_recent_human_context():
    assert group_tone([msg('yo bro lol',0)] + [msg('Good evening, please confirm the time.',1),
                                                   msg('Certainly, thank you.',2)]) == 'formal'
