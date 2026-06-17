"""Phase F1 — Trust & Explainability: Citations.

Every fact the agent states is traceable to a :class:`CitationSource`.
This module provides the data model and a small renderer that
inserts inline markers like ``[1]`` / ``[2]`` and appends a
sources list.

Design goals
------------

* **Lightweight** — a citation is just a dataclass with a source
  kind, a reference (URL / path / id), a title, and a snippet.
  No external dependencies.
* **Composable** — the runtime can attach a citation to a fact
  at any point (memory recall, tool result, web fetch, graph
  traversal, user input, LLM inference).
* **Deterministic** — the same set of citations always renders
  to the same numbered text.  The renderer deduplicates by
  ``(source, ref)``.

Typical usage::

    cm = CitationManager()
    c1 = cm.register(
        CitationSource.MEMORY, ref="mem_42",
        title="User's Q2 OKR", snippet="ship 3 features",
    )
    c2 = cm.register(
        CitationSource.WEB, ref="https://acme.com/q2",
        title="Acme Q2 results", snippet="revenue up 12%",
    )
    fact = cm.cite(
        "Acme shipped 3 features and revenue is up 12%.",
        citations=[c1, c2],
    )
    text, sources = cm.render(fact)
    # text: "Acme shipped 3 features[1] and revenue is up 12%[2]."
    # sources: [[1] memory:mem_42, [2] web:https://acme.com/q2]
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class CitationSource(str, Enum):
    """Where a fact came from.  The string value is the on-wire form."""

    MEMORY = "memory"
    FILE = "file"
    WEB = "web"
    TOOL = "tool"
    GRAPH = "graph"
    USER = "user"
    INFERENCE = "inference"


@dataclass(slots=True, frozen=True)
class Citation:
    """A single source backing a fact.

    ``ref`` is the stable identifier for the source: a memory id,
    a file path, a URL, a tool call id, a graph node id, or
    "user" for explicit user input.  ``title`` and ``snippet``
    are shown when the user hovers or taps a citation marker.
    """

    source: CitationSource
    ref: str
    title: str = ""
    snippet: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    metadata: dict[str, Any] = field(default_factory=dict)

    def short(self) -> str:
        """One-line description for the sources list."""
        title = self.title or self.ref
        return f"[{self.source.value}] {title}"

    def __post_init__(self) -> None:
        # Normalise source to enum (accepts string for callers).
        if isinstance(self.source, str):
            object.__setattr__(self, "source", CitationSource(self.source))


@dataclass(slots=True)
class CitedFact:
    """A piece of text with attached :class:`Citation` objects."""

    text: str
    citations: list[Citation] = field(default_factory=list)
    fact_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def add(self, citation: Citation) -> None:
        """Append a citation, deduplicating by ``(source, ref)``."""
        for existing in self.citations:
            if existing.source == citation.source and existing.ref == citation.ref:
                return
        self.citations.append(citation)


class CitationManager:
    """Process-level facade for citations.

    Holds a registry of every citation the runtime has ever
    produced, keyed by :attr:`Citation.id`.  This lets the
    dashboard look up "what was citation [3]?" without
    re-parsing the rendered text.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._registry: dict[str, Citation] = {}
        self._by_ref: dict[tuple[CitationSource, str], str] = {}

    # -- registration ----------------------------------------------------

    def register(
        self,
        source: CitationSource | str,
        *,
        ref: str,
        title: str = "",
        snippet: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Citation:
        """Create and register a :class:`Citation`.

        If a citation with the same ``(source, ref)`` already
        exists, the existing one is returned (deduplication).
        """
        if isinstance(source, str):
            source = CitationSource(source)
        with self._lock:
            key = (source, ref)
            if key in self._by_ref:
                existing_id = self._by_ref[key]
                existing = self._registry[existing_id]
                # Merge: keep the first non-empty title/snippet.
                if title and not existing.title:
                    object.__setattr__(existing, "title", title)
                if snippet and not existing.snippet:
                    object.__setattr__(existing, "snippet", snippet)
                if metadata:
                    merged = dict(existing.metadata)
                    merged.update(metadata)
                    object.__setattr__(existing, "metadata", merged)
                return existing
            citation = Citation(
                source=source,
                ref=ref,
                title=title,
                snippet=snippet,
                metadata=dict(metadata or {}),
            )
            self._registry[citation.id] = citation
            self._by_ref[key] = citation.id
            return citation

    # -- citation building ----------------------------------------------

    def cite(
        self,
        text: str,
        *,
        citations: list[Citation] | None = None,
    ) -> CitedFact:
        """Wrap ``text`` in a :class:`CitedFact` with the given citations.

        The citations are deduplicated within the fact by
        ``(source, ref)``.  This does NOT auto-detect which
        citation applies to which phrase — the runtime attaches
        them semantically.
        """
        fact = CitedFact(text=text, citations=[])
        if citations:
            for c in citations:
                fact.add(c)
        return fact

    def cite_one(
        self,
        text: str,
        source: CitationSource | str,
        *,
        ref: str,
        title: str = "",
        snippet: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> CitedFact:
        """Convenience: register a citation and wrap ``text`` in one shot."""
        citation = self.register(
            source, ref=ref, title=title, snippet=snippet, metadata=metadata,
        )
        return self.cite(text, citations=[citation])

    # -- rendering ------------------------------------------------------

    def render(self, fact: CitedFact) -> tuple[str, list[Citation]]:
        """Render a :class:`CitedFact` as ``(text, sources)``.

        ``text`` is the original text with ``[1]``, ``[2]``, …
        markers appended at the end.  The markers are placed at
        end-of-sentence (before the final period) when possible,
        otherwise at end-of-text.  The sources list is in
        marker order.
        """
        if not fact.citations:
            return fact.text, []
        # Number citations in the order they appear in the list.
        # This is the order the runtime attached them, which is
        # the order the LLM or planner encountered them.
        indexed: list[tuple[int, Citation]] = list(enumerate(fact.citations, start=1))
        # Build marker string.
        markers = "".join(f"[{n}]" for n, _ in indexed)
        text = self._attach_markers(fact.text, markers)
        sources = [c for _, c in indexed]
        return text, sources

    @staticmethod
    def _attach_markers(text: str, markers: str) -> str:
        """Append ``markers`` to ``text`` before the final period.

        If the text already ends with a period, insert before it.
        If the text ends with a non-alphanumeric char (like ``!``
        or ``?``), insert before it.  Otherwise append at the end.
        """
        if not markers:
            return text
        if not text:
            return markers
        if text[-1] in ".!?":
            return text[:-1] + markers + text[-1]
        return text + markers

    # -- lookup ---------------------------------------------------------

    def get(self, citation_id: str) -> Citation | None:
        """Look up a citation by its :attr:`Citation.id`."""
        with self._lock:
            return self._registry.get(citation_id)

    def find(self, source: CitationSource | str, ref: str) -> Citation | None:
        """Look up a citation by ``(source, ref)``."""
        if isinstance(source, str):
            source = CitationSource(source)
        with self._lock:
            cid = self._by_ref.get((source, ref))
            if cid is None:
                return None
            return self._registry.get(cid)

    def all(self) -> list[Citation]:
        """Return every registered citation (newest last)."""
        with self._lock:
            return list(self._registry.values())

    def __len__(self) -> int:
        with self._lock:
            return len(self._registry)

    def reset(self) -> None:
        """Drop every registered citation.  Tests only."""
        with self._lock:
            self._registry.clear()
            self._by_ref.clear()


# -- format helpers ----------------------------------------------------------


def format_sources_list(sources: list[Citation]) -> str:
    """Render a numbered sources list for display.

    Example output::

        [1] memory: User's Q2 OKR
        [2] web: Acme Q2 results
    """
    lines = []
    for i, c in enumerate(sources, start=1):
        lines.append(f"[{i}] {c.short()}")
    return "\n".join(lines)


# -- module-level singleton helpers ------------------------------------------


_DEFAULT_MANAGER: CitationManager | None = None
_LOCK = threading.RLock()


def get_default_citation_manager() -> CitationManager:
    """Return the process-singleton :class:`CitationManager`."""
    global _DEFAULT_MANAGER
    with _LOCK:
        if _DEFAULT_MANAGER is None:
            _DEFAULT_MANAGER = CitationManager()
        return _DEFAULT_MANAGER


def set_default_citation_manager(manager: CitationManager | None) -> None:
    """Replace the singleton.  Pass ``None`` to clear."""
    global _DEFAULT_MANAGER
    with _LOCK:
        _DEFAULT_MANAGER = manager


def reset_default_citation_manager() -> None:
    """Drop the singleton.  Tests use this between cases."""
    global _DEFAULT_MANAGER
    with _LOCK:
        _DEFAULT_MANAGER = None


__all__ = [
    "Citation",
    "CitationManager",
    "CitationSource",
    "CitedFact",
    "format_sources_list",
    "get_default_citation_manager",
    "reset_default_citation_manager",
    "set_default_citation_manager",
]
