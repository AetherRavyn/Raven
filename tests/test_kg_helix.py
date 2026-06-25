"""Tests for the HelixDB-backed knowledge graph (Phase B).

The live tests require a running HelixDB gateway on
``localhost:6969`` (helix CLI) or ``localhost:8080`` (raw Docker).
If neither is reachable, the live tests are skipped.

The unit tests cover the JSON edge encoding helpers (no I/O) and
the ``KnowledgeGraphTool`` dispatch logic.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio

from app.db.helix import HelixClient, step_n_where_eq
from app.db.knowledge_graph_helix import (
    HelixKnowledgeGraph,
    _decode_edges,
    _encode_metadata,
    _normalise_json,
    _normalise_relation,
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
async def fresh_kg(live_helix_client: HelixClient) -> AsyncGenerator[tuple[HelixKnowledgeGraph, str], None]:
    """A HelixKnowledgeGraph with a unique entity namespace per test.

    All entities created during the test use a UUID prefix so they
    don't collide with prior runs.  Teardown drops every entity
    whose ``name`` starts with that prefix.
    """
    prefix = f"kg-{uuid.uuid4().hex[:12]}-"
    kg = HelixKnowledgeGraph()
    try:
        yield kg, prefix
    finally:
        # Best-effort cleanup: walk every KGEntity node and drop the
        # ones created by this test.  No-ops on failure.
        try:
            from app.db.helix import read_query, write_query

            env = read_query(
                (
                    "m",
                    [
                        step_n_where_eq("user_id", "global"),
                        {"Values": ["name"]},
                    ],
                ),
            )
            res = await live_helix_client.execute(env)
            m = res.get("m")
            if isinstance(m, dict):
                for p in m.get("properties") or []:
                    name = p.get("name") if isinstance(p, dict) else None
                    if name and name.startswith(prefix):
                        await live_helix_client.execute(
                            write_query(
                                (
                                    "drop",
                                    [step_n_where_eq("name", name), "Drop"],  # type: ignore[list-item]
                                ),
                            )
                        )
        except Exception:  # noqa: BLE001
            pass
        await kg.aclose()


# ---------------------------------------------------------------------------
# Unit tests — no I/O
# ---------------------------------------------------------------------------


class TestNormalisers:
    def test_normalise_relation_uppercases_and_replaces_spaces(self) -> None:
        assert _normalise_relation("owns server") == "OWNS_SERVER"
        assert _normalise_relation("  has access  ") == "HAS_ACCESS"
        assert _normalise_relation("OWNS") == "OWNS"

    def test_normalise_relation_defaults(self) -> None:
        assert _normalise_relation("") == "RELATED_TO"
        assert _normalise_relation(None or "") == "RELATED_TO"  # type: ignore[arg-type]

    def test_encode_metadata_empty(self) -> None:
        assert _encode_metadata({}) == "{}"

    def test_encode_metadata_roundtrips(self) -> None:
        import json

        meta = {"since": 2024, "verified": True, "tags": ["a", "b"]}
        encoded = _encode_metadata(meta)
        assert json.loads(encoded) == {"since": 2024, "verified": True, "tags": ["a", "b"]}

    def test_normalise_json_handles_nested(self) -> None:
        import re

        out = _normalise_json({"a": [1, 2, {"b": object()}]})
        # Bare ``object()`` is not JSON-serialisable, so the helper
        # falls back to a stable string representation of the form
        # ``<object object at 0x...>``.
        assert re.fullmatch(r"<object object at 0x[0-9a-fA-F]+>", out["a"][2]["b"])

    def test_normalise_json_preserves_primitives(self) -> None:
        assert _normalise_json({"a": 1, "b": "x", "c": True, "d": None}) == {
            "a": 1,
            "b": "x",
            "c": True,
            "d": None,
        }

    def test_decode_edges_empty(self) -> None:
        assert _decode_edges("") == []
        assert _decode_edges(None) == []
        assert _decode_edges([]) == []
        assert _decode_edges("not json") == []

    def test_decode_edges_roundtrips(self) -> None:
        import json

        edges = [{"to": "Laptop", "relation": "OWNS", "metadata": "{}"}]
        assert _decode_edges(json.dumps(edges)) == edges

    def test_decode_edges_filters_non_dicts(self) -> None:
        import json

        assert _decode_edges(json.dumps([{"a": 1}, "bad", 42])) == [{"a": 1}]


# ---------------------------------------------------------------------------
# Live integration tests — require a running HelixDB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAddRelationship:
    async def test_creates_two_entities_and_edge(self, fresh_kg: Any) -> None:
        kg, prefix = fresh_kg
        result = await kg.add_relationship(
            f"{prefix}Alice", "OWNS", f"{prefix}Laptop", user_id="tester"
        )
        assert result["success"] is True
        assert "Alice" in result["message"]
        assert "Laptop" in result["message"]
        assert "OWNS" in result["message"]

    async def test_relation_is_normalised(self, fresh_kg: Any) -> None:
        kg, prefix = fresh_kg
        result = await kg.add_relationship(
            f"{prefix}A", "owns server", f"{prefix}B", user_id="tester"
        )
        assert result["success"] is True
        # The normalised verb should be reflected in the response
        assert "OWNS_SERVER" in result["message"]

    async def test_duplicate_edge_is_idempotent(self, fresh_kg: Any) -> None:
        kg, prefix = fresh_kg
        e1 = f"{prefix}A"
        e2 = f"{prefix}B"
        r1 = await kg.add_relationship(e1, "OWNS", e2, user_id="tester")
        r2 = await kg.add_relationship(e1, "OWNS", e2, user_id="tester")
        assert r1["success"] and r2["success"]
        # The entity's edges list should have exactly one OWNS edge to B
        node = await kg._get_entity(e1)
        assert node is not None
        edges = _decode_edges(node.get("edges"))
        owns_to_b = [e for e in edges if e["to"] == e2 and e["relation"] == "OWNS"]
        assert len(owns_to_b) == 1

    async def test_multiple_outgoing_edges(self, fresh_kg: Any) -> None:
        kg, prefix = fresh_kg
        alice = f"{prefix}Alice"
        await kg.add_relationship(alice, "OWNS", f"{prefix}Laptop", user_id="tester")
        await kg.add_relationship(alice, "OWNS", f"{prefix}Phone", user_id="tester")
        await kg.add_relationship(alice, "PREFERS", f"{prefix}DarkMode", user_id="tester")
        node = await kg._get_entity(alice)
        assert node is not None
        edges = _decode_edges(node.get("edges"))
        assert len(edges) == 3
        relations = {e["relation"] for e in edges}
        assert relations == {"OWNS", "PREFERS"}


@pytest.mark.asyncio
class TestQueryEntity:
    async def test_query_existing_entity_returns_connections(self, fresh_kg: Any) -> None:
        kg, prefix = fresh_kg
        alice = f"{prefix}Alice"
        await kg.add_relationship(alice, "OWNS", f"{prefix}Laptop", user_id="tester")
        await kg.add_relationship(alice, "PREFERS", f"{prefix}DarkMode", user_id="tester")
        result = await kg.query_entity(alice)
        assert result["success"] is True
        assert result["entity"] == alice
        assert len(result["connections"]) == 2
        assert any("OWNS" in c for c in result["connections"])
        assert any("PREFERS" in c for c in result["connections"])

    async def test_query_unknown_entity_returns_empty_message(self, fresh_kg: Any) -> None:
        kg, prefix = fresh_kg
        result = await kg.query_entity(f"{prefix}Ghost")
        assert result["success"] is True
        assert result["connections"] == ["No connections found in the graph."]

    async def test_query_entity_with_no_outgoing_edges(self, fresh_kg: Any) -> None:
        kg, prefix = fresh_kg
        # Create an entity by referencing it as a target
        await kg.add_relationship(
            f"{prefix}A", "OWNS", f"{prefix}Lonely", user_id="tester"
        )
        result = await kg.query_entity(f"{prefix}Lonely")
        assert result["success"] is True
        # Lonely is referenced as a target, not a source, so it has no
        # outgoing edges of its own.
        assert result["connections"] == ["No connections found in the graph."]


@pytest.mark.asyncio
class TestFindPath:
    async def test_direct_path(self, fresh_kg: Any) -> None:
        kg, prefix = fresh_kg
        await kg.add_relationship(
            f"{prefix}Alice", "OWNS", f"{prefix}Laptop", user_id="tester"
        )
        result = await kg.find_path(f"{prefix}Alice", f"{prefix}Laptop")
        assert result["success"] is True
        assert "path" in result
        assert result["path"] == [f"{prefix}Alice", f"{prefix}Laptop"]

    async def test_two_hop_path(self, fresh_kg: Any) -> None:
        kg, prefix = fresh_kg
        alice = f"{prefix}Alice"
        laptop = f"{prefix}Laptop"
        openssh = f"{prefix}OpenSSH"
        await kg.add_relationship(alice, "OWNS", laptop, user_id="tester")
        await kg.add_relationship(laptop, "HOSTS_SERVICE", openssh, user_id="tester")
        result = await kg.find_path(alice, openssh)
        assert result["success"] is True
        assert result["path"] == [alice, laptop, openssh]

    async def test_no_path_returns_message(self, fresh_kg: Any) -> None:
        kg, prefix = fresh_kg
        await kg.add_relationship(
            f"{prefix}A", "OWNS", f"{prefix}B", user_id="tester"
        )
        result = await kg.find_path(f"{prefix}A", f"{prefix}ZZZ")
        assert result["success"] is True
        assert "message" in result
        assert "No direct path" in result["message"]

    async def test_self_path(self, fresh_kg: Any) -> None:
        kg, prefix = fresh_kg
        alice = f"{prefix}Alice"
        await kg.add_relationship(alice, "OWNS", f"{prefix}Laptop", user_id="tester")
        result = await kg.find_path(alice, alice)
        assert result["success"] is True
        assert result["path"] == [alice]

    async def test_path_respects_max_hops(self, fresh_kg: Any) -> None:
        kg, prefix = fresh_kg
        # Build a chain: A -> B -> C -> D -> E (4 hops)
        chain = [f"{prefix}{c}" for c in "ABCDE"]
        for i in range(len(chain) - 1):
            await kg.add_relationship(chain[i], "REL", chain[i + 1], user_id="tester")
        # Within 4 hops: A -> E is reachable (4 edges)
        result = await kg.find_path(chain[0], chain[-1], max_hops=4)
        assert result["success"] is True
        assert "path" in result
        # With max_hops=2, A -> E is NOT reachable
        result2 = await kg.find_path(chain[0], chain[-1], max_hops=2)
        assert "message" in result2


# ---------------------------------------------------------------------------
# Dispatch: KnowledgeGraphTool with KG_BACKEND=helix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestKnowledgeGraphToolHelixDispatch:
    async def test_dispatch_to_helix_backend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # This test exercises the live HelixDB dispatch path.  It
        # requires a reachable HelixDB endpoint (the ``helix`` CLI
        # on :6969 or the raw Docker image on :8080).  When neither
        # is up, skip rather than fail so the unit suite stays green
        # on machines without a running gateway.
        import socket

        def _port_open(host: str, port: int, timeout: float = 0.2) -> bool:
            try:
                with socket.create_connection((host, port), timeout=timeout):
                    return True
            except OSError:
                return False

        if not (_port_open("localhost", 6969) or _port_open("localhost", 8080)):
            pytest.skip(
                "HelixDB gateway not reachable on localhost:6969 or :8080"
            )

        monkeypatch.setenv("KG_BACKEND", "helix")
        monkeypatch.setenv("RAVEN_HELIX_URL", "http://localhost:8080")

        from app.tools.kgtool import KnowledgeGraphTool

        tool = KnowledgeGraphTool()
        try:
            # is_helix was removed — tool is always HelixDB now
            prefix = f"tool-{uuid.uuid4().hex[:8]}-"
            r1 = await tool.execute(
                operation="add_relationship",
                entity1=f"{prefix}Bob",
                relation="OWNS",
                entity2=f"{prefix}Server",
            )
            assert r1["success"] is True
            r2 = await tool.execute(
                operation="query_entity", query=f"{prefix}Bob"
            )
            assert r2["success"] is True
            assert any("Server" in c for c in r2["connections"])
            r3 = await tool.execute(
                operation="find_path",
                entity1=f"{prefix}Bob",
                entity2=f"{prefix}Server",
            )
            assert r3["success"] is True
            assert "path" in r3
        finally:
            # Cleanup via the underlying store
            try:
                kg = await tool._get_helix_kg()
                for name in (f"{prefix}Bob", f"{prefix}Server"):
                    node = await kg._get_entity(name)
                    if node is not None:
                        await kg._set_edges(name, [], user_id=None)
            except Exception:  # noqa: BLE001
                pass
