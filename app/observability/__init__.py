"""SARAS observability package (A5 in PLAN_v3.md).

Submodules:

- :mod:`app.observability.tracing` — OpenTelemetry init + span helpers
- :mod:`app.observability.logging` — structured JSON logging with PII redaction
- :mod:`app.observability.metrics` — Prometheus metrics for the A4 subsystems

The package is import-safe: every module is functional without
the optional dependencies (``opentelemetry``, ``structlog``,
``prometheus_client``).  When a dep is missing the module
degrades gracefully (no-op tracer, plain logging, None metrics).
"""

from __future__ import annotations

from app.observability.tracing import (
    TracingConfig,
    clear_in_memory_spans,
    get_in_memory_spans,
    get_tracer,
    init_tracing,
    shutdown_tracing,
    span,
    traced,
)
from app.observability.logging import (
    JsonLogFormatter,
    bind_context,
    clear_context,
    get_context,
    get_logger,
    init_logging,
    unbind_context,
)
from app.observability import metrics as obs_metrics


def init_all(*, in_memory: bool = False) -> None:
    """One-call init: tracing + logging + metrics.

    Idempotent.  Safe to call at process start.
    """
    init_logging()
    cfg = TracingConfig.from_env()
    if in_memory:
        cfg = TracingConfig(
            service_name=cfg.service_name,
            service_version=cfg.service_version,
            deployment_env=cfg.deployment_env,
            otlp_endpoint="",
            sample_ratio=cfg.sample_ratio,
            instrument_httpx=cfg.instrument_httpx,
            in_memory=True,
        )
    init_tracing(cfg)
    obs_metrics.init_metrics()


__all__ = [
    # tracing
    "TracingConfig",
    "init_tracing",
    "shutdown_tracing",
    "get_tracer",
    "get_in_memory_spans",
    "clear_in_memory_spans",
    "span",
    "traced",
    # logging
    "JsonLogFormatter",
    "init_logging",
    "get_logger",
    "bind_context",
    "unbind_context",
    "clear_context",
    "get_context",
    # metrics
    "obs_metrics",
    "init_all",
]
