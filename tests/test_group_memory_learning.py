from app.agent import MemoryCandidate
from app.group_memory import GroupMemoryStore
from app.group_turns import GroupTurnStore
from app.models import ChatMessage
from app.orchestrator import RallyService
from app.store import Store
from tests.test_group_conversation_service import ConversationAgent, HACK, LOCAL, NOW


def test_learning_is_group_scoped_and_redacts_sensitive_candidates(tmp_path):
    db = tmp_path / "rally.sqlite3"
    agent = ConversationAgent()
    agent.candidates = [
        MemoryCandidate(key="food.preference", fact="the group prefers ramen"),
        MemoryCandidate(key="secret", fact="password: hunter2"),
        MemoryCandidate(key="crime", fact="how to steal a car"),
    ]
    sent = []
    service = RallyService(
        Store(db), agent, lambda facts: [], lambda chat, text: sent.append(text),
        group_memory=GroupMemoryStore(db), group_turns=GroupTurnStore(db),
        allowed_chat_ids={HACK, LOCAL},
    )
    service.receive(ChatMessage("h1", HACK, "nick", "Rally, we like ramen", NOW))
    facts = service.group_memory.list_facts(HACK)
    assert [item.fact for item in facts] == ["the group prefers ramen"]
    assert service.group_memory.list_facts(LOCAL) == []
    service.group_memory.forget(HACK, "food.preference")
    assert service.group_memory.prompt_context(HACK) == ""


def test_background_learning_from_ordinary_chat_stays_in_group(tmp_path):
    db = tmp_path / "rally.sqlite3"
    agent = ConversationAgent()
    agent.learned = []

    def learn_memory(request, messages, *, memory_context=""):
        agent.learned.append((request, memory_context))
        return [MemoryCandidate(key="food.preference", fact="the group prefers tacos")]

    agent.learn_memory = learn_memory
    sent = []
    service = RallyService(
        Store(db), agent, lambda facts: [], lambda chat, text: sent.append(text),
        group_memory=GroupMemoryStore(db), group_turns=GroupTurnStore(db),
        allowed_chat_ids={HACK, LOCAL},
    )
    service.receive(ChatMessage("chat1", HACK, "nick", "we should do tacos next time", NOW))
    assert sent == []
    assert [item.fact for item in service.group_memory.list_facts(HACK)] == ["the group prefers tacos"]
    assert service.group_memory.list_facts(LOCAL) == []
    assert agent.learned[0][0] == "we should do tacos next time"


def test_webhook_returns_before_extract_when_deferred(tmp_path):
    import threading
    db = tmp_path / "rally.sqlite3"
    started = threading.Event()
    release = threading.Event()
    agent = ConversationAgent()

    def extract(messages, previous):
        started.set()
        assert release.wait(2)
        return agent.__class__.extract(agent, messages, previous)

    agent.extract = extract
    sent = []
    service = RallyService(
        Store(db), agent, lambda facts: [], lambda chat, text: sent.append(text),
        group_memory=GroupMemoryStore(db), group_turns=GroupTurnStore(db),
        allowed_chat_ids={HACK, LOCAL},
        defer_heavy_work=True,
    )
    assert service.receive(ChatMessage("d1", HACK, "nick", "Rally, recap?", NOW)) is True
    assert sent
    assert not service.store.is_processed("d1")
    assert started.wait(2)
    release.set()
    for _ in range(50):
        if service.store.is_processed("d1"):
            break
        threading.Event().wait(0.05)
    assert service.store.is_processed("d1")
    if service._pool:
        service._pool.shutdown(wait=True)
