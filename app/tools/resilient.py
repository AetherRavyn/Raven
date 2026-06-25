"""Resilient tool base — Phase 4.1, 4.2, 4.5, 4.6.

A drop-in upgrade to :class:`app.tools.base.BaseTool` that gives every
tool:

- **Metadata**: ``risk_level``, ``requires_approval``, ``cost_tier``,
  ``cacheable``, ``cache_ttl_s``, ``side_effect``, ``rate_limit_per_min``,
  ``timeout_s``, ``retryable``, ``dry_run_supported``.
- **Watchdog**: ``timeout_s`` enforced via ``asyncio.wait_for``.
- **Retry**: only if ``retryable=True``.
- **Circuit breaker**: per-tool instance; opens after 3 timeouts in
  5 min, recovers after 10 min.
- **Audit outbox**: every call is recorded *before* and *after* in the
  audit log via the envelope bridge.
- **Dry-run**: ``dry_run=True`` returns the call it *would* make
  without firing the side effect.
- **Cache**: ``cacheable=True`` stores the result by args-hash.

This is the "every tool has a fragility contract" half of Phase 4.
The other half (manifests, registry) is in :mod:`app.tools.manifest`.

Tools opt in by subclassing :class:`BaseResilientTool` instead of
:class:`app.tools.base.BaseTool`. Existing tools keep working
unchanged — this class is purely additive.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, ClassVar

from app.tools.base import (
    BaseTool,
    ToolCapability,
    ToolParameter,
    ToolSchema,
)
from app.tools.resilience import (
    ToolCircuitBreaker,
    standardize_error,
)

logger = logging.getLogger(__name__)


# ── Tool metadata ──────────────────────────────────────────────────


@dataclass(slots=True)
class ToolMetadata:
    """Per-tool fragility contract — read at runtime by the executor."""

    risk_level: str = "low"           # low | medium | high | critical
    requires_approval: bool = False   # must be approved before running
    cost_tier: str = "low"            # low | medium | high (for cost router)
    cacheable: bool = False           # cache results across identical calls
    cache_ttl_s: float = 60.0         # cache TTL when cacheable=True
    side_effect: bool = False         # has external side effect (audit first)
    rate_limit_per_min: int = 0       # 0 = no limit
    timeout_s: float = 30.0           # watchdog
    retryable: bool = True            # retry on failure?
    dry_run_supported: bool = False   # can be invoked with dry_run=True

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "cost_tier": self.cost_tier,
            "cacheable": self.cacheable,
            "cache_ttl_s": self.cache_ttl_s,
            "side_effect": self.side_effect,
            "rate_limit_per_min": self.rate_limit_per_min,
            "timeout_s": self.timeout_s,
            "retryable": self.retryable,
            "dry_run_supported": self.dry_run_supported,
        }


# ── Optional outbox + rate limit + cache helpers ────────────────────


def _args_hash(args: dict[str, Any]) -> str:
    """Stable hash for tool-call args.  Sorts keys for determinism."""
    raw = json.dumps(args, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class _RateGate:
    """Tiny per-tool rate gate: max N calls per 60 s."""

    def __init__(self, max_per_min: int) -> None:
        if max_per_min < 1:
            raise ValueError("max_per_min must be ≥ 1")
        self._max = max_per_min
        self._window: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.time()
            self._window = [t for t in self._window if now - t < 60.0]
            if len(self._window) >= self._max:
                wait = 60.0 - (now - self._window[0])
                if wait > 0:
                    await asyncio.sleep(wait)
            self._window.append(time.time())


# ── BaseResilientTool ───────────────────────────────────────────────


class BaseResilientTool(BaseTool):
    """A tool with a fragility contract.

    Subclass and implement :meth:`run` (or override :meth:`execute`).
    Then set class attribute ``metadata`` and the tool will:

    * honour ``timeout_s`` via ``asyncio.wait_for``,
    * open a circuit breaker after repeated timeouts,
    * rate-limit itself,
    * cache results when ``cacheable=True``,
    * audit every call via the envelope bridge,
    * support ``dry_run=True`` when ``dry_run_supported=True``.

    Existing tools that override only ``execute`` keep working —
    :meth:`run` falls through to :meth:`execute` by default.
    """

    group: ClassVar[str] = "ungrouped"
    # Subclasses override this.
    metadata: ClassVar[ToolMetadata] = ToolMetadata()

    def __init__(self) -> None:
        self._breaker = ToolCircuitBreaker(
            failure_threshold=3,
            cooldown_seconds=600.0,  # 10 min
        )
        self._rate_gate: _RateGate | None = (
            _RateGate(self.metadata.rate_limit_per_min)
            if self.metadata.rate_limit_per_min > 0
            else None
        )
        self._cache: dict[str, tuple[float, Any]] = {}
        # Stats for observability.
        self._stats = {
            "calls": 0,
            "failures": 0,
            "timeouts": 0,
            "cache_hits": 0,
            "circuit_open_rejects": 0,
            "rate_limit_waits": 0,
        }

    # ── Abstract surface ─────────────────────────────────────────

    def get_name(self) -> str:
        return self.__class__.__name__

    def get_description(self) -> str:
        return ""

    def get_schema(self) -> ToolSchema:
        return ToolSchema(name=self.get_name(), description=self.get_description())

    def get_capabilities(self) -> ToolCapability:
        return ToolCapability(
            risk_level=self.metadata.risk_level,
        )

    # ── The hot path: execute() ──────────────────────────────────

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        """Public entry point — goes through the resilience envelope.

        Subclasses should override :meth:`_do_run` (not :meth:`execute`)
        so the resilience layer is always applied.
        """
        return await self._resilient_execute(kwargs)

    async def _do_run(self, **kwargs: Any) -> dict[str, Any]:
        """The actual implementation — subclasses MUST override this.

        For backwards-compatibility with tools that override
        :meth:`execute` directly, this default falls through to a
        super() call which raises NotImplementedError unless the
        subclass has overridden execute().
        """
        # Detect "subclass overrode execute" by checking the MRO.
        for klass in type(self).__mro__:
            if klass is BaseResilientTool:
                continue
            if "execute" in klass.__dict__:
                # Subclass overrode execute — call it (it's their impl).
                return await klass.execute(self, **kwargs)
        # Truly abstract — raise.
        raise NotImplementedError(
            f"{type(self).__name__} must override _do_run or execute"
        )

    async def _resilient_execute(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Wraps _run_impl with watchdog + breaker + cache + audit."""
        name = self.get_name()
        self._stats["calls"] += 1
        dry_run = bool(kwargs.pop("dry_run", False))

        # Dry-run path: return the call that *would* be made.
        if dry_run and self.metadata.dry_run_supported:
            return {
                "success": True,
                "dry_run": True,
                "tool": name,
                "would_call_with": dict(kwargs),
            }

        # Circuit breaker gate.
        if not self._breaker.allow_request():
            self._stats["circuit_open_rejects"] += 1
            return standardize_error(
                tool_name=name,
                error=RuntimeError("circuit breaker is OPEN"),
                context="tool temporarily disabled due to repeated failures",
                recoverable=True,
            )

        # Rate gate.
        if self._rate_gate is not None:
            self._stats["rate_limit_waits"] += 1
            await self._rate_gate.acquire()

        # Cache lookup.
        key: str | None = None
        if self.metadata.cacheable and not dry_run:
            key = _args_hash(kwargs)
            cached = self._cache.get(key)
            if cached is not None:
                expires_at, payload = cached
                if expires_at > time.time():
                    self._stats["cache_hits"] += 1
                    return payload
                self._cache.pop(key, None)

        # Audit outbox — record before execution if side effect.
        audit_id = self._audit_before(name, kwargs)
        started = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self._do_run(**kwargs),
                timeout=self.metadata.timeout_s,
            )
        except asyncio.TimeoutError:
            self._stats["timeouts"] += 1
            self._breaker.record_failure()
            elapsed_ms = int((time.monotonic() - started) * 1000)
            err = standardize_error(
                tool_name=name,
                error=TimeoutError(f"timed out after {self.metadata.timeout_s}s"),
                context=f"timeout_s={self.metadata.timeout_s}",
                recoverable=True,
            )
            self._audit_after(name, audit_id, success=False, error=err, elapsed_ms=elapsed_ms)
            return err
        except Exception as exc:  # noqa: BLE001
            self._stats["failures"] += 1
            self._breaker.record_failure()
            elapsed_ms = int((time.monotonic() - started) * 1000)
            err = standardize_error(
                tool_name=name,
                error=exc,
                context=f"{type(exc).__name__}",
                recoverable=self.metadata.retryable,
            )
            self._audit_after(name, audit_id, success=False, error=err, elapsed_ms=elapsed_ms)
            return err

        # Success path.
        self._breaker.record_success()
        elapsed_ms = int((time.monotonic() - started) * 1000)

        # Cache store.
        if self.metadata.cacheable and key is not None:
            self._cache[key] = (time.time() + self.metadata.cache_ttl_s, result)

        self._audit_after(name, audit_id, success=True, error=None, elapsed_ms=elapsed_ms)
        return result

    # ── Audit helpers ─────────────────────────────────────────────

    def _audit_before(self, name: str, kwargs: dict[str, Any]) -> str | None:
        if not self.metadata.side_effect:
            return None
        try:
            from app.core.audit import AuditEvent, AuditKind
            from app.core.audit.log import get_audit_log

            evt = AuditEvent(
                kind=AuditKind.TOOL_CALL,
                actor="tool",
                action=f"{name}.before",
                target=name,
                metadata={"kwargs": _safe_truncate(kwargs)},
            )
            return get_audit_log().record(evt)
        except Exception as exc:  # noqa: BLE001
            logger.debug("audit outbox (before) failed: %s", exc)
            return None

    def _audit_after(
        self,
        name: str,
        audit_id: str | None,
        *,
        success: bool,
        error: dict[str, Any] | None,
        elapsed_ms: int,
    ) -> None:
        if audit_id is None:
            return
        try:
            from app.core.audit import AuditEvent, AuditKind
            from app.core.audit.log import get_audit_log

            evt = AuditEvent(
                kind=AuditKind.TOOL_CALL,
                actor="tool",
                action=f"{name}.after",
                target=name,
                success=success,
                duration_ms=elapsed_ms,
                detail=(error or {}).get("error") if error else None,
                metadata={
                    "audit_id": audit_id,
                    "elapsed_ms": elapsed_ms,
                    "error_type": (error or {}).get("error_type"),
                },
            )
            get_audit_log().record(evt)
        except Exception as exc:  # noqa: BLE001
            logger.debug("audit outbox (after) failed: %s", exc)

    # ── Stats ─────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        return {
            **self._stats,
            "circuit_state": self._breaker.state,
            "metadata": self.metadata.to_dict(),
        }


def _safe_truncate(obj: Any, *, max_len: int = 200) -> Any:
    """Truncate string leaves for the audit log; never raise."""
    try:
        s = json.dumps(obj, default=str)
    except Exception:  # noqa: BLE001
        return "<unserialisable>"
    if len(s) > max_len:
        return s[:max_len] + "…"
    return obj


__all__ = [
    "ToolMetadata",
    "BaseResilientTool",
]
