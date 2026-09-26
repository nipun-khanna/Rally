import pytest

from app.adaptive.agent import AdaptivePlanner
from app.adaptive.tools import ToolRegistry, ToolSpec


def registry():
    tools = ToolRegistry({'chat-a'})
    tools.register(ToolSpec('get_plan_status', {}, 'read', lambda chat_id, args: {'status':'none'}))
    return tools


def test_planner_receives_only_current_request_and_tool_metadata():
    calls = []
    def transport(schema, prompt, data):
        calls.append(data)
        return {'steps':[{'tool':'get_plan_status','args':{}}], 'missing_capability':None}
    plan = AdaptivePlanner(transport).plan('Rally, what is the plan?', 'chat-a', registry())
    assert plan['status'] == 'planned'
    assert plan['steps'] == [{'tool':'get_plan_status','args':{},'effect':'read'}]
    assert set(calls[0]) == {'request', 'tools'}


def test_unknown_tool_becomes_missing_capability_without_execution():
    planner = AdaptivePlanner(lambda *_: {'steps':[{'tool':'send_money','args':{'amount':10}}],
                                          'missing_capability':None})
    plan = planner.plan('Rally send money', 'chat-a', registry())
    assert plan['status'] == 'blocked' and plan['steps'] == []
    assert plan['missing_capability'] == 'send_money'


def test_malformed_or_overlong_plans_fail_closed():
    planner = AdaptivePlanner(lambda *_: {'steps':[{'tool':'get_plan_status','args':{}}]*4,
                                          'missing_capability':None})
    with pytest.raises(ValueError):
        planner.plan('Rally status', 'chat-a', registry())
    planner = AdaptivePlanner(lambda *_: {'steps':[{'tool':'get_plan_status','args':{'bad':1}}],
                                          'missing_capability':None})
    with pytest.raises(ValueError):
        planner.plan('Rally status', 'chat-a', registry())
