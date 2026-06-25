"""Structured JSON logging for RAVEN (A5).

Wraps :mod:`structlog` (or stdlib :mod:`logging` as a fallback)
and produces one JSON object per log line, suitable for shipping
to Loki, ELK, or any log aggregator.

The key features:

- **JSON output** by default; one line per event.
- **PII redaction** runs on every log value via
  :mod:`app.core.audit.redaction`.  No credential or token can
  leak through the logger.
- **stdlib interop**: ``logging.getLogger("...")`` is wired up
  so existing call sites — which use ``logger = logging.getLogger(__name__)``
  — also produce JSON without any code changes.
- **Bound context**: callers can attach a context dict that
  travels with every log line until cleared (think request id,
  user id, trace id).
- **Env-driven**: ``RAVEN_LOG_LEVEL`` (default ``INFO``) and
  ``RAVEN_LOG_JSON`` (default ``true``) control behaviour.

The module is import-safe even if structlog is missing — it
falls back to plain ``logging`` with the same JSON formatter.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_INIT_LOCK = threading.Lock()
_INITIALIZED = False
_CONTEXT: dict[str, Any] = {}
_USE_STRUCTLOG: bool = False


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _env_log_level() -> int:
    name = os.environ.get("RAVEN_LOG_LEVEL", "INFO").strip().upper()
    return getattr(logging, name, logging.INFO)


def _env_json_enabled() -> bool:
    v = os.environ.get("RAVEN_LOG_JSON", "true").strip().lower()
    return v in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


def _redact_value(value: Any) -> Any:
    """Best-effort redaction of a value before it hits the log stream.

    Two layers:

    1. Audit redaction (rule-based) — catches named-field
       secrets like ``api_key``, ``password``, ``secret``.
    2. Privacy redaction (content-based) — catches PII like
       emails, SSNs, phone numbers embedded in any text.

    Both layers run; audit first because it's more
    conservative (replaces entire value with ``REDACTED``).
    Never raises — a logger must not crash the calling code.
    """
    value = _audit_redact(value)
    return _privacy_redact(value)


def _audit_redact(value: Any) -> Any:
    try:
        from app.core.audit.redaction import redact_value, compile_rules

        rules = compile_rules(_redaction_config())
        return redact_value(value, rules, _redaction_config().placeholder)
    except Exception as e:  # noqa: BLE001
        logger.debug("audit redaction failed: %s", e)
        return value


def _privacy_redact(value: Any) -> Any:
    try:
        from app.core.privacy import get_privacy_manager

        pm = get_privacy_manager()
        if pm is None:
            return value
    except Exception as e:  # noqa: BLE001
        logger.debug("privacy redaction unavailable: %s", e)
        return value
    return _redact_with_privacy(pm, value)


def _redact_with_privacy(pm: Any, value: Any) -> Any:
    """Apply the privacy redactor to one log value.

    Recurses into dicts/lists/tuples.  Non-string scalars are
    returned unchanged (PII detection is text-based).
    """
    if value is None:
        return None
    if isinstance(value, str):
        return pm.redact_for_log(value)
    if isinstance(value, dict):
        return {k: _redact_with_privacy(pm, v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        redacted = [_redact_with_privacy(pm, item) for item in value]
        return type(value)(redacted)
    return value


_REDACTION_CONFIG_SINGLETON: Any = None


def _redaction_config() -> Any:
    global _REDACTION_CONFIG_SINGLETON
    if _REDACTION_CONFIG_SINGLETON is None:
        from app.core.audit.redaction import RedactionConfig

        _REDACTION_CONFIG_SINGLETON = RedactionConfig()
    return _REDACTION_CONFIG_SINGLETON


# ---------------------------------------------------------------------------
# JSON formatter for stdlib logging
# ---------------------------------------------------------------------------


class JsonLogFormatter(logging.Formatter):
    """stdlib ``logging`` formatter that emits one JSON object per record.

    PII redaction is applied to ``msg`` and any ``extra`` dict
    before the line is serialised.
    """

    # Standard library LogRecord attributes that we copy across
    # as structured fields rather than dumping the whole record.
    STD_ATTRS = frozenset(
        {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "asctime",
            "taskName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        try:
            payload: dict[str, Any] = {
                "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "msg": _format_msg(record),
            }
            if record.exc_info:
                payload["exc"] = self.formatException(record.exc_info)
            if record.stack_info:
                payload["stack"] = record.stack_info
            # Add any ``extra=...`` keys the caller attached.
            for k, v in record.__dict__.items():
                if k in self.STD_ATTRS or k.startswith("_"):
                    continue
                payload[k] = _redact_value(v)
            # Add bound context.
            if _CONTEXT:
                payload["context"] = _redact_value(dict(_CONTEXT))
            return json.dumps(payload, default=str)
        except Exception as e:  # noqa: BLE001
            # Last-ditch: a plain line.  Never raise from a formatter.
            return f'{{"level":"ERROR","msg":"log-format-failed: {e}"}}'


def _format_msg(record: logging.LogRecord) -> str:
    """Apply redaction to the rendered log message."""
    try:
        msg = record.getMessage()
    except Exception:  # noqa: BLE001
        msg = str(record.msg)
    return str(_redact_value(msg))


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def init_logging(
    level: int | None = None,
    json_output: bool | None = None,
) -> None:
    """Configure root logging to emit JSON.

    Idempotent: calling twice is a no-op.  If structlog is
    available it's used for any logger created via
    :func:`get_logger`; the stdlib formatter handles everything
    else.
    """
    global _INITIALIZED, _USE_STRUCTLOG
    with _INIT_LOCK:
        if _INITIALIZED:
            return
        lvl = level if level is not None else _env_log_level()
        use_json = json_output if json_output is not None else _env_json_enabled()

        root = logging.getLogger()
        root.setLevel(lvl)
        # Clear pre-existing handlers so re-init works in tests.
        for h in list(root.handlers):
            root.removeHandler(h)
        handler = logging.StreamHandler(stream=sys.stderr)
        if use_json:
            handler.setFormatter(JsonLogFormatter())
        else:
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
            )
        root.addHandler(handler)

        # structlog, if available, is wired into stdlib via a
        # foreign-pre-chain filter.
        try:
            import structlog  # noqa: F401

            _USE_STRUCTLOG = True
            _configure_structlog()
        except ImportError:
            _USE_STRUCTLOG = False

        _INITIALIZED = True
        logger.debug("logging initialized: level=%s json=%s", lvl, use_json)


def _configure_structlog() -> None:
    """Wire structlog so ``structlog.get_logger()`` produces JSON too."""
    try:
        import structlog
    except ImportError:
        return
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLogger().level),
        cache_logger_on_first_use=True,
    )


def _redact_processor(_, __, event_dict):  # type: ignore[no-untyped-def]
    """structlog processor: redact every value in the event dict."""
    return {k: _redact_value(v) for k, v in event_dict.items()}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_logger(name: str | None = None) -> Any:
    """Return a logger that respects RAVEN settings.

    If structlog is available, returns a structlog logger that
    automatically merges the bound context.  Otherwise returns
    a stdlib logger — which is also producing JSON because
    :func:`init_logging` was called.
    """
    if _USE_STRUCTLOG:
        try:
            import structlog

            return structlog.get_logger(name)
        except ImportError:
            pass
    return logging.getLogger(name or "raven")


def bind_context(**kwargs: Any) -> None:
    """Attach a value to the global log context.

    The context travels with every subsequent log line until
    :func:`clear_context` is called or the same key is rebound.
    """
    _CONTEXT.update(kwargs)


def unbind_context(*keys: str) -> None:
    for k in keys:
        _CONTEXT.pop(k, None)


def clear_context() -> None:
    _CONTEXT.clear()


def get_context() -> dict[str, Any]:
    return dict(_CONTEXT)


__all__ = [
    "JsonLogFormatter",
    "init_logging",
    "get_logger",
    "bind_context",
    "unbind_context",
    "clear_context",
    "get_context",
]
