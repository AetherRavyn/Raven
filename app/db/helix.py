"""HelixDB Python client — async HTTP wrapper for the AetherRavyn graph+vector store.

This client is the single abstraction over HelixDB. All higher-level modules
(knowledge graph, memory manager, planner persistence) import from here and
never touch raw HTTP or the JSON query AST.

The client targets the HelixDB local gateway (default ``http://localhost:6969``
via the ``helix`` CLI, or ``http://localhost:8080`` when running the
``ghcr.io/helixdb/enterprise-dev`` image directly with ``--network host``).

It is intentionally NOT a 1:1 mirror of the TypeScript SDK. We provide a
typed, async-first API and let the SDK grow alongside the features we use.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Final

import httpx

logger = logging.getLogger(__name__)

# HelixDB request_type values
_REQUEST_TYPE_READ: Final = "read"
_REQUEST_TYPE_WRITE: Final = "write"

# Default ports: helix CLI uses 6969, raw docker image uses 8080.
DEFAULT_HELIX_URL: Final = os.environ.get("SARAS_HELIX_URL", "http://localhost:6969")
_FALLBACK_HELIX_URL: Final = "http://localhost:8080"

# Connection / retry defaults
DEFAULT_TIMEOUT_S: Final = 10.0
DEFAULT_CONNECT_TIMEOUT_S: Final = 2.0
MAX_RETRIES: Final = 3
RETRY_BACKOFF_S: Final = 0.5


class HelixError(Exception):
    """Base error raised by the HelixDB client."""


class HelixConnectionError(HelixError):
    """Raised when the gateway is unreachable."""


class HelixQueryError(HelixError):
    """Raised when the gateway returns a query-level error."""

    def __init__(self, message: str, *, status: int, body: dict[str, Any]) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass(slots=True)
class HelixHealth:
    """Result of a HelixDB health probe."""

    healthy: bool
    service: str
    latency_ms: float
    error: str | None = None


@dataclass(slots=True)
class QueryResult:
    """A single query invocation result.

    Helix returns a JSON object whose keys are the names from the
    ``returning([...])`` call. We keep it as a dict plus a typed
    ``get(name, default)`` helper.
    """

    data: dict[str, Any]
    latency_ms: float
    request_type: str

    def get(self, name: str, default: Any = None) -> Any:
        return self.data.get(name, default)

    def __bool__(self) -> bool:
        return bool(self.data)


# ---------------------------------------------------------------------------
# Query AST builders
#
# HelixDB queries are posted as JSON envelopes. We build the envelope with
# small typed helpers so call-sites don't handcraft dicts of dicts.
# ---------------------------------------------------------------------------


def read_query(
    *named_queries: tuple[str, list[dict[str, Any]]],
    returns: list[str] | None = None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a ``read`` request envelope.

    Example::

        q = read_query(
            ("user", [{"NWhere": {"Eq": ["username", {"String": "alice"}]}}]),
            returns=["user"],
        )
    """
    queries = [
        {"Query": {"name": name, "steps": steps, "condition": None}}
        for name, steps in named_queries
    ]
    return {
        "request_type": _REQUEST_TYPE_READ,
        "query": {
            "queries": queries,
            "returns": returns or [n for n, _ in named_queries],
        },
        "parameters": parameters or {},
    }


def write_query(
    *named_queries: tuple[str, list[dict[str, Any]]],
    returns: list[str] | None = None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a ``write`` request envelope (addN / addE / set / etc.)."""
    queries = [
        {"Query": {"name": name, "steps": steps, "condition": None}}
        for name, steps in named_queries
    ]
    return {
        "request_type": _REQUEST_TYPE_WRITE,
        "query": {
            "queries": queries,
            "returns": returns or [n for n, _ in named_queries],
        },
        "parameters": parameters or {},
    }


# Common step helpers — build the small JSON shapes Helix expects.
def step_add_n(label: str, properties: dict[str, Any]) -> dict[str, Any]:
    """Build an ``AddN`` step.

    Per the Helix wire format, ``properties`` is a list of
    ``[name, {"Value": <PropertyValue>}]`` tuples, not a plain dict.
    """
    return {"AddN": {"label": label, "properties": _prop_entries(properties)}}


def step_add_e(
    from_var: str,
    to_var: str,
    label: str,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "AddE": {
            "label": label,
            "from": {"Var": from_var},
            "to": {"Var": to_var},
        }
    }
    if properties:
        step["AddE"]["properties"] = _prop_entries(properties)
    return step


def step_n_where_eq(field: str, value: Any) -> dict[str, Any]:
    return {"NWhere": {"Eq": [field, _literal(value)]}}


def step_count() -> Any:
    return "Count"


def _prop_entries(d: dict[str, Any]) -> list[list[Any]]:
    """Convert a Python dict to a list of ``[name, PropertyInput]`` tuples.

    Helix encodes property assignments as a sequence of tuples so the server
    can distinguish ``Value`` (literal) from ``Expr`` (computed) without
    relying on object key order.
    """
    return [[k, {"Value": _literal(v)}] for k, v in d.items()]


def _props(d: dict[str, Any]) -> dict[str, Any]:
    """Deprecated: kept for any callers using the dict-style envelope.

    Prefer ``_prop_entries`` (the documented Helix format).
    """
    return {k: _literal(v) for k, v in d.items()}


def _literal(v: Any) -> dict[str, Any]:
    """Wrap a Python value in Helix's literal type tag."""
    if isinstance(v, bool):
        return {"Boolean": v}
    if isinstance(v, int):
        return {"I32": v}
    if isinstance(v, float):
        return {"F32": v}
    if isinstance(v, str):
        return {"String": v}
    if isinstance(v, list):
        return {"Array": [_literal(x) for x in v]}
    if isinstance(v, dict):
        return {"Object": {k: _literal(x) for k, x in v.items()}}
    msg = f"unsupported literal type: {type(v).__name__}"
    raise TypeError(msg)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class HelixClient:
    """Async client for a local HelixDB gateway.

    Usage::

        async with HelixClient() as hx:
            ok = await hx.health()
            res = await hx.execute(read_query(("user_count", [step_count()])))

    The client transparently retries transient failures and times out long
    queries. It is a singleton-friendly object: build it once and share it.
    """

    base_url: str = DEFAULT_HELIX_URL
    timeout_s: float = DEFAULT_TIMEOUT_S
    connect_timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S
    max_retries: int = MAX_RETRIES
    fallback_url: str | None = _FALLBACK_HELIX_URL
    _client: httpx.AsyncClient | None = field(default=None, init=False, repr=False)
    _owns_client: bool = field(default=True, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def __aenter__(self) -> "HelixClient":
        await self._ensure_client()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout_s, connect=self.connect_timeout_s),
                headers={"content-type": "application/json"},
                limits=httpx.Limits(max_connections=32, max_keepalive_connections=8),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    @asynccontextmanager
    async def lifespan(self) -> AsyncIterator[None]:
        """Context manager for ad-hoc usage without `async with`."""
        await self._ensure_client()
        try:
            yield
        finally:
            await self.close()

    # ------------------------------------------------------------------
    # Health & stats
    # ------------------------------------------------------------------

    async def health(self) -> HelixHealth:
        """Probe the gateway /health endpoint."""
        client = await self._ensure_client()
        t0 = time.perf_counter()
        try:
            r = await client.get("/health")
        except httpx.HTTPError as e:
            return HelixHealth(
                healthy=False,
                service="unknown",
                latency_ms=(time.perf_counter() - t0) * 1000,
                error=str(e),
            )
        dt = (time.perf_counter() - t0) * 1000
        if r.status_code != 200:
            return HelixHealth(
                healthy=False,
                service="unknown",
                latency_ms=dt,
                error=f"HTTP {r.status_code}: {r.text[:200]}",
            )
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        return HelixHealth(
            healthy=bool(body.get("healthy", True)),
            service=str(body.get("service", "helix")),
            latency_ms=dt,
        )

    async def is_available(self) -> bool:
        h = await self.health()
        return h.healthy

    # ------------------------------------------------------------------
    # Query execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        envelope: dict[str, Any],
        *,
        request_type: str | None = None,
    ) -> QueryResult:
        """POST a query envelope to ``/v1/query``.

        ``request_type`` overrides the envelope's ``request_type`` when
        set, useful for callers that build the envelope themselves.
        """
        if request_type is not None:
            envelope = {**envelope, "request_type": request_type}

        client = await self._ensure_client()
        t0 = time.perf_counter()
        last_err: Exception | None = None

        # Try primary then fallback
        urls = [self.base_url]
        if self.fallback_url and self.fallback_url != self.base_url:
            urls.append(self.fallback_url)

        for url_attempt in urls:
            for attempt in range(1, self.max_retries + 1):
                try:
                    if url_attempt != self.base_url and self._client is not None:
                        await self._client.aclose()
                        self._client = None
                        self._client = httpx.AsyncClient(
                            base_url=url_attempt,
                            timeout=httpx.Timeout(self.timeout_s, connect=self.connect_timeout_s),
                            headers={"content-type": "application/json"},
                        )
                        client = self._client
                    if client is None:
                        raise RuntimeError("helix client not initialized")

                    r = await client.post("/v1/query", json=envelope)
                except httpx.HTTPError as e:
                    last_err = e
                    logger.warning(
                        "helix POST failed (attempt %d/%d, url=%s): %s",
                        attempt,
                        self.max_retries,
                        url_attempt,
                        e,
                    )
                    if attempt < self.max_retries:
                        await asyncio.sleep(RETRY_BACKOFF_S * attempt)
                        continue
                    break  # try next url

                dt = (time.perf_counter() - t0) * 1000
                if r.status_code != 200:
                    body: dict[str, Any] = {}
                    try:
                        body = r.json()
                    except Exception:  # noqa: BLE001
                        body = {"raw": r.text[:500]}
                    raise HelixQueryError(
                        f"helix query failed: HTTP {r.status_code}",
                        status=r.status_code,
                        body=body,
                    )
                payload = r.json() if r.content else {}
                if not isinstance(payload, dict):
                    payload = {"result": payload}
                return QueryResult(
                    data=payload,
                    latency_ms=dt,
                    request_type=str(envelope.get("request_type", "?")),
                )

        msg = f"helix unreachable: {last_err}"
        raise HelixConnectionError(msg) from last_err

    # ------------------------------------------------------------------
    # Convenience for the most common operations
    # ------------------------------------------------------------------

    async def count_nodes(self, label: str) -> int:
        """Return the number of nodes with the given label."""
        res = await self.execute(
            read_query(
                ("c", [{"NWhere": {"Eq": ["$label", {"String": label}]}}, "Count"]),  # type: ignore[list-item]
                returns=["c"],
            )
        )
        c = res.get("c") or {}
        # Helix returns either {"count": N} or just N depending on version
        if isinstance(c, dict):
            return int(c.get("count", 0))
        return int(c or 0)

    async def ping(self) -> bool:
        try:
            return (await self.health()).healthy
        except Exception:  # noqa: BLE001
            return False


# Module-level singleton
_default_client: HelixClient | None = None


def get_client() -> HelixClient:
    """Return a process-wide HelixClient (created on first use)."""
    global _default_client
    if _default_client is None:
        _default_client = HelixClient()
    return _default_client


async def close_default_client() -> None:
    global _default_client
    if _default_client is not None:
        await _default_client.close()
        _default_client = None


__all__ = [
    "DEFAULT_HELIX_URL",
    "HelixClient",
    "HelixConnectionError",
    "HelixError",
    "HelixHealth",
    "HelixQueryError",
    "QueryResult",
    "close_default_client",
    "get_client",
    "read_query",
    "step_add_e",
    "step_add_n",
    "step_count",
    "step_n_where_eq",
    "write_query",
]
