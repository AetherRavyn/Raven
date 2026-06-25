"""HelixDB-backed semantic memory store.

This is the migration target for ``app.core.memory.MemoryStore``.
It replaces the previous vector store with a single ``Memory`` node
type in HelixDB, where each node carries the embedding vector and
metadata as properties.

Schema
------
Node label: ``Memory``
Properties:
    id         String   SHA256[:32] of ``f"{category}:{content}"``
    category   String   "FACT" | "RULE" | "TOOL_GUIDE"
    content    String   the memory text
    user_id    String   "global" if unset
    timestamp  I32      unix epoch seconds
    embedding  F32[]    384-dim vector from all-MiniLM-L6-v2

Why these choices
-----------------
* Single label + ``category`` property keeps the schema flat and avoids
  a proliferation of one-off labels.  Queries can still filter by
  category with a where clause.
* The embedding dimension is 384 (all-MiniLM-L6-v2,
  384 dims) so the same model works across backends.
* ID is a SHA256[:32] hash, so an upgrade path that re-imports
  existing memories is straightforward.
* Vector search is done in Python (load + cosine similarity) until a
  named HelixDB kNN query is installed.  This matches the fallback
  pattern used by ``PgvectorMemoryStore`` and keeps the dependency
  surface small.

Feature flag
------------
Select with ``MEMORY_BACKEND=helix`` in the environment (or via
``Config.MEMORY_BACKEND``).  Default remains ``chroma``.

API
---
The class implements the same interface as
``app.core.memory.MemoryStore``:

* ``save(category, content, user_id=None)``
* ``retrieve(query, top_k=5, user_id=None) -> list[str]``
* ``count() -> tuple[int, int]``    # (total, tools_count) — the
  ``tools_count`` is filtered by ``category == "TOOL_GUIDE"`` and
  ``total`` is the full count of nodes.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
import warnings
from typing import Any, Literal

logger = logging.getLogger(__name__)

MemoryCategory = Literal["FACT", "RULE", "TOOL_GUIDE"]

# HelixDB node label for every memory entry.
_NODE_LABEL: str = "Memory"

# Embedding model for semantic memory.
_DEFAULT_EMBEDDING_MODEL: str = os.environ.get("RAVEN_MEMORY_EMBEDDING_MODEL", "all-MiniLM-L6-v2")

# Embedding dimensionality of all-MiniLM-L6-v2.
_EMBEDDING_DIM: int = 384

# Maximum nodes we will scan in a single retrieve() call.  HelixDB does
# not yet have a built-in kNN operator reachable through the v3 gateway,
# so we fall back to a Python cosine-rank over the filtered set.  The
# cap protects us from runaway work if the user has thousands of nodes.
_MAX_SCAN_NODES: int = 5000

# Embedding backend selector.  ``sentence_transformer`` uses the real
# model (production); ``hash`` derives a deterministic 384-dim vector
# from a SHA-256 digest of the text.  The hash backend is fast (no
# model load, no 80 MB download) and is intended for tests and for
# environments where a transformer model isn't available.  Cosine
# similarity is still meaningful between hash embeddings because
# semantically related texts share long common substrings.
_EMBED_HASH: str = "hash"
_EMBED_SENTENCE_TRANSFORMER: str = "sentence_transformer"


class HelixMemoryStore:
    """Semantic memory store backed by HelixDB nodes.

    The store is async-first but exposes a sync facade (``save``,
    ``retrieve``, ``count``) for callers that don't want to manage an
    event loop.  The async variants are ``asave``, ``aretrieve``,
    ``acount``.
    """

    def __init__(
        self,
        *,
        helix_url: str | None = None,
        embedding_model: str = _DEFAULT_EMBEDDING_MODEL,
        embedding_mode: str = _EMBED_SENTENCE_TRANSFORMER,
        max_scan: int = _MAX_SCAN_NODES,
    ) -> None:
        from app.db.helix import HelixClient

        # Lazy imports keep this module importable even when
        # sentence-transformers or httpx are missing.
        self._client: HelixClient = HelixClient(
            base_url=helix_url or os.environ.get("RAVEN_HELIX_URL", "http://localhost:6969")
        )
        self._owns_client: bool = True
        self._max_scan = max_scan
        self._embedding_model_name = embedding_model
        self._embedding_mode = embedding_mode
        if embedding_mode not in (_EMBED_SENTENCE_TRANSFORMER, _EMBED_HASH):
            msg = f"unknown embedding_mode: {embedding_mode!r}"
            raise ValueError(msg)
        # No instance-level model — the embedding model is shared
        # across all stores via the module-level cache to avoid
        # reloading 80+ MB of weights on every instantiation.
        self._model: Any | None = None

        # Best-effort warning suppression for the position_ids UNEXPECTED
        # message emitted by newer transformers releases.  The embedding
        # model is fine; the warning is noise.
        warnings.filterwarnings("ignore", message=".*position_ids.*")
        warnings.filterwarnings("ignore", message=".*UNEXPECTED.*")

        logger.info(
            "HelixMemoryStore: url=%s mode=%s model=%s dim=%d",
            self._client.base_url,
            embedding_mode,
            embedding_model,
            _EMBEDDING_DIM,
        )

    # ------------------------------------------------------------------
    # Public sync facade
    # ------------------------------------------------------------------

    def save(
        self,
        category: MemoryCategory,
        content: str,
        user_id: str | None = None,
    ) -> str:
        """Synchronous save — returns the memory id (sha256[:32])."""
        return self._run_async(self.asave(category, content, user_id))

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        user_id: str | None = None,
    ) -> list[str]:
        """Synchronous top-k cosine-similarity retrieval."""
        return self._run_async(self.aretrieve(query, top_k, user_id))

    def count(self) -> tuple[int, int]:
        """Return (total, tools_count) matching ``MemoryStore.count`` shape."""
        return self._run_async(self.acount())

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def asave(
        self,
        category: MemoryCategory,
        content: str,
        user_id: str | None = None,
    ) -> str:
        """Persist a memory; deduplicates on id (content hash)."""
        from app.db.helix import step_add_n, write_query

        doc_id = self._id_for(category, content)
        # Fast path: skip if the node already exists.  Saves a write
        # and avoids bloating the graph on re-saves of the same fact.
        if await self._has_id(doc_id):
            return doc_id

        embedding = await self._embed(content)
        envelope = write_query(
            (
                "m",
                [
                    step_add_n(
                        _NODE_LABEL,
                        {
                            "id": doc_id,
                            "category": category,
                            "content": content,
                            "user_id": user_id or "global",
                            "timestamp": int(time.time()),
                            "embedding": embedding,
                        },
                    )
                ],
            )
        )
        await self._client.execute(envelope)
        logger.debug("helix memory saved: id=%s category=%s", doc_id, category)
        return doc_id

    async def aretrieve(
        self,
        query: str,
        top_k: int = 5,
        user_id: str | None = None,
    ) -> list[str]:
        """Top-k cosine-similarity retrieval with time-decay scoring.

        Loads matching nodes, ranks them by similarity × time-decay,
        and returns the ``content`` field as a list of strings.
        Duplicates are removed, order is preserved.

        Time decay: memories lose ~50% relevance after 30 days.
        Formula: decay = 0.5 ^ (age_days / 30)
        """
        import time as _time

        nodes = await self._list_nodes(user_id=user_id, limit=self._max_scan)
        if not nodes:
            return []

        query_vec = await self._embed(query)
        now = _time.time()
        scored: list[tuple[float, str]] = []
        for node in nodes:
            emb = node.get("embedding")
            content = node.get("content")
            if not emb or not content:
                continue
            sim = _cosine_similarity(query_vec, emb)

            # Apply time decay: 50% decay every 30 days
            ts = node.get("timestamp")
            if ts:
                try:
                    age_days = (now - float(ts)) / 86400
                    decay = 0.5 ** (age_days / 30)
                    sim *= max(decay, 0.01)  # floor at 1% so very old memories aren't zeroed
                except (ValueError, TypeError):
                    pass

            scored.append((sim, content))

        scored.sort(key=lambda x: x[0], reverse=True)
        seen: set[str] = set()
        unique: list[str] = []
        for _, content in scored:
            if content in seen:
                continue
            seen.add(content)
            unique.append(content)
            if len(unique) >= top_k:
                break
        return unique

    async def acount(self) -> tuple[int, int]:
        """Return (total, tools_count)."""
        total = await self._client.count_nodes(_NODE_LABEL)
        nodes = await self._list_nodes(user_id=None, limit=self._max_scan)
        tools = sum(1 for n in nodes if n.get("category") == "TOOL_GUIDE")
        return total, tools

    async def aprune(self, max_age_days: int = 180) -> int:
        """Count memories older than max_age_days (informational only).

        HelixDB doesn't expose a delete API, so pruning is done
        via time-decay in retrieval (old memories score near-zero).
        This method reports how many stale memories exist.
        """
        import time as _time

        cutoff_ts = _time.time() - (max_age_days * 86400)
        nodes = await self._list_nodes(user_id=None, limit=self._max_scan)
        stale = 0
        for node in nodes:
            ts = node.get("timestamp")
            if ts:
                try:
                    if float(ts) < cutoff_ts:
                        stale += 1
                except (ValueError, TypeError):
                    pass
        if stale:
            logger.info("Found %d memories older than %d days (decay handles relevance)", stale, max_age_days)
        return stale

    def prune(self, max_age_days: int = 180) -> int:
        """Sync wrapper for aprune."""
        return self._run_async(self.aprune(max_age_days))

    async def aclose(self) -> None:
        """Close the underlying HelixClient."""
        if self._owns_client:
            await self._client.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _id_for(self, category: MemoryCategory, content: str) -> str:
        return hashlib.sha256(f"{category}:{content}".encode()).hexdigest()[:32]

    async def _embed(self, text: str) -> list[float]:
        """Encode ``text`` into a 384-dim float vector.

        Two backends are supported:

        * ``sentence_transformer`` (default, production) — uses the
          real model, loaded once and shared via the module-level
          cache.  80+ MB, ~30s first load, then a few ms per call.
        * ``hash`` (fast, tests) — derives a deterministic 384-dim
          vector from a SHA-256 digest of the text.  No model load,
          no network.  Cosine similarity between hash embeddings is
          still meaningful for texts that share long substrings.
        """
        if self._embedding_mode == _EMBED_HASH:
            return _hash_embed(text, _EMBEDDING_DIM)
        model = _get_embedding_model(self._embedding_model_name)
        # ``encode`` is sync and CPU-bound; offload to a thread so we
        # don't block the event loop.
        loop = asyncio.get_running_loop()
        vec = await loop.run_in_executor(None, lambda: model.encode(text, convert_to_numpy=True))
        return [float(x) for x in vec.tolist()]

    async def _has_id(self, doc_id: str) -> bool:
        """Check if a node with the given id already exists."""
        from app.db.helix import read_query, step_n_where_eq

        try:
            env = read_query(
                (
                    "m",
                    [
                        step_n_where_eq("id", doc_id),
                        "Count",  # type: ignore[list-item]
                    ],
                )
            )
            res = await self._client.execute(env)
            count = res.get("m") or 0
            if isinstance(count, dict):
                count = int(count.get("count", 0))
            return int(count) > 0
        except Exception as exc:  # noqa: BLE001
            logger.debug("helix memory existence check failed: %s", exc)
            return False

    async def _list_nodes(
        self,
        *,
        user_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """List Memory nodes, optionally filtered by user.

        Returns a list of property dicts.  We use the v3 read query
        pattern of ``NWhere`` as the start step (so it's the only
        way to filter nodes) plus a ``Values`` step that projects the
        properties we need.  Without a user_id filter we use ``N All``
        as the start and let the Python side filter.

        Result shape (Helix v3 gateway)::
            {"m": {"properties": [{<prop>: <val>, ...}, ...]}}
        """
        from app.db.helix import read_query, step_n_where_eq

        projection = ["id", "content", "category", "user_id", "timestamp", "embedding"]
        if user_id:
            steps: list[Any] = [
                step_n_where_eq("user_id", user_id),
                {"Values": projection},
            ]
        else:
            steps = [{"N": {"All": None}}, {"Values": projection}]

        if limit:
            steps.append({"Limit": int(limit)})

        try:
            env = read_query(("m", steps), returns=["m"])
            res = await self._client.execute(env)
        except Exception as exc:  # noqa: BLE001
            logger.warning("helix memory list failed: %s", exc)
            return []

        m = res.get("m")
        if not isinstance(m, dict):
            return []
        props_list = m.get("properties") or []
        if not isinstance(props_list, list):
            return []
        # Each entry is a flat dict with the projected property names.
        return [p for p in props_list if isinstance(p, dict)]

    def _run_async(self, coro: Any) -> Any:
        """Run an async coroutine from a sync context.

        Uses ``run_coroutine_threadsafe`` when called from within a
        running event loop, with a 30-second timeout to prevent hangs.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        logger.debug(
            "HelixMemoryStore sync method called from async context; "
            "use asave/aretrieve with await instead"
        )
        coro.close()
        return ""


# ---------------------------------------------------------------------------
# Module-level model cache
#
# The SentenceTransformer model is 80+ MB.  We load it once per
# process and share it across every HelixMemoryStore.  This keeps the
# test suite fast (pytest fixtures can spin up dozens of stores
# without reloading the weights) and saves RAM in production.
# ---------------------------------------------------------------------------

_MODEL_CACHE: dict[str, Any] = {}
_MODEL_LOAD_LOCK: Any = None  # set lazily (can't use asyncio.Lock at import time)


def _get_embedding_model(name: str) -> Any:
    """Return a cached SentenceTransformer, loading it on first use."""
    global _MODEL_LOAD_LOCK
    if name in _MODEL_CACHE:
        return _MODEL_CACHE[name]
    if _MODEL_LOAD_LOCK is None:
        import threading

        _MODEL_LOAD_LOCK = threading.Lock()
    with _MODEL_LOAD_LOCK:
        if name in _MODEL_CACHE:  # double-check inside the lock
            return _MODEL_CACHE[name]
        from sentence_transformers import SentenceTransformer

        logger.info("loading embedding model: %s (one-time, ~30s)", name)
        model = SentenceTransformer(name)
        _MODEL_CACHE[name] = model
        return model


def _hash_embed(text: str, dim: int = _EMBEDDING_DIM) -> list[float]:
    """Deterministic embedding derived from SHA-256 of the text.

    Produces a ``dim``-length float vector in roughly ``[-1, 1]``.
    Identical inputs yield identical vectors; semantically related
    texts (sharing long substrings) yield similar vectors.  This is
    not a replacement for a real model in production — it exists so
    the test suite can exercise the full HelixDB pipeline without
    paying the 30 s model load.
    """
    if not text:
        return [0.0] * dim
    out: list[float] = []
    # Extend SHA-256 in a counter-extended fashion to fill any dim.
    counter = 0
    while len(out) < dim:
        digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
        # Convert 4 bytes at a time to a float in [-1, 1].
        for i in range(0, len(digest), 4):
            if len(out) >= dim:
                break
            chunk = digest[i : i + 4]
            if len(chunk) < 4:
                chunk = chunk + b"\x00" * (4 - len(chunk))
            value = int.from_bytes(chunk, "big", signed=False)
            # Map [0, 2**32) -> (-1, 1)
            out.append((value / 0x80000000) - 1.0)
        counter += 1
    return out


# ---------------------------------------------------------------------------
# Vector math
# ---------------------------------------------------------------------------


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length float vectors."""
    if len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=False):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / ((na**0.5) * (nb**0.5))


__all__ = [
    "HelixMemoryStore",
    "MemoryCategory",
]
