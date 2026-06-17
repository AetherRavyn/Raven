"""Tests for app.core.trust.citations (Day 26)."""

from __future__ import annotations

import pytest

from app.core.trust.citations import (
    Citation,
    CitationManager,
    CitationSource,
    CitedFact,
    format_sources_list,
    get_default_citation_manager,
    reset_default_citation_manager,
    set_default_citation_manager,
)


# --------------------------------------------------------------------------- #
# Fakes / fixtures                                                            #
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    reset_default_citation_manager()
    yield
    reset_default_citation_manager()


@pytest.fixture
def cm() -> CitationManager:
    return CitationManager()


# --------------------------------------------------------------------------- #
# Citation dataclass                                                           #
# --------------------------------------------------------------------------- #


class TestCitation:
    def test_creation_with_enum(self) -> None:
        c = Citation(source=CitationSource.MEMORY, ref="mem_1")
        assert c.source is CitationSource.MEMORY
        assert c.ref == "mem_1"
        assert c.title == ""
        assert c.snippet == ""

    def test_creation_with_string_source(self) -> None:
        c = Citation(source="web", ref="https://x.com")
        assert c.source is CitationSource.WEB

    def test_short_includes_source_and_title(self) -> None:
        c = Citation(source=CitationSource.TOOL, ref="t1", title="My Tool")
        assert "[tool]" in c.short()
        assert "My Tool" in c.short()

    def test_short_falls_back_to_ref(self) -> None:
        c = Citation(source=CitationSource.FILE, ref="/etc/hosts")
        assert "/etc/hosts" in c.short()

    def test_default_metadata_is_empty(self) -> None:
        c = Citation(source=CitationSource.USER, ref="u1")
        assert c.metadata == {}

    def test_frozen_rejects_mutation(self) -> None:
        c = Citation(source=CitationSource.MEMORY, ref="m")
        with pytest.raises((AttributeError, Exception)):
            c.ref = "other"  # type: ignore[misc]

    def test_invalid_source_string_raises(self) -> None:
        with pytest.raises(ValueError):
            Citation(source="not-a-source", ref="x")


# --------------------------------------------------------------------------- #
# CitedFact                                                                   #
# --------------------------------------------------------------------------- #


class TestCitedFact:
    def test_add_appends(self) -> None:
        fact = CitedFact(text="hello")
        c = Citation(source=CitationSource.MEMORY, ref="m")
        fact.add(c)
        assert len(fact.citations) == 1

    def test_add_dedupes_by_source_ref(self) -> None:
        fact = CitedFact(text="hello")
        c1 = Citation(source=CitationSource.MEMORY, ref="m")
        c2 = Citation(source=CitationSource.MEMORY, ref="m")
        fact.add(c1)
        fact.add(c2)
        assert len(fact.citations) == 1

    def test_dedup_keeps_first_added(self) -> None:
        fact = CitedFact(text="hello")
        c1 = Citation(source=CitationSource.MEMORY, ref="m", title="first")
        c2 = Citation(source=CitationSource.MEMORY, ref="m", title="second")
        fact.add(c1)
        fact.add(c2)
        assert fact.citations[0].title == "first"


# --------------------------------------------------------------------------- #
# CitationManager.register                                                    #
# --------------------------------------------------------------------------- #


class TestRegister:
    def test_register_creates_citation(self, cm: CitationManager) -> None:
        c = cm.register(CitationSource.MEMORY, ref="m1", title="T")
        assert c.source is CitationSource.MEMORY
        assert c.ref == "m1"
        assert c.title == "T"
        assert len(cm) == 1

    def test_register_dedupes_by_source_ref(self, cm: CitationManager) -> None:
        c1 = cm.register(CitationSource.MEMORY, ref="m1", title="first")
        c2 = cm.register(CitationSource.MEMORY, ref="m1", title="second")
        assert c1.id == c2.id
        assert c1.title == "first"  # first non-empty wins
        assert len(cm) == 1

    def test_register_merges_snippet(self, cm: CitationManager) -> None:
        c1 = cm.register(CitationSource.WEB, ref="u1", snippet="")
        c2 = cm.register(CitationSource.WEB, ref="u1", snippet="text")
        assert c1 is c2
        assert c1.snippet == "text"

    def test_register_merges_metadata(self, cm: CitationManager) -> None:
        c1 = cm.register(CitationSource.MEMORY, ref="m", metadata={"a": 1})
        c2 = cm.register(CitationSource.MEMORY, ref="m", metadata={"b": 2})
        assert c1 is c2
        assert c1.metadata == {"a": 1, "b": 2}

    def test_register_accepts_string_source(self, cm: CitationManager) -> None:
        c = cm.register("file", ref="/x")
        assert c.source is CitationSource.FILE


# --------------------------------------------------------------------------- #
# CitationManager.cite                                                        #
# --------------------------------------------------------------------------- #


class TestCite:
    def test_cite_with_no_citations(self, cm: CitationManager) -> None:
        fact = cm.cite("plain text")
        assert fact.text == "plain text"
        assert fact.citations == []

    def test_cite_with_citations(self, cm: CitationManager) -> None:
        c1 = cm.register(CitationSource.MEMORY, ref="m1")
        c2 = cm.register(CitationSource.WEB, ref="u1")
        fact = cm.cite("hello world", citations=[c1, c2])
        assert len(fact.citations) == 2

    def test_cite_dedupes(self, cm: CitationManager) -> None:
        c1 = cm.register(CitationSource.MEMORY, ref="m1")
        fact = cm.cite("hello", citations=[c1, c1])
        assert len(fact.citations) == 1

    def test_cite_one_convenience(self, cm: CitationManager) -> None:
        fact = cm.cite_one("hello", CitationSource.MEMORY, ref="m1")
        assert len(fact.citations) == 1
        assert fact.citations[0].ref == "m1"


# --------------------------------------------------------------------------- #
# CitationManager.render                                                      #
# --------------------------------------------------------------------------- #


class TestRender:
    def test_render_no_citations(self, cm: CitationManager) -> None:
        fact = cm.cite("hello")
        text, sources = cm.render(fact)
        assert text == "hello"
        assert sources == []

    def test_render_appends_markers_before_period(self, cm: CitationManager) -> None:
        c1 = cm.register(CitationSource.MEMORY, ref="m1")
        c2 = cm.register(CitationSource.WEB, ref="u1")
        fact = cm.cite("The sky is blue.", citations=[c1, c2])
        text, sources = cm.render(fact)
        assert text == "The sky is blue[1][2]."
        assert len(sources) == 2

    def test_render_single_marker(self, cm: CitationManager) -> None:
        c = cm.register(CitationSource.MEMORY, ref="m1")
        fact = cm.cite("Done.", citations=[c])
        text, _ = cm.render(fact)
        assert text == "Done[1]."

    def test_render_no_period(self, cm: CitationManager) -> None:
        c = cm.register(CitationSource.MEMORY, ref="m1")
        fact = cm.cite("hello", citations=[c])
        text, _ = cm.render(fact)
        assert text == "hello[1]"

    def test_render_exclamation(self, cm: CitationManager) -> None:
        c = cm.register(CitationSource.MEMORY, ref="m1")
        fact = cm.cite("Watch out!", citations=[c])
        text, _ = cm.render(fact)
        assert text == "Watch out[1]!"

    def test_render_returns_in_order(self, cm: CitationManager) -> None:
        c1 = cm.register(CitationSource.MEMORY, ref="m1", title="M")
        c2 = cm.register(CitationSource.WEB, ref="u1", title="U")
        c3 = cm.register(CitationSource.TOOL, ref="t1", title="T")
        fact = cm.cite("x", citations=[c1, c2, c3])
        _, sources = cm.render(fact)
        assert sources[0] is c1
        assert sources[1] is c2
        assert sources[2] is c3


# --------------------------------------------------------------------------- #
# Lookup                                                                      #
# --------------------------------------------------------------------------- #


class TestLookup:
    def test_get_by_id(self, cm: CitationManager) -> None:
        c = cm.register(CitationSource.MEMORY, ref="m1")
        assert cm.get(c.id) is c

    def test_get_missing_returns_none(self, cm: CitationManager) -> None:
        assert cm.get("nope") is None

    def test_find_by_source_ref(self, cm: CitationManager) -> None:
        c = cm.register(CitationSource.WEB, ref="https://x")
        assert cm.find(CitationSource.WEB, "https://x") is c

    def test_find_missing_returns_none(self, cm: CitationManager) -> None:
        assert cm.find(CitationSource.WEB, "missing") is None

    def test_all_returns_all(self, cm: CitationManager) -> None:
        cm.register(CitationSource.MEMORY, ref="m1")
        cm.register(CitationSource.WEB, ref="u1")
        assert len(cm.all()) == 2

    def test_reset_clears(self, cm: CitationManager) -> None:
        cm.register(CitationSource.MEMORY, ref="m1")
        cm.reset()
        assert len(cm) == 0


# --------------------------------------------------------------------------- #
# format_sources_list                                                         #
# --------------------------------------------------------------------------- #


class TestFormatSourcesList:
    def test_empty(self) -> None:
        assert format_sources_list([]) == ""

    def test_single(self) -> None:
        c = Citation(source=CitationSource.MEMORY, ref="m", title="M")
        out = format_sources_list([c])
        assert "[1]" in out
        assert "[memory]" in out
        assert "M" in out

    def test_multiple_lines(self) -> None:
        c1 = Citation(source=CitationSource.MEMORY, ref="m", title="M")
        c2 = Citation(source=CitationSource.WEB, ref="u", title="U")
        out = format_sources_list([c1, c2])
        lines = out.split("\n")
        assert len(lines) == 2
        assert lines[0].startswith("[1]")
        assert lines[1].startswith("[2]")


# --------------------------------------------------------------------------- #
# Singleton helpers                                                           #
# --------------------------------------------------------------------------- #


class TestSingleton:
    def test_get_default_creates_singleton(self) -> None:
        m1 = get_default_citation_manager()
        m2 = get_default_citation_manager()
        assert m1 is m2

    def test_set_replaces(self) -> None:
        custom = CitationManager()
        set_default_citation_manager(custom)
        try:
            assert get_default_citation_manager() is custom
        finally:
            set_default_citation_manager(None)
        assert get_default_citation_manager() is not custom

    def test_reset_clears(self) -> None:
        get_default_citation_manager()
        reset_default_citation_manager()
        # New instance after reset.
        m1 = get_default_citation_manager()
        assert len(m1) == 0
