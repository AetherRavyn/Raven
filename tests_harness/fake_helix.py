"""In-process fake for ``app.db.helix.HelixClient``.

Purpose
-------
The live HelixDB integration tests skip when no gateway is running
on ``localhost:6969`` or ``localhost:8080``.  That skips 33 tests
in CI.  This module provides monkey-patches that turn any
:class:`HelixClient` constructed during a test into an in-memory
stand-in.

How it is wired
---------------
A pytest autouse fixture in ``tests/conftest.py`` patches the
relevant methods on :class:`HelixClient` so any instance created
during the test (by test fixtures, by ``HelixMemoryStore.__init__``,
by ``HelixKnowledgeGraph.__init__``) becomes a fake.  The fake
records every envelope and maintains an in-memory node store so
``count_nodes`` / ``AddN`` / ``AddE`` round-trip in tests works
without a running gateway.

The module lives at the top level (``tests_harness/``) rather
than under ``tests/`` because a third-party ``tests`` package
installed in the venv (from a transitive ML dependency) shadows
the local ``tests/`` directory when Python resolves imports.

Public API
----------
* :func:`install_fake` — patches ``HelixClient``'s methods in-place
  via a ``monkeypatch`` fixture.  Called from the conftest fixture.

This module is test infrastructure.  It is *not* imported by
production code.
"""
from __future__ import annotations

from typing import Any

from app.db.helix import HelixClient, HelixHealth, QueryResult


# Per-instance state storage; mapping ``id(instance) -> dict``.
# HelixClient is ``@dataclass(slots=True)`` so we cannot add new
# instance attributes; this class-level dict is the workaround.
_state: "dict[int, dict[str, Any]]" = {}


def _state_dict(client: Any) -> dict[str, Any]:
    return _state.setdefault(id(client), {
        "nodes": {},
        "envelopes": [],
        "raise_on": {},
        "responses": {},
    })


# ── Patched method implementations ──────────────────────────────────


async def _fake_close(self: Any) -> None:
    # No real I/O; nothing to close.
    return None


async def _fake_health(self: Any) -> HelixHealth:
    return HelixHealth(
        healthy=True,
        service="helix-fake",
        latency_ms=0.0,
        error=None,
    )


async def _fake_is_available(self: Any) -> bool:
    return True


async def _fake_ping(self: Any) -> bool:
    return True


async def _fake_execute(
    self: Any,
    envelope: dict[str, Any],
    *,
    request_type: str | None = None,
) -> QueryResult:
    if request_type is not None:
        envelope = {**envelope, "request_type": request_type}
    rt = str(envelope.get("request_type", ""))
    state = _state_dict(self)
    state["envelopes"].append(envelope)

    # Error injection.
    if rt in state["raise_on"]:
        raise state["raise_on"][rt]

    # Canned response.
    if rt in state["responses"]:
        return QueryResult(
            data=state["responses"][rt],
            latency_ms=0.0,
            request_type=rt,
        )

    # Reject envelopes that don't look like Helix queries.  Real
    # Helix rejects these with a 400 + HelixQueryError; the test
    # `test_invalid_query_raises` depends on this behaviour.
    from app.db.helix import HelixQueryError

    if not isinstance(envelope, dict) or "query" not in envelope:
        raise HelixQueryError(
            "fake helix: malformed envelope (missing 'query' key)",
            status=400,
            body={"reason": "missing query"},
        )

    # Walk the envelope's query steps to update the node store
    # and synthesise a return value.
    queries = envelope.get("query", {}).get("queries", []) or []
    returns: list[str] = envelope.get("query", {}).get("returns", []) or []
    result_data: dict[str, Any] = {}

    for i, q in enumerate(queries):
        query_obj = q.get("Query", q)
        name = query_obj.get("name") or (returns[i] if i < len(returns) else "result")
        steps = query_obj.get("steps", []) or []
        payload = _run_steps(self, steps)
        result_data[name] = payload

    return QueryResult(
        data=result_data,
        latency_ms=0.0,
        request_type=rt,
    )


def _run_steps(self: Any, steps: list[Any]) -> Any:
    """Apply a sequence of Helix steps against the in-memory store.

    Supports the step shapes the production code emits:
    ``{"AddN": {...}}``, ``{"AddE": {...}}``, ``{"NWhere": {...}}``,
    ``"Count"``, ``"Drop"``, ``{"SearchVector": ...}``, ``"Limit"``,
    and ``{"N": ...}`` (the bare-node step).

    Each step operates on the *previous* step's output (a Helix
    pipeline semantics), so ``[NWhere(id=x), Count]`` counts only
    the nodes that passed the filter, not the entire store.
    """
    # The first step's input is "the whole store" — represented as
    # the flat list of all nodes across labels.
    pipeline: Any = None
    for step in steps:
        pipeline = _run_step(self, step, pipeline)
    return pipeline if pipeline is not None else {}


def _run_step(self: Any, step: Any, prev: Any) -> Any:
    state = _state_dict(self)
    nodes = state["nodes"]
    if isinstance(step, str):
        if step == "Count":
            # Count what the previous step produced.  If previous
            # is a list, that's the count.  If it's the whole
            # store (None), count everything.
            if isinstance(prev, list):
                return {"count": len(prev)}
            if isinstance(prev, dict):
                return prev  # already a count dict
            return {"count": sum(len(v) for v in nodes.values())}
        if step == "Drop":
            # Drop what the previous step produced.  Production
            # code pairs Drop with an NWhere filter; the matched
            # nodes are in `prev`.
            dropped = 0
            if isinstance(prev, list):
                # Remove from any label bucket whose value matches
                # any node in prev (compared by identity-of-fields).
                target_keys = set()
                for node in prev:
                    if isinstance(node, dict):
                        target_keys.add(_node_key(node))
                for label in list(nodes.keys()):
                    new_list = [
                        n for n in nodes[label]
                        if _node_key(n) not in target_keys
                    ]
                    dropped += len(nodes[label]) - len(new_list)
                    nodes[label] = new_list
            return {"dropped": dropped}
        if step == "Limit":
            # Limit N — no-op for our purposes.
            return prev if prev is not None else []
        # Unknown string step — pass through.
        return prev if prev is not None else {}
    if not isinstance(step, dict):
        return prev if prev is not None else {}
    # AddN: create a node under a label.
    if "AddN" in step:
        spec = step["AddN"]
        label = str(spec.get("label", "Node"))
        props = _props_to_dict(spec.get("properties"))
        nodes.setdefault(label, []).append(props)
        return props
    # AddE: create an edge (we do not enforce referential integrity).
    if "AddE" in step:
        spec = step["AddE"]
        label = str(spec.get("label", "Edge"))
        props = _props_to_dict(spec.get("properties"))
        nodes.setdefault(label, []).append(props)
        return props
    # NWhere: filter nodes that match; returns the matching set.
    if "NWhere" in step:
        n_where = step["NWhere"]
        eq = n_where.get("Eq") if isinstance(n_where, dict) else None
        if isinstance(eq, list) and len(eq) >= 2:
            field_name = str(eq[0])
            value = _unwrap_literal(eq[1])
            # Operate on the previous pipeline, or on the whole
            # store if there's no pipeline yet.
            source: list[Any]
            if isinstance(prev, list):
                source = prev
            else:
                source = [n for ns in nodes.values() for n in ns]
            return [n for n in source if n.get(field_name) == value]
        return prev if isinstance(prev, list) else []
    # SearchVector: no-op (production runs vector search in Python).
    if "SearchVector" in step:
        return []
    # N: the "all nodes" step.
    if "N" in step:
        return [n for ns in nodes.values() for n in ns]
    # Values: extract a field from the previous step's items.
    if "Values" in step:
        spec = step["Values"]
        field_names: list[str] = []
        if isinstance(spec, dict):
            # Spec can be ``{"field": "x"}`` (single) or a list of
            # names.  In the production code path we see a *list*
            # of field names (the projection list).
            if isinstance(spec.get("field"), str):
                field_names = [spec["field"]]
            elif "fields" in spec and isinstance(spec["fields"], list):
                field_names = list(spec["fields"])
            elif "name" in spec:
                field_names = [spec["name"]]
        # Fallback: spec itself might be a list of names.
        if not field_names and isinstance(spec, list):
            field_names = [str(x) for x in spec]

        if isinstance(prev, list):
            if len(field_names) == 1:
                # Single-field projection: return a flat list.
                return [n.get(field_names[0]) for n in prev]
            # Multi-field projection: return the Helix "properties"
            # envelope that ``_list_nodes`` consumes.
            return {
                "properties": [
                    {fn: n.get(fn) for fn in field_names}
                    for n in prev
                ]
            }
        return prev if prev is not None else []
    return prev if prev is not None else {}


async def _fake_count_nodes(self: Any, label: str) -> int:
    return len(_state_dict(self)["nodes"].get(label, ()))


# ── Static helpers ──────────────────────────────────────────────────


def _props_to_dict(props: Any) -> dict[str, Any]:
    """Convert Helix's ``[[name, {Value: literal}], ...]`` form to a dict."""
    if not isinstance(props, list):
        if isinstance(props, dict):
            return {
                str(k): _unwrap_literal(v)
                for k, v in props.items()
            }
        return {}
    out: dict[str, Any] = {}
    for entry in props:
        if isinstance(entry, list) and len(entry) >= 2:
            name = str(entry[0])
            value = _unwrap_literal(entry[1])
            out[name] = value
    return out


def _unwrap_literal(lit: Any) -> Any:
    """Unwrap Helix literal tags (``{"String": "x"}``, ``{"I64": n}``)."""
    if not isinstance(lit, dict):
        return lit
    if "Value" in lit and len(lit) == 1:
        return _unwrap_literal(lit["Value"])
    for tag in ("String", "I64", "F64", "Boolean", "Bytes"):
        if tag in lit:
            return lit[tag]
    if "StringArray" in lit:
        return list(lit["StringArray"])
    if "I64Array" in lit:
        return list(lit["I64Array"])
    if "F32Array" in lit:
        return list(lit["F32Array"])
    if "Array" in lit:
        return [_unwrap_literal(x) for x in lit["Array"]]
    if "Object" in lit:
        return {
            str(k): _unwrap_literal(v)
            for k, v in lit["Object"].items()
        }
    return lit


def _node_key(node: dict[str, Any]) -> tuple[Any, ...]:
    """Build a stable identity tuple for a node dict.

    Used by Drop to remove the same nodes that NWhere matched.
    Real Helix uses node IDs internally; we approximate by
    hashing the field values (excluding mutable bookkeeping like
    ``edges`` and ``embedding``).
    """
    return tuple(sorted(
        (k, v) for k, v in node.items()
        if k not in ("edges", "embedding")
    ))


# ── Wiring ──────────────────────────────────────────────────────────


# Mapping of method name -> patched function.  Order matters: we
# use these for both the production module and the conftest fixture.
PATCHES: dict[str, Any] = {
    "close": _fake_close,
    "health": _fake_health,
    "is_available": _fake_is_available,
    "ping": _fake_ping,
    "execute": _fake_execute,
    "count_nodes": _fake_count_nodes,
}


def install_fake(monkeypatch: Any) -> None:
    """Patch ``HelixClient`` methods so every instance is in-process.

    This patches the *methods on the class*, not the constructor.
    Any ``HelixClient`` instance — regardless of when it was
    constructed — gets the patched methods.  This is necessary
    because production code (``HelixMemoryStore.__init__``) creates
    a HelixClient itself and we can't intercept that construction
    via __init__ without losing slots-based attribute access.
    """
    for name, fn in PATCHES.items():
        monkeypatch.setattr(HelixClient, name, fn)
    # Eagerly clear any per-instance state from prior tests.
    _state.clear()


__all__ = [
    "install_fake",
]
