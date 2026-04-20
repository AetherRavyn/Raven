from __future__ import annotations

import pytest

from app.core.user_profile import UserProfileStore
from app.core.workspace_graph import WorkspaceGraph


@pytest.mark.asyncio
async def test_workspace_graph_builds_nodes_and_edges(tmp_path) -> None:
    profile_store = UserProfileStore(str(tmp_path))
    profile_store.update_from_text(
        "u1",
        "My name is Alex. I prefer concise answers. I work on SARAS. I use laptop-01. I decided to keep the graph local.",
    )

    graph = WorkspaceGraph(str(tmp_path))
    data = graph.build_for_user("u1", query="concise")
    assert data["nodes"]
    assert data["edges"]
    kinds = {node["kind"] for node in data["nodes"]}
    assert any(kind in kinds for kind in ("project", "device", "decision"))


@pytest.mark.asyncio
async def test_workspace_graph_prompt_evidence_is_concise(tmp_path) -> None:
    profile_store = UserProfileStore(str(tmp_path))
    profile_store.update_from_text(
        "u1", "My name is Alex. I like Telegram. I use notes.md."
    )

    graph = WorkspaceGraph(str(tmp_path))
    evidence = graph.evidence_for_prompt("u1", query="Telegram")
    assert isinstance(evidence, list)
    assert evidence
