import stat

import pytest

from app.adaptive.proposals import CapabilityProposalStore


def test_source_remains_inert_and_pending_review(tmp_path):
    marker = tmp_path / "executed"
    source = f"open({str(marker)!r}, 'w').write('bad')\n"
    store = CapabilityProposalStore(tmp_path / "data" / "capability_proposals")

    proposal = store.create(
        source=source,
        summary="Find a restaurant",
        dependencies=["places-client"],
        proposed_tests=["test restaurant lookup"],
        tool_schema={"name": "find_restaurant", "effect": "read"},
    )

    assert proposal["status"] == "pending_review"
    assert proposal["syntax_valid"] is True
    assert proposal["summary"] == "Find a restaurant"
    assert proposal["dependencies"] == ["places-client"]
    assert proposal["proposed_tests"] == ["test restaurant lookup"]
    assert proposal["tool_schema"] == {"name": "find_restaurant", "effect": "read"}
    assert not marker.exists()
    assert store.read_source(proposal["id"]) == source
    assert not marker.exists()
    artifact = tmp_path / "data" / "capability_proposals" / proposal["id"]
    assert stat.S_IMODE(artifact.stat().st_mode) == 0o700
    assert stat.S_IMODE((artifact / "source.py").stat().st_mode) == 0o600
    assert stat.S_IMODE((artifact / "metadata.json").stat().st_mode) == 0o600
    assert store.get(proposal["id"]) == proposal


def test_invalid_source_is_recorded_without_becoming_reviewable(tmp_path):
    store = CapabilityProposalStore(tmp_path / "proposals")

    proposal = store.create(
        source="def bad(:\n",
        summary="Broken capability",
        dependencies=[],
        proposed_tests=[],
        tool_schema={"name": "broken", "effect": "read"},
    )

    assert proposal["status"] == "invalid"
    assert proposal["syntax_valid"] is False
    assert proposal["syntax_error"]
    assert store.read_source(proposal["id"]) == "def bad(:\n"


def test_proposal_id_cannot_escape_artifact_directory(tmp_path):
    store = CapabilityProposalStore(tmp_path / "proposals")

    with pytest.raises(ValueError):
        store.read_source("../../secret")
    with pytest.raises(ValueError):
        store.get("../../secret")


def test_rejects_missing_review_metadata(tmp_path):
    store = CapabilityProposalStore(tmp_path / "proposals")

    with pytest.raises(ValueError):
        store.create(source="pass", summary="", dependencies=[], proposed_tests=[], tool_schema={"name": "x"})
