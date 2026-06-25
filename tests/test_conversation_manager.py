"""Tests for ConversationManager + runtime integration (Day 18)."""

from __future__ import annotations

import os
from typing import Any


# -------------------------------------------------------------------
# ConversationManager unit tests
# -------------------------------------------------------------------


class TestConversationManagerIngest:
    def setup_method(self) -> None:
        from app.core.conversation import ConversationManager

        self.cm = ConversationManager(window_size=3)

    def test_ingest_creates_session(self) -> None:
        self.cm.ingest_turn("s1", "user", "hello")
        assert "s1" in self.cm.list_sessions()

    def test_ingest_returns_turn(self) -> None:
        t = self.cm.ingest_turn("s1", "user", "hello")
        assert t.role == "user"
        assert t.content == "hello"
        assert t.id  # non-empty

    def test_ingest_appends_to_working_memory(self) -> None:
        self.cm.ingest_turn("s1", "user", "Project: raven")
        wm = self.cm.get_or_create("s1")
        assert "project" in wm.facts
        assert wm.facts["project"] == "raven"

    def test_ingest_picks_up_topic(self) -> None:
        self.cm.ingest_turn("s1", "user", "About Phase D, what's next?")
        wm = self.cm.get_or_create("s1")
        assert wm.current_topic == "Phase D"

    def test_multiple_turns(self) -> None:
        for role, content in [
            ("user", "Project: raven. HelixDB is fast."),
            ("assistant", "Yes, HelixDB replaces Neo4j."),
            ("user", "ok"),
        ]:
            self.cm.ingest_turn("s1", role, content)
        wm = self.cm.get_or_create("s1")
        assert len(wm.recent_turns) == 3
        assert wm.facts == {"project": "raven"}


class TestConversationManagerCompression:
    def setup_method(self) -> None:
        from app.core.conversation import ConversationManager

        self.cm = ConversationManager(window_size=3, compress_threshold_multiplier=2)

    def test_compress_threshold(self) -> None:
        # window_size=3, threshold=6.  Should compress at 7+.
        for i in range(7):
            self.cm.ingest_turn("s1", "user", f"turn {i}")
        wm = self.cm.get_or_create("s1")
        # Right after the 7th turn, compression runs and
        # shrinks the deque to window_size (3).
        assert wm.summary
        assert len(wm.recent_turns) == 3

    def test_compression_composes_with_subsequent_ingest(self) -> None:
        # After compression, subsequent ingest_turn calls
        # grow the deque again — compression is incremental.
        for i in range(7):
            self.cm.ingest_turn("s1", "user", f"turn {i}")
        # 7th turn triggers compression → deque shrinks to 3.
        assert len(self.cm.get_or_create("s1").recent_turns) == 3
        # 8th turn grows the deque back to 4 (no compression yet).
        self.cm.ingest_turn("s1", "user", "turn 7")
        assert len(self.cm.get_or_create("s1").recent_turns) == 4

    def test_explicit_maybe_compress(self) -> None:
        for i in range(5):
            self.cm.ingest_turn("s1", "user", f"turn {i}")
        wm = self.cm.get_or_create("s1")
        # Not yet past threshold (5 < 6).
        result = self.cm.maybe_compress("s1")
        assert result is None
        assert wm.summary == ""

    def test_summary_fn_swap(self) -> None:

        def my_fn(turns: list[Any], prior: str) -> str:
            return f"<<{len(turns)} summarized>>"

        self.cm.set_summary_fn(my_fn)
        for i in range(7):
            self.cm.ingest_turn("s1", "user", f"turn {i}")
        wm = self.cm.get_or_create("s1")
        # 7 turns - 3 kept = 4 summarized.
        assert "<<4 summarized>>" in wm.summary


class TestConversationManagerContext:
    def setup_method(self) -> None:
        from app.core.conversation import ConversationManager

        self.cm = ConversationManager()

    def test_context_empty_session(self) -> None:
        assert self.cm.context_for_prompt("s1") == ""

    def test_context_includes_sections(self) -> None:
        self.cm.ingest_turn("s1", "user", "project=raven")
        text = self.cm.context_for_prompt("s1")
        assert "Topic:" in text
        assert "Known facts:" in text
        assert "project = raven" in text

    def test_context_max_chars(self) -> None:
        for i in range(20):
            self.cm.ingest_turn("s1", "user", f"this is turn {i} with some content")
        text = self.cm.context_for_prompt("s1", max_chars=200)
        assert len(text) <= 203  # 200 + the "..." suffix

    def test_facts_returns_dict(self) -> None:
        self.cm.ingest_turn("s1", "user", "project=raven. owner=alice.")
        facts = self.cm.facts("s1")
        assert facts == {"project": "raven", "owner": "alice"}

    def test_topic_returns_string_or_none(self) -> None:
        assert self.cm.topic("s1") is None
        self.cm.ingest_turn("s1", "user", "About Phase D, what's next?")
        assert self.cm.topic("s1") == "Phase D"


class TestConversationManagerResolve:
    def setup_method(self) -> None:
        from app.core.conversation import ConversationManager

        self.cm = ConversationManager()

    def test_resolve_pronoun(self) -> None:
        self.cm.ingest_turn("s1", "user", "First")
        self.cm.ingest_turn("s1", "assistant", "Second")
        r = self.cm.resolve_reference("s1", "it")
        assert r.found
        assert r.turn is not None
        assert r.strategy == "pronoun"

    def test_resolve_unknown_session(self) -> None:
        r = self.cm.resolve_reference("nope", "it")
        assert not r.found

    def test_resolve_references_batch(self) -> None:
        self.cm.ingest_turn("s1", "user", "First")
        self.cm.ingest_turn("s1", "assistant", "Second")
        out = self.cm.resolve_references("s1", ["it", "earlier"])
        assert len(out) == 2


class TestConversationManagerPersistence:
    def setup_method(self) -> None:
        from app.core.conversation import ConversationManager

        self.cm = ConversationManager()

    def test_serialize_none_for_unknown(self) -> None:
        assert self.cm.serialize("nope") is None

    def test_round_trip(self) -> None:
        self.cm.ingest_turn("s1", "user", "project=raven")
        data = self.cm.serialize("s1")
        assert data is not None
        # Restore into a fresh manager
        from app.core.conversation import ConversationManager

        cm2 = ConversationManager()
        cm2.restore("s1", data)
        assert "s1" in cm2.list_sessions()
        facts = cm2.facts("s1")
        assert facts == {"project": "raven"}

    def test_clear_drops_session(self) -> None:
        self.cm.ingest_turn("s1", "user", "hello")
        self.cm.clear("s1")
        assert "s1" not in self.cm.list_sessions()

    def test_clear_all(self) -> None:
        self.cm.ingest_turn("s1", "user", "hi")
        self.cm.ingest_turn("s2", "user", "hello")
        self.cm.clear_all()
        assert self.cm.list_sessions() == []


class TestConversationManagerExplain:
    def setup_method(self) -> None:
        from app.core.conversation import ConversationManager

        self.cm = ConversationManager()

    def test_explain_empty_session(self) -> None:
        out = self.cm.explain("s1")
        assert out == {"session_id": "s1", "present": False}

    def test_explain_with_data(self) -> None:
        self.cm.ingest_turn("s1", "user", "project=raven. HelixDB is fast.")
        out = self.cm.explain("s1")
        assert out["present"] is True
        assert out["facts"] == {"project": "raven"}
        assert "HelixDB" in out["entities_top"]


# -------------------------------------------------------------------
# Runtime integration tests
# -------------------------------------------------------------------


class TestRuntimeWiring:
    def setup_method(self) -> None:
        # Force the env flag for the duration of each test.
        self._old = os.environ.get("RAVEN_CONVERSATION_V2")
        os.environ["RAVEN_CONVERSATION_V2"] = "1"

    def teardown_method(self) -> None:
        if self._old is None:
            os.environ.pop("RAVEN_CONVERSATION_V2", None)
        else:
            os.environ["RAVEN_CONVERSATION_V2"] = self._old

    def test_runtime_has_conversation_manager(self) -> None:
        from app.core.runtime import AgentRuntime

        r = AgentRuntime()
        assert r._use_conversation_v2 is True
        assert r.conversation_manager is not None
        # The manager should be empty until turns are ingested.
        assert r.conversation_manager.list_sessions() == []

    def test_ingest_then_context(self) -> None:
        from app.core.runtime import AgentRuntime

        r = AgentRuntime()
        # Simulate ingesting a few turns (this is what
        # execute_turn would do).
        sid = "test-session-1"
        r.conversation_manager.ingest_turn(sid, "user", "Project: raven")
        r.conversation_manager.ingest_turn(sid, "assistant", "Acknowledged. project=raven.")
        ctx = r.conversation_manager.context_for_prompt(sid)
        assert "Topic:" in ctx
        assert "project = raven" in ctx
        assert "Recent turns:" in ctx


class TestRuntimeFlagOff:
    def setup_method(self) -> None:
        self._old = os.environ.get("RAVEN_CONVERSATION_V2")
        os.environ.pop("RAVEN_CONVERSATION_V2", None)

    def teardown_method(self) -> None:
        if self._old is not None:
            os.environ["RAVEN_CONVERSATION_V2"] = self._old

    def test_flag_off_by_default(self) -> None:
        from app.core.runtime import AgentRuntime

        r = AgentRuntime()
        assert r._use_conversation_v2 is False
        # Manager is still built (so callers can opt-in later)
        # but the runtime won't auto-ingest.
        assert r.conversation_manager is not None
