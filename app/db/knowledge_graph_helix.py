"""HelixDB-backed knowledge graph (Phase B).

This module replaces the Neo4j-backed ``KnowledgeGraphTool`` for
environments that don't want a Neo4j dependency.  The graph data
model is identical (entities with names, typed relations between
them) and the public API mirrors the original tool so callers
(``WorkspaceGraph``, ``MultimodalRetrieval``, ``Orchestrator``,
``Reviewer``, ``KnowledgeGraphPopulator``) keep working unchanged.

Schema
------
A single ``KGEntity`` node label carries:

* ``name``       — unique string identifier (the natural key)
* ``kind``       — free-form category string (user / device / fact /
                   project / etc.) — defaults to ``"entity"`` when
                   the caller doesn't provide one
* ``user_id``    — optional scope string for multi-tenant isolation
* ``edges``      — JSON-encoded list of ``{to, relation, metadata}``
                   describing the outgoing edges from this node

Why denormalized (edges as a property)
--------------------------------------
The Helix v3 gateway's ``AddE`` step requires explicit variable
chaining (AddN → As a → AddN → As b → AddE from=a to=b) and the
inline query semantics can be fragile.  Storing the outgoing
edges on the source node gives us O(1) lookup for ``query_entity``
and trivial BFS for ``find_path``, at the cost of an extra JSON
encode/decode per write.  For the dataset sizes a personal
workspace produces (hundreds of entities, thousands of edges) this
is the right trade-off.

A future optimisation could install a native ``AddE`` chain once
we've validated it on a real schema.  Until then, this denormalized
form is correct and fast enough.

Feature flag
------------
``KnowledgeGraphTool`` dispatches to this class when
``KG_BACKEND=helix`` is set; the default remains ``neo4j`` for
backwards compatibility.
"""

from __future__ import annotations

import json
import logging
import os
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)

_NODE_LABEL: str = "KGEntity"

_DEFAULT_KIND: str = "entity"

# Maximum number of nodes to consider during a single find_path
# traversal.  Personal workspace graphs are small, so this is just a
# safety net against pathological inputs.
_MAX_PATH_NODES: int = 5000


class HelixKnowledgeGraph:
    """Denormalized knowledge graph stored in HelixDB.

    Async-first; the original ``KnowledgeGraphTool`` wraps this in
    its own ``async execute(**kwargs)`` interface.  Callers that
    want the raw graph API can use ``add_relationship``,
    ``query_entity``, and ``find_path`` directly.
    """

    def __init__(
        self,
        *,
        helix_url: str | None = None,
    ) -> None:
        from app.db.helix import HelixClient

        self._client: HelixClient = HelixClient(
            base_url=helix_url or os.environ.get("SARAS_HELIX_URL", "http://localhost:6969")
        )
        logger.info("HelixKnowledgeGraph: url=%s label=%s", self._client.base_url, _NODE_LABEL)

    async def aclose(self) -> None:
        await self._client.close()

    # ------------------------------------------------------------------
    # Public API — mirrors KnowledgeGraphTool.execute(...)
    # ------------------------------------------------------------------

    async def add_relationship(
        self,
        entity1: str,
        relation: str,
        entity2: str,
        *,
        user_id: str | None = None,
        kind1: str = _DEFAULT_KIND,
        kind2: str = _DEFAULT_KIND,
        **metadata: Any,
    ) -> dict[str, Any]:
        """Add a directed relationship from ``entity1`` to ``entity2``.

        Creates both entities if they don't exist, then appends the
        new edge to ``entity1``'s outgoing list.  Matches the
        contract of ``KnowledgeGraphTool.execute("add_relationship", ...)``.
        """
        rel = _normalise_relation(relation)
        meta_json = _encode_metadata(metadata)

        # Make sure both endpoints exist.
        for name, kind in ((entity1, kind1), (entity2, kind2)):
            if not await self._has_entity(name):
                await self._create_entity(name, kind, user_id)

        # Append the edge to entity1's outgoing list.
        existing_edges = await self._get_edges(entity1)
        # De-duplicate: skip if the same (to, relation) already exists.
        if not any(e["to"] == entity2 and e["relation"] == rel for e in existing_edges):
            existing_edges.append({"to": entity2, "relation": rel, "metadata": meta_json})
            await self._set_edges(entity1, existing_edges, user_id=user_id)

        return {
            "success": True,
            "message": f"Added: [{entity1}] -> [{rel}] -> [{entity2}]",
        }

    async def query_entity(self, name: str) -> dict[str, Any]:
        """List all outgoing connections from ``name``.

        Matches the contract of
        ``KnowledgeGraphTool.execute("query_entity", query=name)``.
        """
        node = await self._get_entity(name)
        if node is None:
            return {
                "success": True,
                "entity": name,
                "connections": ["No connections found in the graph."],
            }
        edges = _decode_edges(node.get("edges"))
        connections = [f"[{name}] --({e['relation']})--> [{e['to']}]" for e in edges]
        return {
            "success": True,
            "entity": name,
            "connections": connections or ["No connections found in the graph."],
        }

    async def find_path(
        self,
        entity1: str,
        entity2: str,
        max_hops: int = 4,
    ) -> dict[str, Any]:
        """Find the shortest path from ``entity1`` to ``entity2``.

        BFS in Python over the entity→outgoing-edges property
        graph.  ``max_hops=4`` matches the original kgtool limit.
        """
        if entity1 == entity2:
            return {"success": True, "path": [entity1]}

        visited: set[str] = {entity1}
        # queue entries are (current_node, path_to_current_node)
        queue: deque[tuple[str, list[str]]] = deque([(entity1, [entity1])])
        examined = 0

        while queue and examined < _MAX_PATH_NODES:
            current, path = queue.popleft()
            examined += 1
            if len(path) > max_hops + 1:
                continue
            node = await self._get_entity(current)
            if node is None:
                continue
            for edge in _decode_edges(node.get("edges")):
                neighbor = edge["to"]
                if neighbor == entity2:
                    return {
                        "success": True,
                        "path": path + [neighbor],
                    }
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return {
            "success": True,
            "message": (
                f"No direct path found between {entity1} and {entity2} within {max_hops} hops."
            ),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _has_entity(self, name: str) -> bool:
        from app.db.helix import read_query, step_n_where_eq

        try:
            env = read_query(
                ("m", [step_n_where_eq("name", name), "Count"]),  # type: ignore[list-item]
            )
            res = await self._client.execute(env)
            count = res.get("m") or 0
            if isinstance(count, dict):
                count = int(count.get("count", 0))
            return int(count) > 0
        except Exception as exc:  # noqa: BLE001
            logger.debug("helix kg existence check failed: %s", exc)
            return False

    async def _create_entity(self, name: str, kind: str, user_id: str | None) -> None:
        from app.db.helix import step_add_n, write_query

        env = write_query(
            (
                "m",
                [
                    step_add_n(
                        _NODE_LABEL,
                        {
                            "name": name,
                            "kind": kind,
                            "user_id": user_id or "global",
                            "edges": "[]",
                        },
                    )
                ],
            )
        )
        await self._client.execute(env)

    async def _get_entity(self, name: str) -> dict[str, Any] | None:
        from app.db.helix import read_query, step_n_where_eq

        try:
            env = read_query(
                (
                    "m",
                    [
                        step_n_where_eq("name", name),
                        {"Values": ["name", "kind", "user_id", "edges"]},
                    ],
                ),
            )
            res = await self._client.execute(env)
            m = res.get("m")
            if not isinstance(m, dict):
                return None
            props = m.get("properties") or []
            if not props:
                return None
            return props[0] if isinstance(props[0], dict) else None
        except Exception as exc:  # noqa: BLE001
            logger.debug("helix kg entity fetch failed: %s", exc)
            return None

    async def _get_edges(self, name: str) -> list[dict[str, Any]]:
        node = await self._get_entity(name)
        if node is None:
            return []
        return _decode_edges(node.get("edges"))

    async def _set_edges(
        self, name: str, edges: list[dict[str, Any]], *, user_id: str | None
    ) -> None:
        """Update the ``edges`` property of an existing entity.

        Helix v3 doesn't expose an ``Update`` step in the public
        schema list, so we implement a property update by deleting
        the old node and re-creating it with the new edges.  This
        is correct (the node identity by ``name`` is preserved
        because the operations are scoped) but slightly heavy;
        a future optimisation could install a named ``SetProperty``
        query in the Helix schema.
        """
        from app.db.helix import step_add_n, step_n_where_eq, write_query

        old = await self._get_entity(name)
        if old is None:
            # Nothing to update; create fresh.
            await self._create_entity(name, _DEFAULT_KIND, user_id)
            old = await self._get_entity(name) or {}

        # Drop the old node.
        env_drop = write_query(
            ("d", [step_n_where_eq("name", name), "Drop"]),  # type: ignore[list-item]
            returns=["d"],
        )
        try:
            await self._client.execute(env_drop)
        except Exception:  # noqa: BLE001
            pass

        # Re-create with the new edges.
        env_add = write_query(
            (
                "m",
                [
                    step_add_n(
                        _NODE_LABEL,
                        {
                            "name": name,
                            "kind": old.get("kind", _DEFAULT_KIND),
                            "user_id": old.get("user_id", user_id or "global"),
                            "edges": json.dumps(edges, separators=(",", ":")),
                        },
                    )
                ],
            )
        )
        await self._client.execute(env_add)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _normalise_relation(relation: str) -> str:
    """Make the relation verb a safe edge label.

    Strips whitespace, uppercases, and replaces inner spaces with
    underscores.  Returns ``"RELATED_TO"`` for empty / falsy input.
    """
    if not relation:
        return "RELATED_TO"
    cleaned = relation.strip().upper().replace(" ", "_")
    return cleaned or "RELATED_TO"


def _encode_metadata(metadata: dict[str, Any]) -> str:
    """Serialise the optional metadata dict to a JSON string."""
    if not metadata:
        return "{}"
    try:
        return json.dumps(_normalise_json(metadata), separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return "{}"


def _normalise_json(value: Any) -> Any:
    """Convert non-JSON values to strings recursively."""
    if isinstance(value, dict):
        return {str(k): _normalise_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalise_json(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _decode_edges(raw: Any) -> list[dict[str, Any]]:
    """Parse the ``edges`` property of a node into a list of dicts."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [e for e in raw if isinstance(e, dict)]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return []
        if isinstance(parsed, list):
            return [e for e in parsed if isinstance(e, dict)]
    return []


__all__ = ["HelixKnowledgeGraph"]
