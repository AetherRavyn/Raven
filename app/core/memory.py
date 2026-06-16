# app/core/memory.py
"""Persistent semantic memory store backed by ChromaDB.

Singleton — call get_memory_store() to get the single shared instance.

Collections:
  "saras_facts"   — FACT and RULE memories from MemoryTool
  "saras_tools"   — TOOL_GUIDE memories from MemoryTool

Usage:
    store = get_memory_store()
    store.save("FACT", "User's laptop IP is 192.168.1.5", user_id="123")
    snippets = store.retrieve("what is the user's laptop IP", top_k=5)
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

from app.settings.config import Config

_CHROMA_PATH = Path(Config.VECTOR_DB_PATH)
_EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # 80 MB, fast, good quality

MemoryCategory = Literal["FACT", "RULE", "TOOL_GUIDE"]

_INSTANCE: MemoryStore | None = None


class MemoryStore:
    """ChromaDB-backed persistent semantic memory."""

    def __init__(self, db_path: str = str(_CHROMA_PATH)) -> None:
        import warnings
        import chromadb
        from chromadb.utils import embedding_functions

        Path(db_path).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=db_path)
        # Suppress harmless 'position_ids UNEXPECTED' warning from newer transformers
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*position_ids.*")
            warnings.filterwarnings("ignore", message=".*UNEXPECTED.*")
            self._ef = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=_EMBEDDING_MODEL
            )
        self._facts = self._client.get_or_create_collection(
            "saras_facts", embedding_function=self._ef
        )
        self._tools = self._client.get_or_create_collection(
            "saras_tools", embedding_function=self._ef
        )
        logger.info(
            "MemoryStore: facts=%d tools=%d",
            self._facts.count(),
            self._tools.count(),
        )

    def save(
        self,
        category: MemoryCategory,
        content: str,
        user_id: str | None = None,
    ) -> None:
        """Upsert a memory entry. ID is a hash of category+content."""
        import hashlib

        collection = self._tools if category == "TOOL_GUIDE" else self._facts
        doc_id = hashlib.sha256(f"{category}:{content}".encode()).hexdigest()[:32]
        metadata = {
            "category": category,
            "user_id": user_id or "global",
            "timestamp": int(time.time()),
        }
        collection.upsert(ids=[doc_id], documents=[content], metadatas=[metadata])

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        user_id: str | None = None,
    ) -> list[str]:
        """Return the top_k most semantically relevant memories as plain strings."""
        results: list[str] = []
        for collection in (self._facts, self._tools):
            try:
                count = collection.count()
                if count == 0:
                    continue
                where = {"user_id": {"$in": [user_id, "global"]}} if user_id else None
                n = min(top_k, count)
                qr = collection.query(
                    query_texts=[query],
                    n_results=n,
                    where=where,
                )
                docs = qr.get("documents", [[]])[0]
                results.extend(docs)
            except Exception as exc:
                logger.warning("MemoryStore.retrieve error: %s", exc)

        # Deduplicate, preserve order
        seen: set[str] = set()
        unique = []
        for r in results:
            if r not in seen:
                seen.add(r)
                unique.append(r)
        return unique[:top_k]

    def count(self) -> tuple[int, int]:
        """Return (facts_count, tools_count)."""
        return self._facts.count(), self._tools.count()


class PgvectorMemoryStore:
    """PostgreSQL + pgvector semantic memory store.

    Active only when MEMORY_BACKEND=pgvector and DATABASE_URL points to PostgreSQL.
    Falls back gracefully if pgvector extension is unavailable.
    """

    def __init__(self) -> None:
        import warnings
        from sentence_transformers import SentenceTransformer  # type: ignore

        # Suppress harmless 'position_ids UNEXPECTED' warning from newer transformers
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*position_ids.*")
            warnings.filterwarnings("ignore", message=".*UNEXPECTED.*")
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("PgvectorMemoryStore initialised (dim=384)")

    def _embed(self, text: str) -> list[float]:
        return self._model.encode(text, convert_to_numpy=True).tolist()

    def save(
        self,
        category: MemoryCategory,
        content: str,
        user_id: str | None = None,
    ) -> None:
        """Persist memory synchronously (wraps async in run_in_executor caller)."""
        import asyncio

        asyncio.get_event_loop().run_until_complete(
            self._save_async(category, content, user_id)
        )

    async def _save_async(
        self,
        category: MemoryCategory,
        content: str,
        user_id: str | None,
    ) -> None:
        try:
            import json

            from app.db.session import get_session_factory

            embedding = self._embed(content)
            factory = get_session_factory()
            async with factory() as session:
                from app.db.models import Memory

                mem = Memory(
                    category=category,
                    content=content,
                    embedding_json=json.dumps(embedding),
                    importance=1.0,
                )
                session.add(mem)
                await session.commit()
        except Exception as exc:
            logger.warning("PgvectorMemoryStore.save error: %s", exc)

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        user_id: str | None = None,
    ) -> list[str]:
        """Cosine similarity search — returns top_k content strings."""
        import asyncio

        try:
            return asyncio.get_event_loop().run_until_complete(
                self._retrieve_async(query, top_k, user_id)
            )
        except Exception as exc:
            logger.warning("PgvectorMemoryStore.retrieve error: %s", exc)
            return []

    async def _retrieve_async(
        self,
        query: str,
        top_k: int,
        user_id: str | None,
    ) -> list[str]:
        import json

        from sqlalchemy import select, text

        from app.db.models import Memory
        from app.db.session import get_session_factory

        embedding = self._embed(query)
        factory = get_session_factory()
        async with factory() as session:
            # Use cosine distance via pgvector operator <=>
            # Falls back to naive Python sort if pgvector not available
            try:
                rows = await session.execute(
                    text(
                        "SELECT content FROM memories "
                        "ORDER BY embedding_json::vector <=> :emb "
                        "LIMIT :k"
                    ),
                    {"emb": str(embedding), "k": top_k},
                )
                return [r[0] for r in rows]
            except Exception:
                # Fallback: load all and rank by cosine similarity in Python
                stmt = select(Memory.content, Memory.embedding_json).limit(200)
                result = await session.execute(stmt)
                rows = result.all()
                if not rows:
                    return []
                import numpy as np

                q_vec = np.array(embedding)
                scored = []
                for content, emb_json in rows:
                    if not emb_json:
                        continue
                    v = np.array(json.loads(emb_json))
                    norm = np.linalg.norm(q_vec) * np.linalg.norm(v)
                    sim = float(np.dot(q_vec, v) / norm) if norm > 0 else 0.0
                    scored.append((sim, content))
                scored.sort(key=lambda x: x[0], reverse=True)
                return [c for _, c in scored[:top_k]]

    def count(self) -> tuple[int, int]:
        return (0, 0)


_PGVECTOR_INSTANCE: PgvectorMemoryStore | None = None
_HELIX_INSTANCE: Any = None  # HelixMemoryStore, lazy-typed to avoid import


def get_memory_store() -> Any:
    """Return the configured memory backend.

    MEMORY_BACKEND=chroma (default) → ChromaDB MemoryStore
    MEMORY_BACKEND=pgvector         → PostgreSQL PgvectorMemoryStore
    MEMORY_BACKEND=helix            → HelixDB HelixMemoryStore (Phase B)
    """
    from app.settings.config import Config

    backend = getattr(Config, "MEMORY_BACKEND", "chroma")

    if backend == "helix":
        global _HELIX_INSTANCE
        if _HELIX_INSTANCE is None:
            from app.db.memory_helix import HelixMemoryStore

            _HELIX_INSTANCE = HelixMemoryStore()
        return _HELIX_INSTANCE

    if backend == "pgvector":
        global _PGVECTOR_INSTANCE
        if _PGVECTOR_INSTANCE is None:
            _PGVECTOR_INSTANCE = PgvectorMemoryStore()
        return _PGVECTOR_INSTANCE

    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = MemoryStore()
    return _INSTANCE
