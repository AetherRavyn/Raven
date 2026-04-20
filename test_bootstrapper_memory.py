from __future__ import annotations

from unittest import mock

from app.core.bootstrapper import Bootstrapper


def test_bootstrapper_includes_relevant_memory(tmp_path) -> None:
    bootstrapper = Bootstrapper(str(tmp_path))
    with mock.patch(
        "app.core.memory_manager.MemoryManager.retrieve_context",
        return_value=["User prefers concise answers"],
    ):
        prompt = bootstrapper.build_system_prompt(query="preferences", user_id="u1")
    assert "Relevant Memories" in prompt
    assert "concise answers" in prompt
