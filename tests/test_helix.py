"""Tests for the HelixDB async client.

These tests are written against a live local HelixDB gateway. If no
gateway is running, they are skipped — keeping the test suite green
in CI while still exercising the code on a developer machine.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

from app.db.helix import (
    HelixClient,
    HelixQueryError,
    QueryResult,
    read_query,
    step_add_n,
    step_count,
    step_n_where_eq,
    write_query,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def helix() -> AsyncGenerator[HelixClient, None]:
    """A HelixClient connected to localhost; yields it then closes."""
    client = HelixClient()
    try:
        yield client
    finally:
        await client.close()


@pytest_asyncio.fixture
async def live_helix() -> AsyncGenerator[HelixClient | None, None]:
    """Skip the test if no HelixDB is reachable."""
    client = HelixClient()
    healthy = False
    try:
        healthy = await client.is_available()
    except Exception:
        healthy = False
    if not healthy:
        await client.close()
        pytest.skip("HelixDB not running on localhost:6969 or :8080")
    try:
        yield client
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Query AST builder unit tests — no I/O required
# ---------------------------------------------------------------------------


class TestQueryBuilders:
    """The query envelope shape must match Helix's wire format."""

    def test_read_query_envelope_shape(self) -> None:
        env = read_query(("users", [step_count()]), returns=["users"])
        assert env["request_type"] == "read"
        assert "query" in env
        assert env["query"]["queries"][0]["Query"]["name"] == "users"
        assert env["query"]["queries"][0]["Query"]["condition"] is None
        assert env["query"]["returns"] == ["users"]
        assert env["parameters"] == {}

    def test_write_query_envelope_shape(self) -> None:
        env = write_query(("u", [step_add_n("User", {"name": "alice"})]), returns=["u"])
        assert env["request_type"] == "write"
        assert env["query"]["queries"][0]["Query"]["name"] == "u"

    def test_returns_defaults_to_query_names(self) -> None:
        env = read_query(("a", []), ("b", []))
        assert env["query"]["returns"] == ["a", "b"]

    def test_parameters_pass_through(self) -> None:
        env = read_query(("u", []), parameters={"name": "alice"})
        assert env["parameters"] == {"name": "alice"}


class TestStepHelpers:
    def test_step_add_n_wraps_properties(self) -> None:
        step = step_add_n("Person", {"name": "alice", "age": 30})
        assert step["AddN"]["label"] == "Person"
        # Helix expects a list of [name, PropertyInput] tuples.
        props = step["AddN"]["properties"]
        assert isinstance(props, list)
        assert props[0] == ["name", {"Value": {"String": "alice"}}]
        assert props[1] == ["age", {"Value": {"I32": 30}}]

    def test_step_n_where_eq(self) -> None:
        step = step_n_where_eq("name", "bob")
        assert step == {"NWhere": {"Eq": ["name", {"String": "bob"}]}}

    def test_step_count(self) -> None:
        assert step_count() == "Count"

    def test_literal_types(self) -> None:
        # bool
        from app.db.helix import _literal  # noqa: PLC0415

        assert _literal(True) == {"Boolean": True}
        assert _literal(1) == {"I32": 1}
        assert _literal(1.5) == {"F32": 1.5}
        assert _literal("x") == {"String": "x"}
        assert _literal([1, 2]) == {"Array": [{"I32": 1}, {"I32": 2}]}

    def test_unsupported_literal_raises(self) -> None:
        from app.db.helix import _literal  # noqa: PLC0415

        with pytest.raises(TypeError):
            _literal(object())


# ---------------------------------------------------------------------------
# Live integration tests — require a running HelixDB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLiveHelix:
    async def test_health_returns_healthy(self, live_helix: HelixClient) -> None:
        h = await live_helix.health()
        assert h.healthy is True
        assert h.latency_ms >= 0
        assert h.error is None

    async def test_ping_succeeds(self, live_helix: HelixClient) -> None:
        assert await live_helix.ping() is True

    async def test_count_returns_int(self, live_helix: HelixClient) -> None:
        n = await live_helix.count_nodes("NonexistentLabel_XYZ")
        assert isinstance(n, int)
        assert n == 0

    async def test_execute_returns_query_result(self, live_helix: HelixClient) -> None:
        # The `c` here is a placeholder query name; in production we'd
        # register the named query on the HelixDB side first.  We only
        # care that the call shape works.
        res = await live_helix.execute(
            read_query(("c", [{"NWhere": {"Eq": ["$label", {"String": "X"}]}}, "Count"]))  # type: ignore[arg-type]
        )
        assert isinstance(res, QueryResult)
        assert res.latency_ms >= 0
        assert res.request_type == "read"

    async def test_invalid_query_raises(self, live_helix: HelixClient) -> None:
        # Missing required field to provoke an error
        with pytest.raises(HelixQueryError):
            await live_helix.execute({"bogus": True})

    async def test_concurrent_health_probes(self, live_helix: HelixClient) -> None:
        results = await asyncio.gather(*[live_helix.health() for _ in range(8)])
        assert all(r.healthy for r in results)

    async def test_round_trip_write_then_count(self, live_helix: HelixClient) -> None:
        # Write a single node with a unique label, then count it.
        unique_label = f"Test_{int(time.time() * 1000)}"
        env = write_query(
            (
                "n",
                [step_add_n(unique_label, {"name": "tester"})],
            )
        )
        write_res = await live_helix.execute(env)
        assert write_res.request_type == "write"

        # Count via the convenience method.
        n = await live_helix.count_nodes(unique_label)
        assert n == 1
