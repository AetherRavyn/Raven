"""Phase F1 — Trust & Explainability: Citation runtime injection.

Wires :mod:`app.core.trust.citations` into the agent's response
path.  The runtime gathers citations during a turn (memory
recall, tool results, web fetches, graph traversals) and the
injector renders them as inline ``[1]``/``[2]`` markers plus
an optional sources footer appended to the final response.

Design
------

A :class:`CitationContext` is created when a turn begins and
closed when it ends.  Every ``attach_source``/``attach_citation``
call during the turn is recorded on the context.  At turn end
the runtime calls :meth:`CitationInjector.inject` to add the
markers and footer to the final text.

The injector is opt-in via :attr:`CitationContext.auto_inject`:
when ``False``, citations are still recorded but the response
is returned unchanged.  This lets the runtime decide per
channel (markdown-capable channels get markers; plain-text
channels don't).

Typical usage::

    injector = get_default_citation_injector()
    ctx = injector.begin_turn(user_id="u1", session_id="s1")

    # During the turn, attach sources as they're encountered.
    c1 = injector.attach_source(
        ctx.turn_id, CitationSource.MEMORY,
        ref="mem_42", title="User's Q2 OKR",
    )
    c2 = injector.attach_source(
        ctx.turn_id, CitationSource.WEB,
        ref="https://acme.com/q2", title="Acme Q2 results",
    )

    # At turn end, inject markers + footer into the final text.
    final_text, sources = injector.inject(
        ctx.turn_id,
        "Acme shipped 3 features and revenue is up 12%.",
    )
    # final_text: "Acme shipped 3 features[1] and revenue is up 12%[2].\\n\\n[1] memory: ...\\n[2] web: ..."
    # sources: [c1, c2]

    injector.end_turn(ctx.turn_id)
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from app.core.trust.citations import (
    Citation,
    CitationManager,
    CitationSource,
    CitedFact,
    format_sources_list,
)


class InjectionMode(str, Enum):
    """How to render citations in the final response."""

    INLINE = "inline"  # inline [1][2] markers at end of text
    FOOTER = "footer"  # only append a sources footer, no inline markers
    BOTH = "both"  # inline markers + sources footer (default)
    NONE = "none"  # record only, do not modify the response


@dataclass(slots=True)
class CitationContext:
    """Per-turn state holding gathered citations."""

    turn_id: str
    user_id: str
    session_id: str
    citations: list[Citation] = field(default_factory=list)
    auto_inject: bool = True
    mode: InjectionMode = InjectionMode.BOTH
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def has_citations(self) -> bool:
        return bool(self.citations)

    def is_closed(self) -> bool:
        return self.ended_at is not None


class CitationInjector:
    """Orchestrates citation gathering + rendering for LLM responses.

    Thread-safe.  Holds a :class:`CitationManager` and a
    ``turn_id -> CitationContext`` map.
    """

    def __init__(
        self,
        manager: CitationManager | None = None,
        *,
        default_mode: InjectionMode = InjectionMode.BOTH,
    ) -> None:
        # Note: do NOT use `manager or CitationManager()` here —
        # CitationManager defines __len__ so an empty manager
        # is falsy and the fallback would always win.
        self._lock = threading.RLock()
        self._manager = manager if manager is not None else CitationManager()
        self._contexts: dict[str, CitationContext] = {}
        self._default_mode = default_mode

    # -- context lifecycle ---------------------------------------------

    def begin_turn(
        self,
        *,
        user_id: str,
        session_id: str,
        auto_inject: bool = True,
        mode: InjectionMode | None = None,
        turn_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CitationContext:
        """Open a new :class:`CitationContext` for a turn.

        Returns the new context.  Use :meth:`end_turn` to close it
        (or let it leak — contexts are bounded by the injector
        lifecycle and can be cleared with :meth:`clear`).
        """
        with self._lock:
            ctx = CitationContext(
                turn_id=turn_id or uuid.uuid4().hex,
                user_id=user_id,
                session_id=session_id,
                auto_inject=auto_inject,
                mode=mode or self._default_mode,
                metadata=dict(metadata or {}),
            )
            self._contexts[ctx.turn_id] = ctx
            return ctx

    def end_turn(self, turn_id: str) -> CitationContext | None:
        """Close a context and return it.  Returns ``None`` if unknown."""
        with self._lock:
            ctx = self._contexts.get(turn_id)
            if ctx is None:
                return None
            ctx.ended_at = datetime.now(timezone.utc)
            return ctx

    def get_context(self, turn_id: str) -> CitationContext | None:
        """Return the active context, or ``None`` if unknown."""
        with self._lock:
            return self._contexts.get(turn_id)

    def has_citations(self, turn_id: str) -> bool:
        ctx = self.get_context(turn_id)
        return ctx is not None and ctx.has_citations()

    # -- attachment ----------------------------------------------------

    def attach_source(
        self,
        turn_id: str,
        source: CitationSource | str,
        *,
        ref: str,
        title: str = "",
        snippet: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Citation | None:
        """Register a citation on the active turn's context.

        Returns the :class:`Citation` (new or deduplicated), or
        ``None`` if the turn_id is unknown.  Dedupes by
        ``(source, ref)`` *within the context* — the same source
        attached twice on the same turn is recorded once.
        """
        with self._lock:
            ctx = self._contexts.get(turn_id)
            if ctx is None:
                return None
            if isinstance(source, str):
                source_enum = CitationSource(source)
            else:
                source_enum = source
            # Dedupe within context first.
            for existing in ctx.citations:
                if existing.source == source_enum and existing.ref == ref:
                    return existing
            citation = self._manager.register(
                source,
                ref=ref,
                title=title,
                snippet=snippet,
                metadata=metadata,
            )
            ctx.citations.append(citation)
            return citation

    def attach_citation(self, turn_id: str, citation: Citation) -> bool:
        """Attach a pre-built :class:`Citation` to the active turn.

        Deduplicates by ``(source, ref)`` within the context.
        Returns ``True`` if added, ``False`` if unknown turn or
        already attached.
        """
        with self._lock:
            ctx = self._contexts.get(turn_id)
            if ctx is None:
                return False
            for existing in ctx.citations:
                if existing.source == citation.source and existing.ref == citation.ref:
                    return False
            ctx.citations.append(citation)
            return True

    def attach_citations(
        self,
        turn_id: str,
        citations: list[Citation],
    ) -> int:
        """Attach multiple citations.  Returns count of actually-added."""
        added = 0
        for c in citations:
            if self.attach_citation(turn_id, c):
                added += 1
        return added

    # -- rendering -----------------------------------------------------

    def inject(
        self,
        turn_id: str,
        text: str,
        *,
        citations: list[Citation] | None = None,
        add_footer: bool = True,
    ) -> tuple[str, list[Citation]]:
        """Render ``text`` with citations from the context.

        If ``citations`` is given, those are used (in order);
        otherwise the context's gathered citations are used.

        Returns ``(rendered_text, sources)`` where ``sources`` is
        the citation list in marker order.  If the turn has no
        citations and ``citations`` is not given, returns the
        original text unchanged with an empty list.
        """
        ctx = self.get_context(turn_id)
        if citations is None:
            citations = ctx.citations if ctx is not None else []
        if not citations:
            return text, []
        # Determine effective mode
        mode = ctx.mode if ctx is not None else self._default_mode
        auto = ctx.auto_inject if ctx is not None else True
        if not auto or mode == InjectionMode.NONE:
            return text, list(citations)
        # Build the rendered text per mode.
        if mode == InjectionMode.FOOTER:
            # Footer-only: no inline markers, just the sources list.
            rendered = text
            sources = list(citations)
        else:
            # INLINE or BOTH: render with inline markers.
            fact = self._manager.cite(text, citations=list(citations))
            rendered, sources = self._manager.render(fact)
        if add_footer and mode in (InjectionMode.FOOTER, InjectionMode.BOTH):
            footer = format_sources_list(sources)
            if footer:
                rendered = f"{rendered}\n\n{footer}"
        return rendered, sources

    def render_inline(
        self,
        text: str,
        citations: list[Citation],
        *,
        add_footer: bool = True,
        mode: InjectionMode = InjectionMode.BOTH,
    ) -> tuple[str, list[Citation]]:
        """Render ``text`` with the given citations (no context needed).

        Use this for ad-hoc rendering outside of a turn
        (e.g. proactive briefings, scheduled digests).  Pass
        ``mode=InjectionMode.FOOTER`` to suppress inline markers.
        """
        if not citations:
            return text, []
        if mode == InjectionMode.FOOTER:
            rendered = text
            sources = list(citations)
        else:
            fact = self._manager.cite(text, citations=list(citations))
            rendered, sources = self._manager.render(fact)
        if add_footer and mode in (InjectionMode.FOOTER, InjectionMode.BOTH):
            footer = format_sources_list(sources)
            if footer:
                rendered = f"{rendered}\n\n{footer}"
        return rendered, sources

    # -- lookup + stats ------------------------------------------------

    def manager(self) -> CitationManager:
        """Return the underlying :class:`CitationManager`."""
        return self._manager

    def active_turns(self) -> list[str]:
        """Return the turn_ids of all open contexts."""
        with self._lock:
            return [tid for tid, ctx in self._contexts.items() if not ctx.is_closed()]

    def all_turns(self) -> list[CitationContext]:
        """Return every context (open + closed)."""
        with self._lock:
            return list(self._contexts.values())

    def clear(self, turn_id: str | None = None) -> int:
        """Drop context(s).  Returns count cleared.  Tests use this."""
        with self._lock:
            if turn_id is None:
                count = len(self._contexts)
                self._contexts.clear()
                return count
            return 1 if self._contexts.pop(turn_id, None) is not None else 0


# -- module-level singleton helpers ------------------------------------------


_DEFAULT_INJECTOR: CitationInjector | None = None
_LOCK = threading.RLock()


def get_default_citation_injector() -> CitationInjector:
    """Return the process-singleton :class:`CitationInjector`."""
    global _DEFAULT_INJECTOR
    with _LOCK:
        if _DEFAULT_INJECTOR is None:
            _DEFAULT_INJECTOR = CitationInjector()
        return _DEFAULT_INJECTOR


def set_default_citation_injector(injector: CitationInjector | None) -> None:
    """Replace the singleton.  Pass ``None`` to clear."""
    global _DEFAULT_INJECTOR
    with _LOCK:
        _DEFAULT_INJECTOR = injector


def reset_default_citation_injector() -> None:
    """Drop the singleton.  Tests use this between cases."""
    global _DEFAULT_INJECTOR
    with _LOCK:
        _DEFAULT_INJECTOR = None


__all__ = [
    "CitationContext",
    "CitationInjector",
    "InjectionMode",
    "get_default_citation_injector",
    "reset_default_citation_injector",
    "set_default_citation_injector",
]


# Re-export for callers — keeps `from app.core.trust.citation_runtime import X` clean.
_ = (Citation, CitationManager, CitationSource, CitedFact)
