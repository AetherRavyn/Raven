"""Tests for the A5 observability layer.

Covers:
- :mod:`app.observability.tracing` — config, init, span helpers, decorator,
  in-memory span capture, graceful no-op fallback.
- :mod:`app.observability.logging` — JSON formatter shape, PII redaction
  in messages and extras, context binding roundtrip, structlog fallback.
- :mod:`app.observability.metrics` — helper functions are no-op safe
  when prometheus_client is absent, idempotent init, increment works
  when available.
- :func:`app.observability.init_all` — one-call init works end-to-end.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Generator

import pytest


# ---------------------------------------------------------------------------
# Session-scoped bootstrap: init observability exactly once.
# ---------------------------------------------------------------------------
#
# OTel's `trace.set_tracer_provider` and Prometheus' global registry
# only allow one registration per process.  Re-initialising in every
# test would raise.  We do it once per session and only reset the
# per-test state (in-memory spans, log context).


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_observability() -> None:
    from app.observability import init_all

    init_all(in_memory=True)


@pytest.fixture(autouse=True)
def _clear_per_test_state() -> Generator[None, None, None]:
    """Clear per-test state without re-initialising modules."""
    from app.observability import logging as obs_log
    from app.observability import tracing as obs_tracing

    obs_log._CONTEXT.clear()
    obs_tracing.clear_in_memory_spans()
    yield


# ---------------------------------------------------------------------------
# Tracing
# ---------------------------------------------------------------------------


class TestTracingConfig:
    def test_defaults(self) -> None:
        from app.observability.tracing import TracingConfig

        cfg = TracingConfig()
        assert cfg.service_name == "saras"
        assert cfg.service_version == "0.1.0"
        assert cfg.deployment_env == "dev"
        assert cfg.otlp_endpoint == ""
        assert cfg.sample_ratio == 1.0
        assert cfg.instrument_httpx is True
        assert cfg.in_memory is False

    def test_from_env_overrides(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SARAS_OTEL_SERVICE_NAME", "saras-prod")
        monkeypatch.setenv("SARAS_OTEL_VERSION", "9.9.9")
        monkeypatch.setenv("SARAS_OTEL_ENV", "prod")
        monkeypatch.setenv("SARAS_OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel:4318")
        monkeypatch.setenv("SARAS_OTEL_SAMPLE_RATIO", "0.25")
        monkeypatch.setenv("SARAS_OTEL_INSTRUMENT_HTTPX", "false")
        monkeypatch.setenv("SARAS_OTEL_IN_MEMORY", "true")

        from app.observability.tracing import TracingConfig

        cfg = TracingConfig.from_env()
        assert cfg.service_name == "saras-prod"
        assert cfg.service_version == "9.9.9"
        assert cfg.deployment_env == "prod"
        assert cfg.otlp_endpoint == "http://otel:4318"
        assert cfg.sample_ratio == 0.25
        assert cfg.instrument_httpx is False
        assert cfg.in_memory is True

    def test_from_env_uses_defaults_on_missing(self) -> None:
        for v in (
            "SARAS_OTEL_SERVICE_NAME",
            "SARAS_OTEL_VERSION",
            "SARAS_OTEL_ENV",
            "SARAS_OTEL_EXPORTER_OTLP_ENDPOINT",
            "SARAS_OTEL_SAMPLE_RATIO",
            "SARAS_OTEL_INSTRUMENT_HTTPX",
            "SARAS_OTEL_IN_MEMORY",
        ):
            os.environ.pop(v, None)

        from app.observability.tracing import TracingConfig

        cfg = TracingConfig.from_env()
        assert cfg.service_name == "saras"
        assert cfg.sample_ratio == 1.0
        assert cfg.instrument_httpx is True

    def test_from_env_invalid_float_falls_back(self, monkeypatch) -> None:
        monkeypatch.setenv("SARAS_OTEL_SAMPLE_RATIO", "not-a-float")

        from app.observability.tracing import TracingConfig

        cfg = TracingConfig.from_env()
        assert cfg.sample_ratio == 1.0


class TestTracingInit:
    def test_init_in_memory_captures_spans(self) -> None:
        from app.observability.tracing import (
            clear_in_memory_spans,
            get_in_memory_spans,
            span,
        )

        clear_in_memory_spans()

        with span("test.op", attributes={"k": "v"}):
            with span("test.inner"):
                pass

        spans = get_in_memory_spans()
        names = [s.name for s in spans]
        assert "test.op" in names
        assert "test.inner" in names
        assert len(spans) >= 2

    def test_init_idempotent(self) -> None:
        from app.observability.tracing import TracingConfig, init_tracing

        p1 = init_tracing(TracingConfig(in_memory=True))
        p2 = init_tracing(TracingConfig(in_memory=True))
        # Second call should return same provider
        assert p1 is p2

    def test_get_tracer_returns_tracer(self) -> None:
        from app.observability.tracing import get_tracer

        tracer = get_tracer("test.module")
        assert tracer is not None
        # Should be able to start a span
        with tracer.start_as_current_span("noop.test"):
            pass


class TestSpanHelpers:
    def test_span_records_exception(self) -> None:
        from app.observability.tracing import (
            clear_in_memory_spans,
            get_in_memory_spans,
            span,
        )

        clear_in_memory_spans()

        with pytest.raises(ValueError):
            with span("failing.op"):
                raise ValueError("boom")

        spans = get_in_memory_spans()
        assert any(s.name == "failing.op" for s in spans)
        # The span should have an event recorded
        boom_spans = [s for s in spans if s.name == "failing.op"]
        assert len(boom_spans) == 1
        events = boom_spans[0].events
        # OTel records the exception as an event named "exception"
        assert any(e.name == "exception" for e in events)

    def test_traced_decorator(self) -> None:
        from app.observability.tracing import (
            clear_in_memory_spans,
            get_in_memory_spans,
            traced,
        )

        clear_in_memory_spans()

        @traced("my.op")
        def add(a: int, b: int) -> int:
            return a + b

        assert add(2, 3) == 5
        spans = get_in_memory_spans()
        assert any(s.name == "my.op" for s in spans)

    def test_traced_default_name(self) -> None:
        from app.observability.tracing import (
            clear_in_memory_spans,
            get_in_memory_spans,
            traced,
        )

        clear_in_memory_spans()

        @traced()
        def hello() -> str:
            return "hi"

        assert hello() == "hi"
        spans = get_in_memory_spans()
        # Default name includes module + qualname
        assert any("hello" in s.name for s in spans)

    def test_traced_attributes_from_args(self) -> None:
        from app.observability.tracing import (
            clear_in_memory_spans,
            get_in_memory_spans,
            traced,
        )

        clear_in_memory_spans()

        @traced("op", attributes_from_args=lambda x: {"value": x})
        def square(x: int) -> int:
            return x * x

        assert square(4) == 16
        spans = get_in_memory_spans()
        op_spans = [s for s in spans if s.name == "op"]
        assert op_spans
        # Attributes should contain "value"
        attrs = dict(op_spans[0].attributes or {})
        assert attrs.get("value") == 4

    def test_traced_attributes_from_args_failure_ignored(self) -> None:
        from app.observability.tracing import (
            clear_in_memory_spans,
            get_in_memory_spans,
            traced,
        )

        clear_in_memory_spans()

        def bad_extractor(*a, **kw):  # noqa: ARG001
            raise RuntimeError("nope")

        @traced("op", attributes_from_args=bad_extractor)
        def fn(x: int) -> int:
            return x

        assert fn(7) == 7
        spans = get_in_memory_spans()
        assert any(s.name == "op" for s in spans)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class TestJsonLogFormatter:
    def _format(self, msg: str, **extra) -> dict:
        from app.observability.logging import JsonLogFormatter, init_logging

        init_logging()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=10,
            msg=msg,
            args=(),
            exc_info=None,
        )
        for k, v in extra.items():
            setattr(record, k, v)
        return json.loads(JsonLogFormatter().format(record))

    def test_basic_shape(self) -> None:
        payload = self._format("hello world")
        assert payload["level"] == "INFO"
        assert payload["logger"] == "test"
        assert payload["msg"] == "hello world"
        assert "ts" in payload
        # ISO-8601 timestamp
        assert "T" in payload["ts"]

    def test_includes_extra_fields(self) -> None:
        payload = self._format("hi", user_id="u1", action="login")
        assert payload["user_id"] == "u1"
        assert payload["action"] == "login"

    def test_redacts_pii_in_msg(self) -> None:
        payload = self._format("key=sk-abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG")
        assert "sk-abcdefghijklmnopqrstuvwxyz" not in payload["msg"]
        assert "REDACTED" in payload["msg"]

    def test_redacts_pii_in_extras(self) -> None:
        payload = self._format(
            "ok",
            api_key="sk-abcdefghijklmnopqrstuvwxyz1234567890ABCDEFG",
        )
        assert "REDACTED" in str(payload["api_key"])

    def test_includes_context(self) -> None:
        from app.observability.logging import (
            bind_context,
            clear_context,
            init_logging,
        )

        init_logging()
        bind_context(user_id="u1", trace_id="t1")
        try:
            payload = self._format("hi")
            assert payload["context"]["user_id"] == "u1"
            assert payload["context"]["trace_id"] == "t1"
        finally:
            clear_context()

    def test_format_includes_exception(self) -> None:
        try:
            raise RuntimeError("kaboom")
        except RuntimeError:
            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname=__file__,
                lineno=1,
                msg="failed",
                args=(),
                exc_info=sys.exc_info(),
            )
        from app.observability.logging import JsonLogFormatter, init_logging

        init_logging()
        payload = json.loads(JsonLogFormatter().format(record))
        assert "exc" in payload
        assert "kaboom" in payload["exc"]

    def test_format_falls_back_gracefully(self) -> None:
        """If json.dumps fails, the formatter must not raise."""
        from app.observability.logging import JsonLogFormatter, init_logging

        init_logging()

        class Bad:
            def __repr__(self) -> str:
                raise RuntimeError("no repr")

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="ok",
            args=(),
            exc_info=None,
        )
        record.boom = Bad()
        out = JsonLogFormatter().format(record)
        # Should still produce a valid (or fallback) line
        assert out


class TestInitLogging:
    def test_idempotent(self) -> None:
        from app.observability.logging import init_logging

        init_logging()
        # If we get here without error, it's good.  Idempotency is
        # only guaranteed within a process that hasn't reset the
        # module-level flag.

    def test_structlog_fallback(self, monkeypatch) -> None:
        """When structlog is missing, _USE_STRUCTLOG stays False."""
        from app.observability import logging as obs_log

        # Hide structlog
        hidden = [k for k in sys.modules if k.startswith("structlog")]
        for k in hidden:
            monkeypatch.delitem(sys.modules, k)
        import builtins

        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):  # noqa: ARG001
            if name == "structlog" or name.startswith("structlog."):
                raise ImportError("blocked")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        # Reset & re-init
        obs_log._INITIALIZED = False
        obs_log._USE_STRUCTLOG = False
        obs_log.init_logging()
        assert obs_log._USE_STRUCTLOG is False

        # Restore by resetting state
        obs_log._INITIALIZED = False


class TestContextBinding:
    def test_bind_and_get(self) -> None:
        from app.observability.logging import (
            bind_context,
            clear_context,
            get_context,
        )

        clear_context()
        bind_context(user_id="u1")
        bind_context(session_id="s1")
        ctx = get_context()
        assert ctx == {"user_id": "u1", "session_id": "s1"}

    def test_unbind(self) -> None:
        from app.observability.logging import (
            bind_context,
            clear_context,
            get_context,
            unbind_context,
        )

        clear_context()
        bind_context(user_id="u1", session_id="s1")
        unbind_context("user_id")
        assert get_context() == {"session_id": "s1"}

    def test_clear(self) -> None:
        from app.observability.logging import (
            bind_context,
            clear_context,
            get_context,
        )

        bind_context(x=1)
        clear_context()
        assert get_context() == {}

    def test_bind_overwrites(self) -> None:
        from app.observability.logging import (
            bind_context,
            clear_context,
            get_context,
        )

        clear_context()
        bind_context(user_id="u1")
        bind_context(user_id="u2")
        assert get_context()["user_id"] == "u2"


class TestGetLogger:
    def test_returns_logger(self) -> None:
        from app.observability.logging import get_logger, init_logging

        init_logging()
        log = get_logger("test.module")
        assert log is not None
        # Should be able to call standard methods
        log.info("hello")

    def test_returns_logger_without_init(self) -> None:
        """get_logger must work even before init_logging is called."""
        from app.observability import logging as obs_log
        from app.observability.logging import get_logger

        # Temporarily flip the flag
        prev = obs_log._INITIALIZED
        obs_log._INITIALIZED = False
        obs_log._USE_STRUCTLOG = False
        try:
            log = get_logger("test.uninit")
            assert log is not None
        finally:
            obs_log._INITIALIZED = prev


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_init_idempotent(self) -> None:
        from app.observability import metrics as obs_metrics

        assert obs_metrics.init_metrics() is True
        assert obs_metrics.init_metrics() is True
        # All metric handles should be set
        assert obs_metrics.audit_events_total is not None
        assert obs_metrics.policy_approvals_pending is not None

    def test_helpers_increment_counters(self) -> None:
        from app.observability import metrics as obs_metrics

        obs_metrics.init_metrics()
        # Just call them; no exception is success
        obs_metrics.inc_audit_event("tool_call", "low")
        obs_metrics.inc_audit_redaction("api_key")
        obs_metrics.inc_policy_evaluation("allow", "low")
        obs_metrics.inc_vault_rotation()
        obs_metrics.inc_vault_lookup_failure()
        obs_metrics.inc_otel_exported()
        obs_metrics.inc_otel_dropped()
        obs_metrics.inc_log_redaction()
        obs_metrics.set_audit_log_size(1024)
        obs_metrics.set_policy_approvals_pending(2)
        obs_metrics.set_vault_secrets(5)
        obs_metrics.set_trust_tier_counts({"ADMIN": 1, "TRUSTED": 2, "NEW": 3})

    def test_helpers_no_op_when_unavailable(self, monkeypatch) -> None:
        from app.observability import metrics as obs_metrics

        def fake_is_available() -> bool:
            return False

        monkeypatch.setattr(obs_metrics, "is_available", fake_is_available)

        # All of these should silently no-op
        obs_metrics.inc_audit_event("x", "low")
        obs_metrics.inc_audit_redaction("x")
        obs_metrics.inc_policy_evaluation("allow", "low")
        obs_metrics.inc_vault_rotation()
        obs_metrics.inc_vault_lookup_failure()
        obs_metrics.inc_otel_exported()
        obs_metrics.inc_otel_dropped()
        obs_metrics.inc_log_redaction()
        obs_metrics.set_audit_log_size(1)
        obs_metrics.set_policy_approvals_pending(0)
        obs_metrics.set_vault_secrets(0)
        obs_metrics.set_trust_tier_counts({"ADMIN": 0})

    def test_helpers_tolerate_metric_errors(self, monkeypatch) -> None:
        from app.observability import metrics as obs_metrics

        class _Bad:
            def inc(self, *a, **kw):  # noqa: ARG002
                raise RuntimeError("boom")

            def labels(self, *a, **kw):  # noqa: ARG002
                return self

            def set(self, *a, **kw):  # noqa: ARG002
                raise RuntimeError("boom")

        monkeypatch.setattr(obs_metrics, "is_available", lambda: True)
        monkeypatch.setattr(obs_metrics, "audit_events_total", _Bad())
        monkeypatch.setattr(obs_metrics, "audit_events_by_risk", _Bad())
        monkeypatch.setattr(obs_metrics, "audit_redactions_total", _Bad())
        monkeypatch.setattr(obs_metrics, "policy_evaluations_total", _Bad())
        monkeypatch.setattr(obs_metrics, "policy_decisions_by_verdict", _Bad())
        monkeypatch.setattr(obs_metrics, "policy_approvals_pending", _Bad())
        monkeypatch.setattr(obs_metrics, "policy_trust_tier_users", _Bad())
        monkeypatch.setattr(obs_metrics, "vault_secrets_total", _Bad())
        monkeypatch.setattr(obs_metrics, "vault_rotations_total", _Bad())
        monkeypatch.setattr(obs_metrics, "vault_lookup_failures_total", _Bad())
        monkeypatch.setattr(obs_metrics, "otel_spans_exported_total", _Bad())
        monkeypatch.setattr(obs_metrics, "otel_spans_dropped_total", _Bad())
        monkeypatch.setattr(obs_metrics, "log_redactions_total", _Bad())
        monkeypatch.setattr(obs_metrics, "audit_log_size_bytes", _Bad())

        # Should not raise
        obs_metrics.inc_audit_event("x", "low")
        obs_metrics.inc_audit_redaction("x")
        obs_metrics.inc_policy_evaluation("allow", "low")
        obs_metrics.inc_vault_rotation()
        obs_metrics.inc_vault_lookup_failure()
        obs_metrics.inc_otel_exported()
        obs_metrics.inc_otel_dropped()
        obs_metrics.inc_log_redaction()
        obs_metrics.set_audit_log_size(1)
        obs_metrics.set_policy_approvals_pending(0)
        obs_metrics.set_vault_secrets(0)
        obs_metrics.set_trust_tier_counts({"ADMIN": 0})


# ---------------------------------------------------------------------------
# init_all integration
# ---------------------------------------------------------------------------


class TestInitAll:
    def test_init_all_idempotent(self) -> None:
        from app.observability import init_all
        from app.observability import logging as obs_log
        from app.observability import metrics as obs_metrics
        from app.observability import tracing as obs_tracing

        init_all(in_memory=True)
        assert obs_log._INITIALIZED is True
        assert obs_metrics._INITIALIZED is True
        assert obs_tracing._INITIALIZED is True
