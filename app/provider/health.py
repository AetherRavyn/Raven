"""Provider health probing + stats — used by routing + dashboard.

v35 (2026-06-23): 9router-style live health checks for every provider.

What this module does
---------------------
- ``ProviderHealth``  — rolling per-provider status (ok / latency / last check)
- ``probe_provider``  — async HTTP probe against the provider's cheapest endpoint
- ``probe_all``       — parallel fan-out for the dashboard
- ``record_call``     — call-site hook for the orchestrator / runtime
- ``StatsStore``      — global in-memory store of call stats (success / fail /
                        latency histogram / token totals) keyed by
                        ``(provider_id, model_id)``

This module is *pure data* — it does not depend on :mod:`app.core.reinforcement_learning`
or :mod:`app.core.model_router` so the dashboard can import it without pulling
the whole swarm in.  Routing logic in :mod:`app.core.model_router` reads from
this module via :func:`app.provider.manager.ProviderManager.select_with_fallback`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable

import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


# How long a health check may take before we mark the provider degraded.
DEFAULT_PROBE_TIMEOUT_S = 1.5
# How long a health result is considered fresh.  Probes older than this
# trigger a re-check on the next dashboard reload.
HEALTH_FRESH_S = 60.0
# Max latency samples kept per provider for the rolling average.
LATENCY_WINDOW = 30


@dataclass(slots=True)
class ProviderHealth:
    """Live health for a single provider."""

    provider_id: str
    ok: bool = False
    latency_ms: float = 0.0
    error: str = ""
    last_checked: float = 0.0
    # Rolling window of recent latencies (ms) for the average.
    samples: deque[float] = field(default_factory=lambda: deque(maxlen=LATENCY_WINDOW))

    @property
    def is_fresh(self) -> bool:
        return (time.time() - self.last_checked) < HEALTH_FRESH_S

    @property
    def avg_latency_ms(self) -> float:
        if not self.samples:
            return self.latency_ms
        return sum(self.samples) / len(self.samples)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "ok": self.ok,
            "latency_ms": round(self.latency_ms, 1),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "samples": len(self.samples),
            "error": self.error,
            "last_checked": self.last_checked,
            "is_fresh": self.is_fresh,
            "status": self.status_label,
        }

    @property
    def status_label(self) -> str:
        if not self.is_fresh and self.last_checked == 0:
            return "unchecked"
        if self.ok:
            if self.avg_latency_ms < 500:
                return "healthy"
            if self.avg_latency_ms < 2000:
                return "slow"
            return "degraded"
        return "down"


def _probe_url_for(provider_id: str, base_url: str) -> str:
    """Pick the cheapest probe endpoint for *provider_id*.

    Most OpenAI-compatible providers expose ``/models``.  Local servers
    (Ollama, vLLM, etc.) have their own.  Anything we don't recognise
    falls back to ``base_url`` (a simple GET, which most providers
    reject with 401 — but 401 means "server is up" which is enough
    for the dashboard).
    """
    pid = (provider_id or "").lower()
    if pid == "ollama":
        return f"{base_url.rstrip('/')}/api/tags"
    if pid == "anthropic":
        # Anthropic rejects GET on /v1/messages; use root.
        return base_url.rstrip("/") or "https://api.anthropic.com"
    if pid == "google" or pid == "gemini":
        # Gemini's discovery endpoint requires no auth.
        return "https://generativelanguage.googleapis.com/v1beta/models"
    if pid == "xai" or pid == "grok":
        return f"{base_url.rstrip('/')}/v1/models"
    # Default OpenAI-compatible.
    return f"{base_url.rstrip('/')}/models"


async def probe_provider(
    provider_id: str,
    base_url: str = "",
    *,
    timeout: float = DEFAULT_PROBE_TIMEOUT_S,
) -> ProviderHealth:
    """Probe *provider_id* and return a fresh :class:`ProviderHealth`.

    The probe runs in a thread so the dashboard's async event loop
    never blocks on a slow / hanging upstream.
    """
    url = _probe_url_for(provider_id, base_url)
    started = time.monotonic()
    health = ProviderHealth(provider_id=provider_id)
    try:
        await asyncio.to_thread(_probe_sync, url, timeout)
        elapsed_ms = (time.monotonic() - started) * 1000.0
        health.ok = True
        health.latency_ms = elapsed_ms
        health.samples.append(elapsed_ms)
        health.last_checked = time.time()
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = (time.monotonic() - started) * 1000.0
        health.ok = False
        health.latency_ms = elapsed_ms
        health.error = str(exc)[:160]
        health.last_checked = time.time()
    _HEALTH_STORE[provider_id] = health
    return health


def _probe_sync(url: str, timeout: float) -> None:
    """Synchronous GET against *url* with a tight timeout."""
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", "RAVEN-HealthProbe/1.0")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        # Any 2xx / 4xx / 5xx means the server is reachable.  We do
        # not care about the body — just that the TCP+TLS handshake
        # + HTTP round-trip succeeded within *timeout* seconds.
        _ = resp.status


async def probe_all(
    providers: Iterable[tuple[str, str]],
    *,
    timeout: float = DEFAULT_PROBE_TIMEOUT_S,
) -> dict[str, ProviderHealth]:
    """Fan-out probes in parallel for the dashboard."""
    pairs = list(providers)
    results = await asyncio.gather(
        *(probe_provider(pid, url, timeout=timeout) for pid, url in pairs),
        return_exceptions=True,
    )
    out: dict[str, ProviderHealth] = {}
    for (pid, _url), result in zip(pairs, results):
        if isinstance(result, BaseException):
            h = ProviderHealth(provider_id=pid, ok=False, error=str(result)[:160])
            h.last_checked = time.time()
            out[pid] = h
            _HEALTH_STORE[pid] = h
        elif isinstance(result, ProviderHealth):
            out[pid] = result
    return out


# Module-level singleton so the runtime can record calls + the
# dashboard can read them without threading the store through DI.
_HEALTH_STORE: dict[str, ProviderHealth] = {}


def get_health(provider_id: str) -> ProviderHealth | None:
    return _HEALTH_STORE.get(provider_id)


def all_health() -> dict[str, ProviderHealth]:
    return dict(_HEALTH_STORE)


# ── Call stats ────────────────────────────────────────────────────────


@dataclass(slots=True)
class CallStats:
    """Rolling per-(provider, model) call stats."""

    provider_id: str
    model_id: str = ""
    calls: int = 0
    successes: int = 0
    failures: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    last_call_ts: float = 0.0
    last_error: str = ""
    latencies: deque[float] = field(default_factory=lambda: deque(maxlen=LATENCY_WINDOW))

    @property
    def success_rate(self) -> float:
        if self.calls == 0:
            return 0.0
        return self.successes / self.calls

    @property
    def avg_latency_ms(self) -> float:
        if not self.latencies:
            return 0.0
        return sum(self.latencies) / len(self.latencies)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "calls": self.calls,
            "successes": self.successes,
            "failures": self.failures,
            "success_rate": round(self.success_rate, 3),
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "last_call_ts": self.last_call_ts,
            "last_error": self.last_error,
        }


_STATS_STORE: dict[tuple[str, str], CallStats] = {}


def record_call(
    provider_id: str,
    model_id: str,
    *,
    ok: bool,
    latency_ms: float = 0.0,
    tokens_in: int = 0,
    tokens_out: int = 0,
    error: str = "",
) -> CallStats:
    """Record the outcome of one LLM call.

    Called by the runtime after every dispatch so the dashboard can
    show "X calls today, Y success rate" without scraping logs.
    """
    key = (provider_id, model_id)
    stats = _STATS_STORE.get(key)
    if stats is None:
        stats = CallStats(provider_id=provider_id, model_id=model_id)
        _STATS_STORE[key] = stats
    stats.calls += 1
    if ok:
        stats.successes += 1
    else:
        stats.failures += 1
        if error:
            stats.last_error = error[:200]
    stats.tokens_in += max(0, tokens_in)
    stats.tokens_out += max(0, tokens_out)
    stats.last_call_ts = time.time()
    if latency_ms > 0:
        stats.latencies.append(latency_ms)
    return stats


def get_stats(provider_id: str, model_id: str = "") -> CallStats | None:
    if model_id:
        return _STATS_STORE.get((provider_id, model_id))
    out: list[CallStats] = []
    for (pid, mid), s in _STATS_STORE.items():
        if pid == provider_id:
            out.append(s)
    if not out:
        return None
    # Aggregate across models for the provider-level summary.
    agg = CallStats(provider_id=provider_id, model_id="*")
    for s in out:
        agg.calls += s.calls
        agg.successes += s.successes
        agg.failures += s.failures
        agg.tokens_in += s.tokens_in
        agg.tokens_out += s.tokens_out
        for lat in s.latencies:
            agg.latencies.append(lat)
    agg.last_call_ts = max((s.last_call_ts for s in out), default=0.0)
    agg.last_error = next((s.last_error for s in out if s.last_error), "")
    return agg


def all_stats() -> list[CallStats]:
    """Per-model stats flattened + provider-level aggregates appended."""
    rows = list(_STATS_STORE.values())
    # Provider-level rollups.
    by_provider: dict[str, CallStats] = {}
    for s in rows:
        agg = by_provider.get(s.provider_id)
        if agg is None:
            agg = CallStats(provider_id=s.provider_id, model_id="*")
            by_provider[s.provider_id] = agg
        agg.calls += s.calls
        agg.successes += s.successes
        agg.failures += s.failures
        agg.tokens_in += s.tokens_in
        agg.tokens_out += s.tokens_out
        for lat in s.latencies:
            agg.latencies.append(lat)
        agg.last_call_ts = max(agg.last_call_ts, s.last_call_ts)
    return [*rows, *by_provider.values()]


def reset_for_tests() -> None:
    _HEALTH_STORE.clear()
    _STATS_STORE.clear()
