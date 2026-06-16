"""Tests for the conversation package (Day 17, Phase D)."""

from __future__ import annotations

from collections import deque


from app.core.conversation import (
    Compressor,
    FollowUpResolver,
    Turn,
    WorkingMemory,
    apply_to_working_memory,
    detect_topic,
    deterministic_summary,
    extract_entities,
    extract_facts,
    resolve_references,
)


def _t(idx: int, role: str, content: str) -> Turn:
    return Turn(id=f"t{idx}", role=role, content=content)


# -------------------------------------------------------------------
# Turn + extractors
# -------------------------------------------------------------------


class TestExtractFacts:
    def test_simple_key_value(self) -> None:
        f = extract_facts(_t(1, "user", "name=alice"))
        assert f == {"name": "alice"}

    def test_multiple_facts_in_one_turn(self) -> None:
        f = extract_facts(_t(1, "user", "name=alice project=saras"))
        assert f == {"name": "alice", "project": "saras"}

    def test_case_insensitive_key(self) -> None:
        f = extract_facts(_t(1, "user", "Project=saras"))
        assert f == {"project": "saras"}

    def test_trailing_punctuation_stripped(self) -> None:
        f = extract_facts(_t(1, "user", "name=alice."))
        assert f == {"name": "alice"}

    def test_tool_role_skipped(self) -> None:
        f = extract_facts(_t(1, "tool", "name=alice"))
        assert f == {}

    def test_first_wins_on_duplicate_key(self) -> None:
        f = extract_facts(_t(1, "user", "name=alice name=bob"))
        assert f == {"name": "alice"}


class TestExtractEntities:
    def test_multi_word_phrase(self) -> None:
        e = extract_entities("The Home Sentinel is here.")
        assert "The Home Sentinel" in e

    def test_compound_word(self) -> None:
        e = extract_entities("HelixDB is fast.")
        assert "HelixDB" in e

    def test_stopword_filtered(self) -> None:
        e = extract_entities("The and is a I")
        assert e == []

    def test_topic_hint_leading_word_dropped(self) -> None:
        e = extract_entities("About Phase D, what is the plan?")
        assert "About Phase" not in e
        # The remaining single word "Phase" still appears.
        assert "Phase" in e

    def test_dedup(self) -> None:
        e = extract_entities("HelixDB and HelixDB again")
        assert e.count("HelixDB") == 1


class TestDetectTopic:
    def test_explicit_about(self) -> None:
        t = detect_topic(_t(1, "user", "About Phase D, what's next?"), None)
        assert t == "Phase D"

    def test_about_lowercase_hint_still_works(self) -> None:
        # "about" hint word is matched case-insensitively, but
        # the captured noun must be Capitalized (proper noun).
        t = detect_topic(_t(1, "user", "about Heli X"), None)
        assert t is not None
        assert t.lower().startswith("heli")

    def test_regarding(self) -> None:
        t = detect_topic(_t(1, "user", "Regarding the migration plan"), None)
        assert "migration" in (t or "").lower() or t == "Migration Plan"

    def test_short_followup_keeps_prior(self) -> None:
        t = detect_topic(_t(1, "user", "ok"), "prior topic")
        assert t == "prior topic"

    def test_falls_back_to_first_sentence(self) -> None:
        t = detect_topic(_t(1, "user", "Tell me about Phase C."), None)
        assert "phase" in (t or "").lower()

    def test_empty_returns_prior(self) -> None:
        t = detect_topic(_t(1, "user", ""), "prior")
        assert t == "prior"


# -------------------------------------------------------------------
# WorkingMemory
# -------------------------------------------------------------------


class TestWorkingMemory:
    def test_initial_state(self) -> None:
        wm = WorkingMemory()
        assert wm.recent_turns == deque(maxlen=20)
        assert wm.facts == {}
        assert wm.entities == Counter()  # type: ignore[name-defined]
        assert wm.current_topic is None
        assert wm.summary == ""

    def test_add_turn_updates_facts(self) -> None:
        wm = WorkingMemory()
        wm.add_turn(_t(1, "user", "project=saras"))
        assert wm.facts == {"project": "saras"}

    def test_add_turn_updates_entities(self) -> None:
        wm = WorkingMemory()
        wm.add_turn(_t(1, "user", "HelixDB is fast."))
        assert wm.entities["HelixDB"] == 1

    def test_add_turn_updates_topic(self) -> None:
        wm = WorkingMemory()
        wm.add_turn(_t(1, "user", "About Phase D, what's next?"))
        assert wm.current_topic == "Phase D"

    def test_short_followup_keeps_topic(self) -> None:
        wm = WorkingMemory()
        wm.add_turn(_t(1, "user", "About Phase D, what's next?"))
        wm.add_turn(_t(2, "user", "ok"))
        assert wm.current_topic == "Phase D"

    def test_recent_turns_deque_capped(self) -> None:
        wm = WorkingMemory()
        for i in range(50):
            wm.add_turn(_t(i, "user", f"turn {i}"))
        assert len(wm.recent_turns) == 20
        assert wm.recent_turns[0].id == "t30"

    def test_serialise_round_trip(self) -> None:
        wm = WorkingMemory(user_id="alice")
        wm.add_turn(_t(1, "user", "project=saras. HelixDB is fast."))
        wm.add_turn(_t(2, "assistant", "Phase D is about conversational depth."))
        wm.summary = "Earlier the user mentioned saras."

        data = wm.to_dict()
        wm2 = WorkingMemory.from_dict(data)
        assert wm2.user_id == "alice"
        assert wm2.facts == wm.facts
        assert wm2.entities == wm.entities
        assert wm2.current_topic == wm.current_topic
        assert wm2.summary == wm.summary
        assert [t.id for t in wm2.recent_turns] == [t.id for t in wm.recent_turns]

    def test_context_string_includes_sections(self) -> None:
        wm = WorkingMemory()
        wm.add_turn(_t(1, "user", "project=saras"))
        wm.summary = "User is working on saras."
        text = wm.context_string()
        assert "Summary:" in text
        assert "Topic:" in text
        assert "Known facts:" in text
        assert "Recent turns:" in text
        assert "project = saras" in text

    def test_context_string_no_facts(self) -> None:
        wm = WorkingMemory()
        text = wm.context_string()
        assert "Known facts:" not in text

    def test_custom_fact_extractor(self) -> None:
        def my_extractor(t: Turn) -> dict[str, str]:
            return {"x": "1"} if "x" in t.content else {}

        wm = WorkingMemory(fact_extractor=my_extractor)
        wm.add_turn(_t(1, "user", "x marks the spot"))
        assert wm.facts == {"x": "1"}

    def test_fact_extractor_exception_ignored(self) -> None:
        def bad_extractor(t: Turn) -> dict[str, str]:
            raise RuntimeError("explode")

        wm = WorkingMemory(fact_extractor=bad_extractor)
        # Should not raise.
        wm.add_turn(_t(1, "user", "project=saras"))
        assert wm.facts == {}  # the bad extractor returned nothing


# -------------------------------------------------------------------
# Compressor
# -------------------------------------------------------------------


class TestCompressor:
    def test_under_window_keeps_everything(self) -> None:
        c = Compressor(window_size=5)
        turns = [_t(i, "user", f"turn {i}") for i in range(3)]
        result = c.compress(turns)
        assert result.dropped_count == 0
        assert result.kept_turns == turns
        assert result.summary == ""  # prior is empty, no summarization

    def test_over_window_drops_old(self) -> None:
        c = Compressor(window_size=2)
        turns = [_t(i, "user", f"turn {i}") for i in range(5)]
        result = c.compress(turns)
        assert result.dropped_count == 3
        assert [t.id for t in result.kept_turns] == ["t3", "t4"]
        assert result.summary  # non-empty

    def test_summary_includes_prior(self) -> None:
        c = Compressor(window_size=2)
        turns = [_t(i, "user", f"turn {i}") for i in range(5)]
        result = c.compress(turns, prior_summary="<prior>")
        assert result.summary.startswith("<prior>")

    def test_deterministic_summary_basic(self) -> None:
        turns = [_t(i, "user", f"turn {i}") for i in range(3)]
        s = deterministic_summary(turns)
        assert "[3 turn(s) summarized]" in s
        assert "- user: turn 0" in s
        assert "- user: turn 2" in s

    def test_deterministic_summary_empty(self) -> None:
        assert deterministic_summary([]) == ""

    def test_summary_fn_exception_falls_back(self) -> None:
        def bad_fn(turns: list[Turn], prior: str) -> str:
            raise RuntimeError("explode")

        c = Compressor(window_size=2, summary_fn=bad_fn)
        turns = [_t(i, "user", f"turn {i}") for i in range(5)]
        result = c.compress(turns)
        # Falls back to deterministic.
        assert "turn(s) summarized" in result.summary

    def test_should_compress(self) -> None:
        c = Compressor(window_size=3)
        assert c.should_compress(7) is True
        assert c.should_compress(5) is False

    def test_apply_to_working_memory(self) -> None:
        turns = [_t(i, "user", f"turn {i}") for i in range(3)]
        new_summary, new_deque = apply_to_working_memory("summary", turns, maxlen=10)
        assert new_summary == "summary"
        assert isinstance(new_deque, deque)
        assert len(new_deque) == 3
        assert new_deque[0].id == "t0"


# -------------------------------------------------------------------
# FollowUpResolver
# -------------------------------------------------------------------


class TestResolverPronoun:
    def test_it_resolves_to_most_recent(self) -> None:
        wm = WorkingMemory()
        wm.add_turn(_t(1, "user", "First message"))
        wm.add_turn(_t(2, "assistant", "Second message"))
        r = FollowUpResolver(wm).resolve("it")
        assert r.found
        assert r.turn is not None
        assert r.turn.id == "t2"
        assert r.strategy == "pronoun"

    def test_that_resolves_to_most_recent(self) -> None:
        wm = WorkingMemory()
        wm.add_turn(_t(1, "user", "First"))
        wm.add_turn(_t(2, "assistant", "Second"))
        r = FollowUpResolver(wm).resolve("that")
        assert r.found
        assert r.turn is not None
        assert r.turn.id == "t2"

    def test_continuation_with_pronoun(self) -> None:
        wm = WorkingMemory()
        wm.add_turn(_t(1, "user", "The HelixDB is fast."))
        wm.add_turn(_t(2, "assistant", "Yes."))
        r = FollowUpResolver(wm).resolve("Does it support joins?")
        assert r.found
        assert r.turn is not None
        assert r.turn.id == "t2"


class TestResolverDemonstrative:
    def test_that_noun_finds_mention(self) -> None:
        wm = WorkingMemory()
        wm.add_turn(_t(1, "user", "Tell me about the resolver."))
        wm.add_turn(_t(2, "assistant", "OK."))
        r = FollowUpResolver(wm).resolve("that resolver")
        assert r.found
        assert r.turn is not None
        assert r.turn.id == "t1"
        assert r.strategy == "demonstrative"

    def test_missing_noun_returns_none(self) -> None:
        wm = WorkingMemory()
        wm.add_turn(_t(1, "user", "First message"))
        r = FollowUpResolver(wm).resolve("that widget")
        assert not r.found
        assert r.strategy == "demonstrative"


class TestResolverTemporal:
    def test_earlier_returns_previous_turn(self) -> None:
        wm = WorkingMemory()
        wm.add_turn(_t(1, "user", "First"))
        wm.add_turn(_t(2, "assistant", "Second"))
        wm.add_turn(_t(3, "user", "Earlier you said something"))
        r = FollowUpResolver(wm).resolve("earlier")
        assert r.found
        assert r.turn is not None
        assert r.turn.id == "t2"
        assert r.strategy == "temporal"

    def test_before_returns_previous(self) -> None:
        wm = WorkingMemory()
        wm.add_turn(_t(1, "user", "First"))
        wm.add_turn(_t(2, "assistant", "Second"))
        r = FollowUpResolver(wm).resolve("before that")
        assert r.found
        assert r.turn is not None
        assert r.turn.id == "t1"


class TestResolverTopic:
    def test_topic_hint_finds_mention(self) -> None:
        wm = WorkingMemory()
        wm.add_turn(_t(1, "user", "About Phase D, what's next?"))
        wm.add_turn(_t(2, "assistant", "Phase D is about conversational depth."))
        wm.add_turn(_t(3, "user", "Tell me about Phase E"))
        wm.add_turn(_t(4, "user", "And Phase F?"))
        # "And Phase F" — the most recent turn mentioning Phase F is t4.
        r = FollowUpResolver(wm).resolve("And Phase F")
        assert r.found
        assert r.turn is not None
        assert r.turn.id == "t4"
        assert r.strategy == "topic"

    def test_topic_hint_with_current_topic_match(self) -> None:
        wm = WorkingMemory()
        wm.add_turn(_t(1, "user", "About HelixDB, what about joins?"))
        wm.add_turn(_t(2, "assistant", "HelixDB joins are fast."))
        wm.add_turn(_t(3, "user", "Tell me more"))
        # current_topic should be "HelixDB" or similar after t1
        r = FollowUpResolver(wm).resolve("And HelixDB")
        assert r.found
        assert r.turn is not None
        assert r.strategy == "topic"


class TestResolverFallback:
    def test_no_match_returns_most_recent(self) -> None:
        wm = WorkingMemory()
        wm.add_turn(_t(1, "user", "First"))
        wm.add_turn(_t(2, "assistant", "Second"))
        r = FollowUpResolver(wm).resolve("blah blah")
        assert r.found
        assert r.turn is not None
        assert r.turn.id == "t2"
        assert r.strategy == "fallback"

    def test_empty_transcript_returns_none(self) -> None:
        wm = WorkingMemory()
        r = FollowUpResolver(wm).resolve("it")
        assert not r.found

    def test_empty_reference_returns_none(self) -> None:
        wm = WorkingMemory()
        wm.add_turn(_t(1, "user", "First"))
        r = FollowUpResolver(wm).resolve("")
        assert not r.found


class TestResolveReferences:
    def test_batch_resolves(self) -> None:
        wm = WorkingMemory()
        wm.add_turn(_t(1, "user", "First"))
        wm.add_turn(_t(2, "assistant", "Second"))
        out = resolve_references(wm, ["it", "earlier"])
        assert len(out) == 2
        assert out[0].turn is not None
        assert out[0].turn.id == "t2"
        assert out[1].turn is not None
        assert out[1].turn.id == "t1"


# Helper so the file's own imports succeed without an unused warning.
from collections import Counter  # noqa: E402
