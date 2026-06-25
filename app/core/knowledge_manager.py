"""Knowledge Manager — Phase 4 (v9) — structured facade over the KG.

A synchronous, ergonomic wrapper around the underlying
:class:`app.tools.kgtool.KnowledgeGraphTool` (HelixDB-backed).
The manager is the user-facing surface for
**structured** knowledge writes:

* ``record_fact(subject, predicate, object)`` — write one triple
* ``record_facts([...])`` — batch write
* ``query(name)`` — return all facts about an entity
* ``find_path(a, b)`` — BFS path between two entities
* ``sync_from_life_context(user_id)`` — pull active projects,
  current project, preferences, display name from
  :class:`LifeContextEngine` and write them as typed triples

The existing ``KnowledgeGraphPopulator`` (LLM-based entity
extraction from conversation text) handles the **unstructured**
side; ``KnowledgeManager`` handles the **structured** side.
Both share the same underlying KG tool.

JSONL fallback
--------------

The HelixDB backend is a heavy dependency that may
not be available in tests, dev environments, or single-user
deployments.  When the underlying ``KnowledgeGraphTool`` is
unavailable (raises on construction or write), the manager
falls back to a per-workspace JSONL file.  This keeps the
API surface stable across environments — a test that writes
``"Swadhin owns AetherRavyn"`` can assert the triple is
retrievable without spinning up a database.  The fallback
file format is one JSON object per line:

    {"s": "Swadhin", "p": "owns", "o": "AetherRavyn",
     "ts": "2026-06-20T10:00:00Z", "src": "user"}

The ``src`` field tags the provenance — ``"user"`` for
explicit ``record_fact`` calls, ``"life_context"`` for the
ambient-loop sync, ``"slash"`` for ``/kg add`` commands.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ── Event-loop bridge (v33) ──────────────────────────────────────────
#
# The KG tool's :meth:`execute` is an ``async`` coroutine.  The
# manager's public API is **synchronous** (slash commands, the
# ambient-loop tick, and ``record_facts`` callers all want a
# blocking return value).  Naïvely calling ``asyncio.run(coro)``
# works from the test suite (which has no running loop) but
# **crashes** when called from inside the orchestrator's
# async event loop with::
#
#     RuntimeError: asyncio.run() cannot be called from a
#     running event loop
#
# The bridge detects whether a loop is already running:
# - **No loop** → safe to use ``asyncio.run`` directly.
# - **Loop running** → run the coroutine in a dedicated worker
#   thread that owns its own loop.  We do *not* use
#   ``run_until_complete`` on the live loop because the caller
#   (the orchestrator) is itself awaiting a coroutine and
#   nesting ``run_until_complete`` would deadlock the loop.


def _run_coro(coro: Any) -> Any:
    """Run *coro* to completion, working both inside and outside
    an existing asyncio event loop.

    Returns the coroutine's return value.  Raises whatever the
    coroutine raises (the caller's ``try/except`` is responsible
    for turning KG failures into a JSONL fallback).
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — the cheap path.
        return asyncio.run(coro)
    # Running loop — delegate to a worker thread.
    import threading

    holder: dict[str, Any] = {}

    def _worker() -> None:
        try:
            holder["result"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001
            holder["error"] = exc
        finally:
            holder["done"] = True

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join()
    if holder.get("error") is not None:
        raise holder["error"]
    return holder.get("result")


# ── Result dataclass ─────────────────────────────────────────────────


@dataclass(slots=True)
class Fact:
    """A single (subject, predicate, object) triple.

    Returned by :meth:`KnowledgeManager.query` and accepted by
    :meth:`KnowledgeManager.record_facts` for batch writes.
    """

    subject: str
    predicate: str
    object: str
    source: str = "user"
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )

    def to_dict(self) -> dict[str, str]:
        return {
            "s": self.subject,
            "p": self.predicate,
            "o": self.object,
            "src": self.source,
            "ts": self.timestamp,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Fact":
        return cls(
            subject=str(raw.get("s", "")).strip(),
            predicate=str(raw.get("p", "")).strip(),
            object=str(raw.get("o", "")).strip(),
            source=str(raw.get("src", "user")),
            timestamp=str(raw.get("ts", "")),
        )

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.subject.lower(), self.predicate.lower(), self.object.lower())


# ── Manager ──────────────────────────────────────────────────────────


class KnowledgeManager:
    """Synchronous facade over the knowledge graph.

    The class is **synchronous by design**: most callers
    (ambient-loop tick, slash commands, batch sync) don't want
    to await every write.  The underlying KG tool is async; the
    manager wraps it but exposes a sync API.  The JSONL fallback
    is fully sync.

    Write paths are **fail-silent** (logged at WARNING) so an
    unreachable backend never crashes the orchestrator or the
    ambient loop.  Read paths return whatever the JSONL fallback
    has when the backend is unavailable.
    """

    def __init__(
        self,
        *,
        workspace_dir: str | None = None,
        kg_tool: Any = None,
        jsonl_fallback_path: str | Path | None = None,
    ) -> None:
        from app.settings.config import Config

        self._workspace_dir = Path(
            workspace_dir or os.environ.get("RAVEN_MEMORY_ROOT") or Config.MEMORY_ROOT
        )
        self._fallback_path = Path(
            jsonl_fallback_path
            if jsonl_fallback_path is not None
            else (self._workspace_dir / "knowledge_graph.jsonl")
        )
        self._fallback_path.parent.mkdir(parents=True, exist_ok=True)
        self._kg_tool = kg_tool  # None → lazy load + JSONL fallback
        self._backend: str = "jsonl"  # or "helix"
        self._recent_writes: list[Fact] = []
        self._fallback_cache: list[Fact] | None = None  # lazy-loaded JSONL cache
        self._fallback_cache_dirty = True

    # ── Backend management ──────────────────────────────────────

    def _get_kg_tool(self) -> Any | None:
        """Lazy-load the KG tool.  Returns ``None`` on any failure
        so the manager falls back to JSONL silently."""
        if self._kg_tool is not None:
            return self._kg_tool
        try:
            from app.tools.kgtool import KnowledgeGraphTool

            tool = KnowledgeGraphTool()
            self._kg_tool = tool
            self._backend = "helix"
            return tool
        except Exception as exc:
            logger.debug(
                "KnowledgeManager: KG tool unavailable, JSONL fallback — %s", exc,
            )
            self._kg_tool = False  # sentinel: tried, failed
            return None

    @property
    def backend(self) -> str:
        """The active backend name (``"jsonl"``, ``"helix"``,
        ``"neo4j"``).  Used by tests and the audit log."""
        return self._backend

    # ── Write API ───────────────────────────────────────────────

    def record_fact(
        self,
        subject: str,
        predicate: str,
        object: str,
        *,
        source: str = "user",
    ) -> Fact | None:
        """Write a single triple.  Returns the :class:`Fact` if
        it was new, or ``None`` if the triple already existed
        (idempotent).  Failures are logged and swallowed."""
        fact = Fact(
            subject=subject.strip(),
            predicate=predicate.strip().lower(),
            object=object.strip(),
            source=source,
        )
        if not fact.subject or not fact.predicate or not fact.object:
            logger.warning(
                "KnowledgeManager.record_fact: empty triple rejected — %r",
                fact,
            )
            return None

        # JSONL is the source of truth in fallback mode; if the
        # backend succeeds, we don't double-write.
        if self._exists_in_fallback(fact):
            return None

        tool = self._get_kg_tool()
        if tool is not None:
            coro = tool.execute(
                operation="add_relationship",
                entity1=fact.subject,
                relation=fact.predicate,
                entity2=fact.object,
            )
            try:
                res = _run_coro(coro)
            except Exception as exc:
                logger.warning(
                    "KnowledgeManager.record_fact: KG write failed (%s) — %s",
                    fact.key, exc,
                )
            else:
                if res and res.get("success"):
                    self._backend = "helix"
                    self._recent_writes.append(fact)
                    return fact

        # JSONL fallback path (also used when KG write failed).
        self._append_fallback(fact)
        self._recent_writes.append(fact)
        return fact

    def record_facts(
        self, facts: Iterable[tuple[str, str, str] | Fact], *, source: str = "user"
    ) -> int:
        """Batch write.  Returns the number of NEW triples added."""
        added = 0
        for entry in facts:
            if isinstance(entry, Fact):
                result = self.record_fact(
                    entry.subject, entry.predicate, entry.object,
                    source=entry.source or source,
                )
            else:
                s, p, o = entry
                result = self.record_fact(s, p, o, source=source)
            if result is not None:
                added += 1
        return added

    # ── Read API ────────────────────────────────────────────────

    def query(self, name: str) -> list[Fact]:
        """Return all facts whose subject equals ``name``.

        Reads from the JSONL fallback when the backend is
        unavailable, so the test surface is consistent across
        environments.
        """
        tool = self._get_kg_tool()
        if tool is not None:
            coro = tool.execute(operation="query_entity", entity1=name)
            try:
                res = _run_coro(coro)
            except Exception as exc:
                logger.debug("KnowledgeManager.query: KG read failed — %s", exc)
                return self._query_fallback(name)
            if res and res.get("success"):
                connections = res.get("connections") or []
                out: list[Fact] = []
                for c in connections:
                    # c is like "[name] --(relation)--> [target]"
                    fact = _parse_kg_connection_line(name, c)
                    if fact is not None:
                        out.append(fact)
                if out:
                    return out
                # Backend returned empty → check JSONL too
                # (mixed source environment).
        return self._query_fallback(name)

    def find_path(self, a: str, b: str, *, max_hops: int = 4) -> list[str] | None:
        """Return the entity path from ``a`` to ``b``, or
        ``None`` if no path exists within ``max_hops``."""
        tool = self._get_kg_tool()
        if tool is not None:
            coro = tool.execute(
                operation="find_path",
                entity1=a,
                entity2=b,
                max_hops=max_hops,
            )
            try:
                res = _run_coro(coro)
            except Exception as exc:
                logger.debug("KnowledgeManager.find_path: KG failed — %s", exc)
                return self._find_path_fallback(a, b, max_hops=max_hops)
            if res and res.get("success") and res.get("path"):
                return list(res["path"])
        return self._find_path_fallback(a, b, max_hops=max_hops)

    # ── Bulk sync from life context ────────────────────────────

    def sync_from_life_context(self, user_id: str = "default") -> int:
        """Pull typed fields from :class:`LifeContextEngine` and
        write them as triples.

        Returns the number of NEW triples added.  The same call
        repeated is idempotent: a second call with unchanged
        life context adds zero triples.

        Mapping:
          * ``display_name`` → ``<name> HAS_NAME <display_name>``
          * ``current_project`` → ``<user_id> WORKS_ON <project>``
          * each ``active_projects[i]`` →
            ``<user_id> ACTIVE_ON <project>``
          * each ``preferences[i]`` →
            ``<user_id> PREFERS <preference>``
        """
        try:
            from app.core.life_context import get_life_context_engine
        except Exception as exc:
            logger.debug(
                "KnowledgeManager.sync: LifeContext unavailable — %s", exc,
            )
            return 0
        try:
            engine = get_life_context_engine()
            ctx = engine.get_context(user_id)
        except Exception as exc:
            logger.debug(
                "KnowledgeManager.sync: get_context failed — %s", exc,
            )
            return 0
        if ctx is None:
            return 0

        triples: list[tuple[str, str, str]] = []
        if getattr(ctx, "display_name", None):
            triples.append((ctx.display_name, "has_name", ctx.display_name))
        if getattr(ctx, "current_project", None):
            triples.append((user_id, "works_on", ctx.current_project))
        for project in getattr(ctx, "active_projects", []) or []:
            triples.append((user_id, "active_on", project))
        for pref in getattr(ctx, "preferences", []) or []:
            triples.append((user_id, "prefers", pref))

        return self.record_facts(triples, source="life_context")

    # ── Recent writes (audit seam) ──────────────────────────────

    def drain_recent_writes(self) -> list[Fact]:
        """Return and clear the recent-writes list.  Used by the
        ambient-loop tick to surface writes for the audit log
        without accumulating state across ticks."""
        out = list(self._recent_writes)
        self._recent_writes.clear()
        return out

    # ── JSONL fallback helpers ──────────────────────────────────

    def _load_fallback_cache(self) -> list[Fact]:
        """Load JSONL into memory cache. Only re-reads if dirty."""
        if self._fallback_cache is not None and not self._fallback_cache_dirty:
            return self._fallback_cache
        facts: list[Fact] = []
        if self._fallback_path.exists():
            try:
                for raw in self._fallback_path.read_text(encoding="utf-8").splitlines():
                    if not raw.strip():
                        continue
                    facts.append(Fact.from_dict(json.loads(raw)))
            except Exception:
                pass
        self._fallback_cache = facts
        self._fallback_cache_dirty = False
        return facts

    def _exists_in_fallback(self, fact: Fact) -> bool:
        facts = self._load_fallback_cache()
        return any(f.key == fact.key for f in facts)

    def _append_fallback(self, fact: Fact) -> None:
        try:
            with self._fallback_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(fact.to_dict(), ensure_ascii=False) + "\n")
            self._fallback_cache_dirty = True  # invalidate cache
            if self._backend != "jsonl":
                self._backend = "jsonl"
        except Exception as exc:
            logger.warning(
                "KnowledgeManager: JSONL append failed — %s", exc,
            )

    def _query_fallback(self, name: str) -> list[Fact]:
        target = name.strip().lower()
        facts = self._load_fallback_cache()
        return [f for f in facts if f.subject.lower() == target]

    def _find_path_fallback(
        self, a: str, b: str, *, max_hops: int
    ) -> list[str] | None:
        """BFS over the JSONL-derived edge graph. Returns the
        node sequence or None if no path exists."""
        if a == b:
            return [a]
        # Build adjacency from cache.
        adj: dict[str, list[str]] = {}
        facts = self._load_fallback_cache()
        for f in facts:
            adj.setdefault(f.subject, []).append(f.object)

        from collections import deque

        visited: set[str] = {a}
        queue: deque[list[str]] = deque([[a]])
        while queue:
            path = queue.popleft()
            if len(path) > max_hops + 1:
                continue
            current = path[-1]
            for nxt in adj.get(current, []):
                if nxt == b:
                    return path + [nxt]
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append(path + [nxt])
        return None


# ── Helpers ──────────────────────────────────────────────────────────


def _parse_kg_connection_line(entity: str, line: str) -> Fact | None:
    """Parse a line like ``"[Swadhin] --(owns)--> [AetherRavyn]"``
    into a :class:`Fact`.  Returns ``None`` for sentinel lines
    (``"No connections found in the graph."``)."""
    if not isinstance(line, str):
        return None
    sentinel = "no connections"
    if sentinel in line.lower():
        return None
    # Strip leading "[name] --(" and trailing "--> [target]"
    try:
        rest = line.split("--(", 1)[1]
        predicate, target_part = rest.split(")-->", 1)
        target = target_part.strip().strip("[]").strip()
        return Fact(subject=entity, predicate=predicate.strip(), object=target)
    except (IndexError, ValueError):
        return None


# ── Singleton ────────────────────────────────────────────────────────


_knowledge_manager: KnowledgeManager | None = None


def get_knowledge_manager() -> KnowledgeManager:
    """Return the process-wide :class:`KnowledgeManager`.

    Lazy-initialised.  Tests that need a fresh manager call
    :func:`reset_knowledge_manager_for_tests` and then patch
    :func:`get_knowledge_manager` to return their own
    instance.
    """
    global _knowledge_manager
    if _knowledge_manager is None:
        _knowledge_manager = KnowledgeManager()
    return _knowledge_manager


def reset_knowledge_manager_for_tests() -> None:  # pragma: no cover - seam
    """Drop the cached singleton."""
    global _knowledge_manager
    _knowledge_manager = None
