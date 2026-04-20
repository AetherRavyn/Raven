from __future__ import annotations

from unittest import mock

from app.core.memory_manager import MemoryManager


def test_memory_manager_extracts_preferences_and_facts(monkeypatch) -> None:
    mm = MemoryManager()
    extract = mm.extract(
        "I prefer concise answers. My name is Alex. Please use the weather tool."
    )
    assert extract.preferences
    assert extract.facts
    assert extract.tool_guides


def test_memory_manager_store_calls_backend(monkeypatch) -> None:
    mm = MemoryManager()
    with mock.patch.object(mm.store, "save") as save:
        mm.store_extraction(
            "I prefer concise answers. Remember that my laptop IP is 1.2.3.4."
        )
        assert save.call_count >= 2
