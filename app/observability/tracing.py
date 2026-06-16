"""OpenTelemetry tracing setup for SARAS (A5).

This module provides a single :func:`init_tracing` entry point that
wires up an OTel tracer provider, a resource describing the
service, and the right exporter for the deployment.

The default exporter is OTLP/HTTP, the same one Jaeger / Tempo /
Honeycomb accept.  An :class:`InMemorySpanExporter` is provided
for tests.

Design notes
------------

- **Lazy**: nothing is configured until :func:`init_tracing` is
  called.  Tests that don't care about tracing pay zero cost.
- **Idempotent**: calling :func:`init_tracing` twice is safe; the
  second call returns the existing provider.
- **Env-driven**: every deployment knob has a sensible default and
  can be overridden via ``SARAS_OTEL_*`` env vars.  No code change
  is needed to point at a different collector.
- **Auto-instrumentation**: ``init_tracing`` can install httpx
  instrumentation so every outbound HTTP call becomes a span.
  Disable with ``SARAS_OTEL_INSTRUMENT_HTTPX=false``.

The module also exports a tiny :func:`traced` decorator and a
context-manager :func:`span` helper for ad-hoc instrumentation.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, Iterator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TracingConfig:
    """Resolved tracing configuration."""

    service_name: str = "saras"
    service_version: str = "0.1.0"
    deployment_env: str = "dev"
    # OTLP/HTTP endpoint.  Empty string disables export.
    otlp_endpoint: str = ""
    # Sample ratio in [0, 1].  ``1.0`` = trace everything (default
    # in dev); ``0.0`` = trace nothing.
    sample_ratio: float = 1.0
    # Whether to install httpx auto-instrumentation.  Safe on
    # by default because SARAS uses httpx internally; turn off
    # if a particular deployment's httpx usage is sensitive.
    instrument_httpx: bool = True
    # In-memory exporter (tests only).  When True the OTLP
    # exporter is replaced with an in-process recorder.
    in_memory: bool = False

    @classmethod
    def from_env(cls) -> "TracingConfig":
        return cls(
            service_name=os.environ.get("SARAS_OTEL_SERVICE_NAME", "saras"),
            service_version=os.environ.get("SARAS_OTEL_VERSION", "0.1.0"),
            deployment_env=os.environ.get("SARAS_OTEL_ENV", "dev"),
            otlp_endpoint=os.environ.get("SARAS_OTEL_EXPORTER_OTLP_ENDPOINT", ""),
            sample_ratio=_env_float("SARAS_OTEL_SAMPLE_RATIO", 1.0),
            instrument_httpx=_env_bool("SARAS_OTEL_INSTRUMENT_HTTPX", True),
            in_memory=_env_bool("SARAS_OTEL_IN_MEMORY", False),
        )


def _env_float(name: str, default: float) -> float:
    v = os.environ.get(name, "").strip()
    if not v:
        return default
    try:
        return float(v)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name, "").strip().lower()
    if not v:
        return default
    return v in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


_INIT_LOCK = threading.Lock()
_INITIALIZED = False
_INMEM_EXPORTER: Any = None


def init_tracing(
    config: TracingConfig | None = None,
) -> Any:
    """Configure the global tracer provider.

    Returns the configured provider (or ``None`` if tracing is
    disabled).  Safe to call multiple times; the second call
    returns the previously-configured provider.
    """
    global _INITIALIZED, _INMEM_EXPORTER
    cfg = config or TracingConfig.from_env()

    with _INIT_LOCK:
        if _INITIALIZED:
            return _get_tracer_provider()
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import (
                BatchSpanProcessor,
                SimpleSpanProcessor,
            )
            from opentelemetry.sdk.trace.sampling import (
                ALWAYS_ON,
                TraceIdRatioBased,
            )
        except ImportError as e:  # pragma: no cover
            logger.debug("opentelemetry-sdk not installed: %s", e)
            return None

        resource = Resource.create(
            {
                "service.name": cfg.service_name,
                "service.version": cfg.service_version,
                "deployment.environment": cfg.deployment_env,
            }
        )
        provider = TracerProvider(
            resource=resource,
            sampler=(
                TraceIdRatioBased(cfg.sample_ratio)
                if 0.0 <= cfg.sample_ratio < 1.0
                else ALWAYS_ON
            ),
        )

        if cfg.in_memory:
            from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
                InMemorySpanExporter,
            )

            _INMEM_EXPORTER = InMemorySpanExporter()
            provider.add_span_processor(SimpleSpanProcessor(_INMEM_EXPORTER))
        elif cfg.otlp_endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )

                exporter = OTLPSpanExporter(endpoint=cfg.otlp_endpoint)
                provider.add_span_processor(BatchSpanProcessor(exporter))
            except ImportError as e:
                logger.debug("OTLP exporter not installed: %s", e)

        trace.set_tracer_provider(provider)

        if cfg.instrument_httpx:
            try:
                from opentelemetry.instrumentation.httpx import (
                    HTTPXClientInstrumentor,
                )

                HTTPXClientInstrumentor().instrument()
            except Exception as e:  # noqa: BLE001
                logger.debug("httpx instrumentation skipped: %s", e)

        _INITIALIZED = True
        logger.info(
            "tracing initialized: service=%s env=%s sample=%.2f endpoint=%s",
            cfg.service_name,
            cfg.deployment_env,
            cfg.sample_ratio,
            cfg.otlp_endpoint or "<none>",
        )
        return provider


def shutdown_tracing() -> None:
    """Flush and shut down the global tracer provider."""
    global _INITIALIZED
    with _INIT_LOCK:
        if not _INITIALIZED:
            return
        provider = _get_tracer_provider()
        if provider is not None:
            try:
                provider.shutdown()
            except Exception as e:  # noqa: BLE001
                logger.debug("tracer shutdown failed: %s", e)
        _INITIALIZED = False
        global _INMEM_EXPORTER
        _INMEM_EXPORTER = None


def _get_tracer_provider() -> Any:
    try:
        from opentelemetry import trace
    except ImportError:
        return None
    return trace.get_tracer_provider()


def get_tracer(name: str) -> Any:
    """Return a tracer for ``name`` (the module's ``__name__``)."""
    try:
        from opentelemetry import trace
    except ImportError:
        return _NoopTracer()
    return trace.get_tracer(name)


# ---------------------------------------------------------------------------
# In-memory helpers (tests)
# ---------------------------------------------------------------------------


def get_in_memory_spans() -> list[Any]:
    """Return all spans recorded so far (in-memory mode only)."""
    if _INMEM_EXPORTER is None:
        return []
    return list(_INMEM_EXPORTER.get_finished_spans())


def clear_in_memory_spans() -> None:
    if _INMEM_EXPORTER is not None:
        _INMEM_EXPORTER.clear()


# ---------------------------------------------------------------------------
# Span helpers
# ---------------------------------------------------------------------------


@contextmanager
def span(
    name: str,
    *,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Open a span with the given ``name`` and optional ``attributes``.

    Falls back to a no-op if tracing is disabled or OTel is
    unavailable, so call sites don't need a feature flag.

    Exceptions raised inside the ``with`` block are recorded on
    the span as an ``exception`` event (OTel convention) and
    re-raised so the caller can handle them.
    """
    tracer = get_tracer("saras.span")
    cm = tracer.start_as_current_span(name, attributes=attributes or {})
    span_obj: Any = None
    try:
        # Enter the OTel span and grab the Span object so we can
        # call ``record_exception`` on it.
        span_obj = cm.__enter__()
        yield cm
    except Exception as exc:  # noqa: BLE001
        if span_obj is not None and hasattr(span_obj, "record_exception"):
            try:
                span_obj.record_exception(exc)
            except Exception:  # noqa: BLE001
                pass
        raise
    finally:
        # Pass real exc_info so OTel's __exit__ can also set
        # status=ERROR when the body raised.
        try:
            cm.__exit__(*sys.exc_info())
        except Exception:  # noqa: BLE001
            pass


def traced(
    name: str | None = None,
    *,
    attributes_from_args: Callable[..., dict[str, Any]] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: wrap a sync function in a span.

    The span name defaults to ``"<module>.<func>"``.  Pass
    ``attributes_from_args`` to derive span attributes from the
    call's positional arguments (e.g. ``lambda user_id, action: {"user": user_id}``).
    """

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        span_name = name or f"{fn.__module__}.{fn.__qualname__}"

        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            attrs: dict[str, Any] = {}
            if attributes_from_args is not None:
                try:
                    attrs = attributes_from_args(*args, **kwargs) or {}
                except Exception:  # noqa: BLE001
                    attrs = {}
            with span(span_name, attributes=attrs):
                return fn(*args, **kwargs)

        return wrapper

    return deco


# ---------------------------------------------------------------------------
# No-op fallback
# ---------------------------------------------------------------------------


class _NoopTracer:
    """Returned by :func:`get_tracer` when OTel isn't installed.

    Implements the subset of the OTel API used by this codebase
    so call sites can use it transparently.
    """

    def start_as_current_span(
        self, name: str, attributes: dict[str, Any] | None = None
    ) -> Any:
        return _NoopSpan()


class _NoopSpan:
    def __enter__(self) -> "_NoopSpan":
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def record_exception(self, exc: BaseException) -> None:
        return None

    def set_attribute(self, key: str, value: Any) -> None:
        return None


__all__ = [
    "TracingConfig",
    "init_tracing",
    "shutdown_tracing",
    "get_tracer",
    "get_in_memory_spans",
    "clear_in_memory_spans",
    "span",
    "traced",
]
