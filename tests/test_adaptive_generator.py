import pytest

from app.adaptive.generator import CapabilityProposalGenerator
from app.adaptive.proposals import CapabilityProposalStore


def test_missing_capability_is_saved_for_review_without_running_source(tmp_path):
    marker = tmp_path / "executed"
    store = CapabilityProposalStore(tmp_path / "proposals")
    captured = []

    def transport(payload):
        captured.append(payload)
        return {
            "source": f"open({str(marker)!r}, 'w').write('bad')\n",
            "summary": "Research a restaurant",
            "dependencies": [],
            "proposed_tests": ["test candidate ranking"],
            "tool_schema": {"name": "find_restaurant", "effect": "read", "arguments": {}},
        }

    generator = CapabilityProposalGenerator(transport, store)
    result = generator.generate("Find dinner options", "restaurant ranking")

    assert result["status"] == "pending_review"
    assert store.read_source(result["id"]).startswith("open(")
    assert not marker.exists()
    assert captured[0]["request"] == "Find dinner options"
    assert captured[0]["missing_capability"] == "restaurant ranking"
    assert "source" in captured[0]["response_schema"]["required"]


@pytest.mark.parametrize("response", [
    {"source": "pass"},
    {"source": "pass", "summary": "ok", "dependencies": "pip install x",
     "proposed_tests": [], "tool_schema": {"name": "x"}},
    {"source": "pass", "summary": "ok", "dependencies": [],
     "proposed_tests": [], "tool_schema": {"name": "x"}, "execute": True},
])
def test_malformed_generation_creates_no_artifact(tmp_path, response):
    store = CapabilityProposalStore(tmp_path / "proposals")
    generator = CapabilityProposalGenerator(lambda payload: response, store)

    with pytest.raises(ValueError):
        generator.generate("Find dinner options", "restaurant ranking")

    assert not (tmp_path / "proposals").exists()


def test_transport_failure_creates_no_artifact(tmp_path):
    store = CapabilityProposalStore(tmp_path / "proposals")

    def fail(payload):
        raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        CapabilityProposalGenerator(fail, store).generate("Find dinner options", "restaurant ranking")
    assert not (tmp_path / "proposals").exists()
