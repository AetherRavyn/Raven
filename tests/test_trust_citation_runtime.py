"""Tests for ``app.core.trust.citation_runtime``.

Covers the per-turn citation context, attachment API, and
inline-injection rendering.
"""

from __future__ import annotations

import threading

import pytest

from app.core.trust.citation_runtime import (
    CitationContext,
    CitationInjector,
    InjectionMode,
    get_default_citation_injector,
    reset_default_citation_injector,
    set_default_citation_injector,
)
from app.core.trust.citations import (
    Citation,
    CitationManager,
    CitationSource,
    format_sources_list,
)


# -- fixtures ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Make every test start with a clean default injector."""
    reset_default_citation_injector()
    yield
    reset_default_citation_injector()


# -- CitationContext --------------------------------------------------------


class TestCitationContext:
    def test_default_state(self):
        ctx = CitationContext(turn_id="t1", user_id="u1", session_id="s1")
        assert ctx.turn_id == "t1"
        assert ctx.user_id == "u1"
        assert ctx.session_id == "s1"
        assert ctx.citations == []
        assert ctx.auto_inject is True
        assert ctx.mode == InjectionMode.BOTH
        assert ctx.is_closed() is False
        assert ctx.has_citations() is False
        assert ctx.ended_at is None
        assert ctx.metadata == {}

    def test_has_citations(self):
        c = Citation(source=CitationSource.MEMORY, ref="m1")
        ctx = CitationContext(turn_id="t1", user_id="u1", session_id="s1", citations=[c])
        assert ctx.has_citations() is True
        assert ctx.is_closed() is False

    def test_close(self):
        ctx = CitationContext(turn_id="t1", user_id="u1", session_id="s1")
        ctx.ended_at = ctx.started_at
        assert ctx.is_closed() is True


# -- CitationInjector: lifecycle -------------------------------------------


class TestBeginEnd:
    def test_begin_turn_returns_context(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1")
        assert isinstance(ctx, CitationContext)
        assert ctx.user_id == "u1"
        assert ctx.session_id == "s1"
        assert ctx.has_citations() is False

    def test_begin_turn_with_options(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(
            user_id="u1",
            session_id="s1",
            auto_inject=False,
            mode=InjectionMode.FOOTER,
            turn_id="custom-id",
            metadata={"channel": "discord"},
        )
        assert ctx.turn_id == "custom-id"
        assert ctx.auto_inject is False
        assert ctx.mode == InjectionMode.FOOTER
        assert ctx.metadata == {"channel": "discord"}

    def test_end_turn_marks_closed(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1")
        closed = inj.end_turn(ctx.turn_id)
        assert closed is not None
        assert closed.is_closed() is True
        assert closed.ended_at is not None

    def test_end_turn_unknown_returns_none(self):
        inj = CitationInjector()
        assert inj.end_turn("nope") is None

    def test_get_context_unknown(self):
        inj = CitationInjector()
        assert inj.get_context("nope") is None

    def test_get_context_returns_active(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1")
        got = inj.get_context(ctx.turn_id)
        assert got is ctx

    def test_has_citations_false(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1")
        assert inj.has_citations(ctx.turn_id) is False

    def test_has_citations_true(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1")
        inj.attach_source(ctx.turn_id, CitationSource.MEMORY, ref="m1")
        assert inj.has_citations(ctx.turn_id) is True

    def test_has_citations_unknown_turn(self):
        inj = CitationInjector()
        assert inj.has_citations("nope") is False


# -- attach_source ---------------------------------------------------------


class TestAttachSource:
    def test_attach_unknown_turn_returns_none(self):
        inj = CitationInjector()
        assert inj.attach_source("nope", CitationSource.MEMORY, ref="m1") is None

    def test_attach_registers_citation(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1")
        c = inj.attach_source(ctx.turn_id, CitationSource.MEMORY, ref="m1", title="Memory 1")
        assert c is not None
        assert c.source == CitationSource.MEMORY
        assert c.ref == "m1"
        assert c.title == "Memory 1"
        assert len(ctx.citations) == 1

    def test_attach_string_source(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1")
        c = inj.attach_source(ctx.turn_id, "memory", ref="m1")
        assert c.source == CitationSource.MEMORY

    def test_attach_dedupes_by_ref(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1")
        c1 = inj.attach_source(ctx.turn_id, CitationSource.MEMORY, ref="m1")
        c2 = inj.attach_source(ctx.turn_id, CitationSource.MEMORY, ref="m1", title="t2")
        assert c1.id == c2.id  # deduped — same id
        assert len(ctx.citations) == 1

    def test_attach_different_refs(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1")
        c1 = inj.attach_source(ctx.turn_id, CitationSource.MEMORY, ref="m1")
        c2 = inj.attach_source(ctx.turn_id, CitationSource.WEB, ref="https://a.com")
        assert c1.id != c2.id
        assert len(ctx.citations) == 2

    def test_attach_persists_in_manager(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1")
        c = inj.attach_source(ctx.turn_id, CitationSource.MEMORY, ref="m1")
        # Re-found via manager
        found = inj.manager().find(CitationSource.MEMORY, "m1")
        assert found is not None
        assert found.id == c.id


# -- attach_citation --------------------------------------------------------


class TestAttachCitation:
    def test_attach_prebuilt(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1")
        c = Citation(source=CitationSource.WEB, ref="https://a.com", title="A")
        assert inj.attach_citation(ctx.turn_id, c) is True
        assert len(ctx.citations) == 1

    def test_attach_unknown_turn(self):
        inj = CitationInjector()
        c = Citation(source=CitationSource.WEB, ref="https://a.com")
        assert inj.attach_citation("nope", c) is False

    def test_attach_dedupes(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1")
        c = Citation(source=CitationSource.WEB, ref="https://a.com")
        assert inj.attach_citation(ctx.turn_id, c) is True
        assert inj.attach_citation(ctx.turn_id, c) is False

    def test_attach_citations_bulk(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1")
        cs = [
            Citation(source=CitationSource.MEMORY, ref="m1"),
            Citation(source=CitationSource.WEB, ref="https://a.com"),
            Citation(source=CitationSource.MEMORY, ref="m1"),  # duplicate
        ]
        added = inj.attach_citations(ctx.turn_id, cs)
        assert added == 2
        assert len(ctx.citations) == 2


# -- inject ------------------------------------------------------------------


class TestInject:
    def test_no_citations_passthrough(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1")
        text, sources = inj.inject(ctx.turn_id, "Hello world.")
        assert text == "Hello world."
        assert sources == []

    def test_unknown_turn_no_citations_passthrough(self):
        inj = CitationInjector()
        text, sources = inj.inject("nope", "Hello world.")
        assert text == "Hello world."
        assert sources == []

    def test_single_citation_inline(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1")
        inj.attach_source(ctx.turn_id, CitationSource.MEMORY, ref="m1", title="M1")
        text, sources = inj.inject(ctx.turn_id, "Hello world.")
        # _attach_markers places markers BEFORE the final period.
        assert text.startswith("Hello world[1].")
        assert "[1] [memory] M1" in text
        assert len(sources) == 1

    def test_two_citations_inline(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1")
        inj.attach_source(ctx.turn_id, CitationSource.MEMORY, ref="m1", title="M1")
        inj.attach_source(ctx.turn_id, CitationSource.WEB, ref="https://a.com", title="A.com")
        text, sources = inj.inject(ctx.turn_id, "Fact A and B.")
        assert "[1][2]" in text
        assert "[1] [memory] M1" in text
        assert "[2] [web] A.com" in text
        assert len(sources) == 2

    def test_explicit_citations_override_context(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1")
        inj.attach_source(ctx.turn_id, CitationSource.MEMORY, ref="m1", title="M1")
        # Pass an empty list explicitly — should be no-citations
        text, sources = inj.inject(ctx.turn_id, "Hello.", citations=[])
        assert text == "Hello."
        assert sources == []

    def test_auto_inject_off(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1", auto_inject=False)
        inj.attach_source(ctx.turn_id, CitationSource.MEMORY, ref="m1", title="M1")
        text, sources = inj.inject(ctx.turn_id, "Hello.")
        assert text == "Hello."  # not modified
        assert len(sources) == 1  # but citations are returned

    def test_inject_mode_none(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1", mode=InjectionMode.NONE)
        inj.attach_source(ctx.turn_id, CitationSource.MEMORY, ref="m1", title="M1")
        text, sources = inj.inject(ctx.turn_id, "Hello.")
        assert text == "Hello."
        assert len(sources) == 1

    def test_inject_mode_footer_only(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1", mode=InjectionMode.FOOTER)
        inj.attach_source(ctx.turn_id, CitationSource.MEMORY, ref="m1", title="M1")
        text, _ = inj.inject(ctx.turn_id, "Hello world.")
        # No inline marker
        assert "[1]" not in text.split("\n\n")[0]
        # But footer present
        assert "[1] [memory] M1" in text

    def test_inject_mode_inline_only(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1", mode=InjectionMode.INLINE)
        inj.attach_source(ctx.turn_id, CitationSource.MEMORY, ref="m1", title="M1")
        text, _ = inj.inject(ctx.turn_id, "Hello world.")
        # Has inline marker (markers go before the final period)
        assert "Hello world[1]." in text
        # But no footer
        assert "[1] [memory] M1" not in text

    def test_no_footer_flag(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1", mode=InjectionMode.BOTH)
        inj.attach_source(ctx.turn_id, CitationSource.MEMORY, ref="m1", title="M1")
        text, _ = inj.inject(ctx.turn_id, "Hello world.", add_footer=False)
        assert "Hello world[1]." in text
        # No sources list (only inline marker)
        assert "[1] [memory] M1" not in text


# -- render_inline -----------------------------------------------------------


class TestRenderInline:
    def test_no_citations_passthrough(self):
        inj = CitationInjector()
        text, sources = inj.render_inline("Hello.", [])
        assert text == "Hello."
        assert sources == []

    def test_with_citations(self):
        inj = CitationInjector()
        cs = [
            Citation(source=CitationSource.MEMORY, ref="m1", title="M1"),
            Citation(source=CitationSource.WEB, ref="https://a.com", title="A.com"),
        ]
        text, sources = inj.render_inline("Fact A and B.", cs)
        assert "[1][2]" in text
        assert "[1] [memory] M1" in text
        assert "[2] [web] A.com" in text
        assert len(sources) == 2

    def test_no_footer(self):
        inj = CitationInjector()
        cs = [Citation(source=CitationSource.MEMORY, ref="m1", title="M1")]
        text, _ = inj.render_inline("Hello.", cs, add_footer=False)
        # Markers go before the final period
        assert "Hello[1]." in text
        assert "[1] [memory] M1" not in text

    def test_footer_only_mode(self):
        inj = CitationInjector()
        cs = [Citation(source=CitationSource.MEMORY, ref="m1", title="M1")]
        text, _ = inj.render_inline("Hello world.", cs, mode=InjectionMode.FOOTER)
        # No inline marker in the first part
        assert "[1]" not in text.split("\n\n")[0]
        # Footer present
        assert "[1] [memory] M1" in text


# -- manager + active turns -------------------------------------------------


class TestManagerAndActive:
    def test_manager_returns_injected(self):
        cm = CitationManager()
        inj = CitationInjector(manager=cm)
        assert inj.manager() is cm

    def test_default_manager(self):
        inj = CitationInjector()
        assert isinstance(inj.manager(), CitationManager)

    def test_active_turns(self):
        inj = CitationInjector()
        c1 = inj.begin_turn(user_id="u1", session_id="s1")
        c2 = inj.begin_turn(user_id="u2", session_id="s1")
        active = inj.active_turns()
        assert set(active) == {c1.turn_id, c2.turn_id}

    def test_active_turns_excludes_closed(self):
        inj = CitationInjector()
        c1 = inj.begin_turn(user_id="u1", session_id="s1")
        c2 = inj.begin_turn(user_id="u2", session_id="s1")
        inj.end_turn(c1.turn_id)
        active = inj.active_turns()
        assert active == [c2.turn_id]

    def test_all_turns(self):
        inj = CitationInjector()
        c1 = inj.begin_turn(user_id="u1", session_id="s1")
        inj.begin_turn(user_id="u2", session_id="s1")
        inj.end_turn(c1.turn_id)
        all_turns = inj.all_turns()
        assert len(all_turns) == 2
        user_ids = {ctx.user_id for ctx in all_turns}
        assert user_ids == {"u1", "u2"}


# -- clear -------------------------------------------------------------------


class TestClear:
    def test_clear_specific(self):
        inj = CitationInjector()
        c1 = inj.begin_turn(user_id="u1", session_id="s1")
        c2 = inj.begin_turn(user_id="u2", session_id="s1")
        assert inj.clear(c1.turn_id) == 1
        assert inj.get_context(c1.turn_id) is None
        assert inj.get_context(c2.turn_id) is not None

    def test_clear_unknown(self):
        inj = CitationInjector()
        assert inj.clear("nope") == 0

    def test_clear_all(self):
        inj = CitationInjector()
        inj.begin_turn(user_id="u1", session_id="s1")
        inj.begin_turn(user_id="u2", session_id="s1")
        assert inj.clear() == 2
        assert inj.all_turns() == []


# -- singletons --------------------------------------------------------------


class TestSingletons:
    def test_default_is_none_initially(self):
        reset_default_citation_injector()
        inj = get_default_citation_injector()
        assert isinstance(inj, CitationInjector)

    def test_set_replaces(self):
        custom = CitationInjector()
        set_default_citation_injector(custom)
        assert get_default_citation_injector() is custom

    def test_set_none_clears(self):
        set_default_citation_injector(None)
        # After reset, the singleton is rebuilt lazily — both calls
        # return the same fresh instance.
        new = get_default_citation_injector()
        assert new is get_default_citation_injector()

    def test_reset(self):
        inj = get_default_citation_injector()
        reset_default_citation_injector()
        # After reset, the singleton is rebuilt lazily
        assert get_default_citation_injector() is not inj


# -- integration with CitationManager ---------------------------------------


class TestIntegrationWithManager:
    def test_shared_manager_dedupes_across_turns(self):
        cm = CitationManager()
        inj = CitationInjector(manager=cm)
        c1 = inj.begin_turn(user_id="u1", session_id="s1")
        c2 = inj.begin_turn(user_id="u2", session_id="s1")
        # Same (source, ref) across turns → same Citation id
        a = inj.attach_source(c1.turn_id, CitationSource.MEMORY, ref="m1", title="M1")
        b = inj.attach_source(c2.turn_id, CitationSource.MEMORY, ref="m1", title="M1-v2")
        assert a.id == b.id
        # Manager merged title (first non-empty wins)
        assert b.title == "M1"

    def test_citations_isolated_per_context(self):
        inj = CitationInjector()
        c1 = inj.begin_turn(user_id="u1", session_id="s1")
        c2 = inj.begin_turn(user_id="u2", session_id="s1")
        inj.attach_source(c1.turn_id, CitationSource.MEMORY, ref="m1", title="M1")
        assert len(c1.citations) == 1
        assert len(c2.citations) == 0

    def test_full_workflow(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1")
        c1 = inj.attach_source(
            ctx.turn_id,
            CitationSource.MEMORY,
            ref="mem_42",
            title="User's Q2 OKR",
        )
        c2 = inj.attach_source(
            ctx.turn_id,
            CitationSource.WEB,
            ref="https://acme.com/q2",
            title="Acme Q2 results",
        )
        text, sources = inj.inject(
            ctx.turn_id,
            "Acme shipped 3 features and revenue is up 12%.",
        )
        # Inline markers
        assert "[1][2]" in text
        # Footer
        assert "[1] [memory] User's Q2 OKR" in text
        assert "[2] [web] Acme Q2 results" in text
        # Sources in marker order
        assert sources[0].id == c1.id
        assert sources[1].id == c2.id
        # Close
        inj.end_turn(ctx.turn_id)
        assert ctx.is_closed()


# -- threading ---------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_attach(self):
        inj = CitationInjector()
        ctx = inj.begin_turn(user_id="u1", session_id="s1")
        errors: list[Exception] = []

        def worker(i: int) -> None:
            try:
                for j in range(50):
                    inj.attach_source(
                        ctx.turn_id,
                        CitationSource.MEMORY,
                        ref=f"m-{i}-{j}",
                        title=f"Mem {i}/{j}",
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert len(ctx.citations) == 4 * 50


# -- format helpers re-exported ---------------------------------------------


def test_format_sources_list_integration():
    cs = [
        Citation(source=CitationSource.MEMORY, ref="m1", title="M1"),
        Citation(source=CitationSource.WEB, ref="https://a.com", title="A"),
    ]
    out = format_sources_list(cs)
    assert out == "[1] [memory] M1\n[2] [web] A"
