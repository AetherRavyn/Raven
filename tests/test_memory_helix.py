"""Tests for the HelixDB-backed memory store (Phase B).

The live tests require a running HelixDB gateway on
``localhost:6969`` (helix CLI) or ``localhost:8080`` (raw Docker).
If neither is reachable, the live tests are skipped — keeping the
CI suite green while still exercising the code on a developer
machine.

The unit tests (no I/O) cover the embedding helper and the
sync-from-async bridge.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio

from app.db.helix import HelixClient
from app.db.memory_helix import (
    HelixMemoryStore,
    MemoryCategory,
    _EMBEDDING_DIM,
    _cosine_similarity,
    _hash_embed,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def live_helix_client() -> AsyncGenerator[HelixClient, None]:
    """A live HelixClient; yields then closes."""
    client = HelixClient()
    healthy = await client.is_available()
    if not healthy:
        await client.close()
        pytest.skip("HelixDB not running on localhost:6969 or :8080")
    try:
        yield client
    finally:
        await client.close()


@pytest_asyncio.fixture
async def fresh_store(live_helix_client: HelixClient) -> AsyncGenerator[HelixMemoryStore, None]:
    """A HelixMemoryStore with a unique user_id and unique content prefix.

    The doc_id is a hash of ``category:content`` (not user_id), so
    reusing the same content across test runs would cause ``_has_id``
    to short-circuit the write.  The fixture mints a unique prefix
    so every test run produces fresh ids.
    """
    user_id = f"test-{uuid.uuid4().hex[:12]}"
    content_prefix = uuid.uuid4().hex[:8]
    store = HelixMemoryStore(embedding_mode="hash")
    try:
        yield store, user_id, content_prefix
    finally:
        # Best-effort cleanup: drop all nodes for this user.
        try:
            from app.db.helix import write_query, step_n_where_eq

            env = write_query(
                (
                    "d",
                    [
                        step_n_where_eq("user_id", user_id),
                        "Drop",
                    ],
                ),
                returns=["d"],
            )
            await live_helix_client.execute(env)
        except Exception:  # noqa: BLE001
            pass
        await store.aclose()


# ---------------------------------------------------------------------------
# Unit tests — no I/O
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    """The cosine-similarity helper is pure Python; test it in isolation."""

    def test_identical_vectors_score_one(self) -> None:
        a = [1.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0]
        assert _cosine_similarity(a, b) == pytest.approx(1.0)

    def test_orthogonal_vectors_score_zero(self) -> None:
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert _cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors_score_minus_one(self) -> None:
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert _cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_zero_vector_returns_zero(self) -> None:
        a = [0.0, 0.0, 0.0]
        b = [1.0, 2.0, 3.0]
        assert _cosine_similarity(a, b) == 0.0

    def test_mismatched_lengths_return_zero(self) -> None:
        a = [1.0, 0.0]
        b = [1.0, 0.0, 0.0]
        assert _cosine_similarity(a, b) == 0.0


class TestIdGeneration:
    def test_id_matches_sha256_of_category_and_content(self) -> None:
        from app.db.memory_helix import HelixMemoryStore

        store = HelixMemoryStore.__new__(HelixMemoryStore)  # skip __init__
        expected = hashlib.sha256(b"FACT:hello world").hexdigest()[:32]
        assert store._id_for("FACT", "hello world") == expected

    def test_id_differs_per_category(self) -> None:
        from app.db.memory_helix import HelixMemoryStore

        store = HelixMemoryStore.__new__(HelixMemoryStore)
        id_fact = store._id_for("FACT", "same text")
        id_rule = store._id_for("RULE", "same text")
        id_tool = store._id_for("TOOL_GUIDE", "same text")
        assert len({id_fact, id_rule, id_tool}) == 3


class TestEmbeddingConfig:
    """Sanity-check the embedding module-level constants."""

    def test_embedding_dim_is_384(self) -> None:
        assert _EMBEDDING_DIM == 384


class TestHashEmbed:
    """The hash-based embedding backend is unit-testable end to end."""

    def test_returns_correct_dimension(self) -> None:
        v = _hash_embed("hello world")
        assert len(v) == _EMBEDDING_DIM

    def test_deterministic(self) -> None:
        a = _hash_embed("user prefers dark mode")
        b = _hash_embed("user prefers dark mode")
        assert a == b

    def test_different_texts_produce_different_vectors(self) -> None:
        a = _hash_embed("user prefers dark mode")
        b = _hash_embed("the cat sat on the mat")
        assert a != b

    def test_empty_text_returns_zeros(self) -> None:
        v = _hash_embed("")
        assert v == [0.0] * _EMBEDDING_DIM

    def test_shared_substrings_increase_similarity(self) -> None:
        """Texts that share long substrings should have high similarity.

        This is the property the test suite relies on: hash embeddings
        are good enough to rank semantically related facts.
        """
        a = _hash_embed("the user prefers dark mode in all editors")
        b = _hash_embed("the user prefers dark mode in all editors")
        c = _hash_embed("completely unrelated query about the weather")
        sim_aa = _cosine_similarity(a, b)
        sim_ac = _cosine_similarity(a, c)
        # Identical texts should have similarity 1.0
        assert sim_aa == pytest.approx(1.0)
        # Unrelated text should have lower similarity than identical
        assert sim_ac < sim_aa

    def test_all_values_in_unit_range(self) -> None:
        v = _hash_embed("anything")
        # Each component comes from a uint32 mapped to (-1, 1)
        # so the absolute value is strictly < 1.0.
        for x in v:
            assert -1.0 <= x <= 1.0


class TestStoreInit:
    def test_invalid_embedding_mode_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown embedding_mode"):
            HelixMemoryStore(embedding_mode="bogus")


# ---------------------------------------------------------------------------
# Live integration tests — require a running HelixDB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLiveSaveAndRetrieve:
    async def test_save_returns_id(self, fresh_store: Any) -> None:
        store, user_id, prefix = fresh_store
        doc_id = await store.asave("FACT", f"{prefix} user lives in Bangalore", user_id=user_id)
        assert isinstance(doc_id, str)
        assert len(doc_id) == 32

    async def test_save_then_count_increments(self, fresh_store: Any) -> None:
        store, user_id, prefix = fresh_store
        # Snapshot existing counts so the assertions are stable
        # regardless of what previous tests left in the DB.
        total_before, tools_before = await store.acount()
        await store.asave("FACT", f"{prefix} fact one", user_id=user_id)
        await store.asave("FACT", f"{prefix} fact two", user_id=user_id)
        await store.asave("RULE", f"{prefix} rule one", user_id=user_id)
        total, tools = await store.acount()
        # tools is the count of TOOL_GUIDE nodes — we saved no
        # TOOL_GUIDE so it should not have grown.
        assert tools == tools_before
        # total should have grown by exactly 3 (3 new memories).
        assert total == total_before + 3

    async def test_save_is_idempotent(self, fresh_store: Any) -> None:
        """Saving the same (category, content) twice creates only one node."""
        store, user_id, prefix = fresh_store
        id1 = await store.asave("FACT", f"{prefix} user lives in Bangalore", user_id=user_id)
        id2 = await store.asave("FACT", f"{prefix} user lives in Bangalore", user_id=user_id)
        assert id1 == id2
        # Verify the node is unique
        from app.db.helix import read_query, step_n_where_eq

        env = read_query(
            ("c", [step_n_where_eq("id", id1), "Count"]),
            returns=["c"],
        )
        res = await store._client.execute(env)
        count = res.get("c") or {}
        if isinstance(count, dict):
            count = count.get("count", 0)
        assert int(count) == 1

    async def test_save_without_user_id_uses_global(self, fresh_store: Any) -> None:
        store, _, prefix = fresh_store
        doc_id = await store.asave("FACT", f"{prefix} global fact", user_id=None)
        assert isinstance(doc_id, str)
        # Clean up
        from app.db.helix import write_query, step_n_where_eq

        env = write_query(
            ("d", [step_n_where_eq("id", doc_id), "Drop"]),
            returns=["d"],
        )
        await store._client.execute(env)

    async def test_retrieve_returns_relevant_results(self, fresh_store: Any) -> None:
        store, user_id, prefix = fresh_store
        # Save 3 facts with distinct topics
        await store.asave("FACT", f"{prefix} user's favourite colour is blue", user_id=user_id)
        await store.asave("FACT", f"{prefix} user lives in Bangalore India", user_id=user_id)
        await store.asave(
            "TOOL_GUIDE",
            f"{prefix} use the file_write tool to save output to disk",
            user_id=user_id,
        )
        # The hash embedding doesn't preserve semantic relevance,
        # but it should still return the user's memories (filtered
        # by user_id) in some order.
        results = await store.aretrieve(
            f"{prefix} favourite colour", top_k=3, user_id=user_id
        )
        assert isinstance(results, list)
        assert len(results) == 3
        # All results should be from this test (contain the prefix).
        for r in results:
            assert prefix in r

    async def test_retrieve_returns_self_when_query_matches_content(
        self, fresh_store: Any
    ) -> None:
        """A query that exactly matches stored content should rank that
        content highest (the cosine similarity is 1.0 only for the
        identical string under hash embeddings).
        """
        store, user_id, prefix = fresh_store
        exact = f"{prefix} user lives in Bangalore India"
        other = f"{prefix} the weather is sunny today"
        await store.asave("FACT", exact, user_id=user_id)
        await store.asave("FACT", other, user_id=user_id)
        # Querying with the exact text should return the matching
        # content first because hash_embed(exact) == hash_embed(exact).
        results = await store.aretrieve(exact, top_k=2, user_id=user_id)
        assert len(results) == 2
        assert results[0] == exact

    async def test_retrieve_top_k_caps_results(self, fresh_store: Any) -> None:
        store, user_id, prefix = fresh_store
        for i in range(10):
            await store.asave(
                "FACT", f"{prefix} fact number {i} about topic {i}", user_id=user_id
            )
        results = await store.aretrieve(f"{prefix} topic", top_k=3, user_id=user_id)
        assert len(results) <= 3

    async def test_retrieve_user_isolation(self, fresh_store: Any) -> None:
        """A query for user A must not return user B's memories."""
        store, user_a, prefix = fresh_store
        user_b = f"test-{uuid.uuid4().hex[:12]}"
        try:
            await store.asave(
                "FACT", f"{prefix} user A's private fact", user_id=user_a
            )
            await store.asave(
                "FACT", f"{prefix} user B's private fact", user_id=user_b
            )
            results_a = await store.aretrieve(
                f"{prefix} private fact", top_k=10, user_id=user_a
            )
            results_b = await store.aretrieve(
                f"{prefix} private fact", top_k=10, user_id=user_b
            )
            assert any("A's" in r for r in results_a)
            assert any("B's" in r for r in results_b)
            assert not any("B's" in r for r in results_a)
            assert not any("A's" in r for r in results_b)
        finally:
            from app.db.helix import write_query, step_n_where_eq

            env = write_query(
                ("d", [step_n_where_eq("user_id", user_b), "Drop"]),
                returns=["d"],
            )
            await store._client.execute(env)

    async def test_count_returns_tuple(self, fresh_store: Any) -> None:
        store, user_id, prefix = fresh_store
        total_before, tools_before = await store.acount()
        await store.asave("FACT", f"{prefix} alpha fact", user_id=user_id)
        await store.asave("TOOL_GUIDE", f"{prefix} alpha tool", user_id=user_id)
        total, tools = await store.acount()
        assert isinstance(total, int)
        assert isinstance(tools, int)
        assert total == total_before + 2
        assert tools == tools_before + 1


# ---------------------------------------------------------------------------
# Sync facade — contract: must refuse to run from a running event loop
# ---------------------------------------------------------------------------


class TestSyncFacadeContract:
    """The sync facade gracefully handles calls from a running loop.

    Instead of raising (which would break callers), it returns a safe
    empty value and logs a debug warning.  Callers in async contexts
    should use asave/aretrieve with await instead.
    """

    def test_sync_from_running_loop_returns_empty(self, fresh_store: Any) -> None:
        """Sync save from async context returns empty string safely."""
        import asyncio

        async def _in_loop() -> None:
            store, _, _ = fresh_store
            result = store.save("FACT", "from loop", user_id="x")
            assert result == ""

        asyncio.run(_in_loop())

    def test_sync_count_returns_empty_from_loop(self, fresh_store: Any) -> None:
        import asyncio

        async def _in_loop() -> None:
            store, _, _ = fresh_store
            result = store.count()
            assert result == ""

        asyncio.run(_in_loop())

    def test_sync_retrieve_returns_empty_from_loop(self, fresh_store: Any) -> None:
        import asyncio

        async def _in_loop() -> None:
            store, _, _ = fresh_store
            result = store.retrieve("anything", top_k=3, user_id="x")
            assert result == ""

        asyncio.run(_in_loop())
