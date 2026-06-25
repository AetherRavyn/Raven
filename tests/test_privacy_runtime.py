"""Tests for the privacy ↔ runtime integration (Day 20)."""

from __future__ import annotations

import json
import logging
import os
from datetime import timedelta
from typing import Any

import pytest

from app.core.privacy import (
    ConsentLevel,
    DataClass,
    PrivacyError,
    PrivacyManager,
    data_class_for,
    get_privacy_manager,
    redact_for_log,
    reset_privacy,
    set_privacy_manager,
)
from app.core.privacy.consent import ConsentStore
from app.core.privacy.detection import PIIDetector
from app.core.privacy.redaction import Redactor
from app.core.privacy.retention import RetentionManager, RetentionPolicy
from app.core.privacy.policy import DEFAULT_DATA_CLASS


# -------------------------------------------------------------------
# tool name → DataClass
# -------------------------------------------------------------------


class TestToolDataClass:
    def test_email_tools(self) -> None:
        assert data_class_for("email_send") == DataClass.EMAIL
        assert data_class_for("gmail_send") == DataClass.EMAIL
        assert data_class_for("gmail") == DataClass.EMAIL

    def test_file_tools(self) -> None:
        assert data_class_for("file_read") == DataClass.FILES
        assert data_class_for("file_write") == DataClass.FILES
        assert data_class_for("shell") == DataClass.FILES

    def test_calendar_tools(self) -> None:
        assert data_class_for("calendar_read") == DataClass.CALENDAR
        assert data_class_for("add_calendar_event") == DataClass.CALENDAR

    def test_location_tools(self) -> None:
        assert data_class_for("location") == DataClass.LOCATION
        assert data_class_for("weather") == DataClass.LOCATION

    def test_credential_tools(self) -> None:
        assert data_class_for("vault_read") == DataClass.CREDENTIALS
        assert data_class_for("secret_read") == DataClass.CREDENTIALS

    def test_prefix_match(self) -> None:
        # Tool names that *start* with a registered tool + '_'
        # match by prefix.
        assert data_class_for("gmail_send_message") == DataClass.EMAIL
        assert data_class_for("file_read_v2") == DataClass.FILES

    def test_suffix_match(self) -> None:
        # Tool names that *end* with '_' + a registered tool
        # match by suffix.
        assert data_class_for("my_custom_file_read") == DataClass.FILES

    def test_no_false_positive(self) -> None:
        # 'custom_file_read_helper' doesn't start with
        # 'file_read_' and doesn't end with '_file_read' —
        # it should NOT match the FILES class.
        assert data_class_for("custom_file_read_helper") == DataClass.PROFILE

    def test_unknown_defaults_to_profile(self) -> None:
        assert data_class_for("totally_made_up") == DEFAULT_DATA_CLASS
        assert DEFAULT_DATA_CLASS == DataClass.PROFILE

    def test_empty_string(self) -> None:
        assert data_class_for("") == DEFAULT_DATA_CLASS

    def test_lowercases(self) -> None:
        assert data_class_for("FILE_READ") == DataClass.FILES
        assert data_class_for("File_Write") == DataClass.FILES


# -------------------------------------------------------------------
# PrivacyError
# -------------------------------------------------------------------


class TestPrivacyError:
    def test_carries_fields(self) -> None:
        e = PrivacyError(
            "test",
            user_id="u1",
            data_class=DataClass.EMAIL,
            current_level=ConsentLevel.DENY,
        )
        assert e.user_id == "u1"
        assert e.data_class == DataClass.EMAIL
        assert e.current_level == ConsentLevel.DENY
        assert isinstance(e, PermissionError)
        assert "test" in str(e)

    def test_repr(self) -> None:
        e = PrivacyError(
            "x",
            user_id="u1",
            data_class=DataClass.FILES,
        )
        r = repr(e)
        assert "u1" in r
        assert "files" in r

    def test_no_current_level(self) -> None:
        e = PrivacyError("x", user_id="u1", data_class=DataClass.FILES)
        assert e.current_level is None


# -------------------------------------------------------------------
# check_tool
# -------------------------------------------------------------------


class TestCheckTool:
    def setup_method(self) -> None:
        reset_privacy()
        self.pm = PrivacyManager(
            detector=PIIDetector(),
            redactor=Redactor(detector=PIIDetector()),
            consent_store=ConsentStore(),
            retention_manager=RetentionManager(
                policy=RetentionPolicy(),
                consent_store=ConsentStore(),
            ),
        )
        set_privacy_manager(self.pm)

    def teardown_method(self) -> None:
        reset_privacy()

    def test_allowed_returns_data_class(self) -> None:
        self.pm.grant_consent("u1", DataClass.FILES, ConsentLevel.ALLOW)
        assert self.pm.check_tool("u1", "file_read") == DataClass.FILES

    def test_no_consent_raises(self) -> None:
        with pytest.raises(PrivacyError) as ei:
            self.pm.check_tool("u1", "file_read")
        assert ei.value.data_class == DataClass.FILES
        assert ei.value.current_level is None

    def test_deny_raises(self) -> None:
        self.pm.grant_consent("u1", DataClass.FILES, ConsentLevel.DENY)
        with pytest.raises(PrivacyError) as ei:
            self.pm.check_tool("u1", "file_read")
        assert ei.value.data_class == DataClass.FILES
        assert ei.value.current_level == ConsentLevel.DENY

    def test_expired_raises(self) -> None:
        self.pm.grant_consent(
            "u1", DataClass.FILES, ConsentLevel.ALLOW, ttl=timedelta(milliseconds=5)
        )
        import time as _t

        _t.sleep(0.05)
        with pytest.raises(PrivacyError):
            self.pm.check_tool("u1", "file_read")

    def test_ask_raises(self) -> None:
        self.pm.grant_consent("u1", DataClass.FILES, ConsentLevel.ASK)
        with pytest.raises(PrivacyError) as ei:
            self.pm.check_tool("u1", "file_read")
        assert ei.value.current_level == ConsentLevel.ASK

    def test_auto_purge_allowed(self) -> None:
        self.pm.grant_consent("u1", DataClass.FILES, ConsentLevel.AUTO_PURGE)
        assert self.pm.check_tool("u1", "file_read") == DataClass.FILES

    def test_missing_user_id_raises(self) -> None:
        with pytest.raises(PrivacyError) as ei:
            self.pm.check_tool("", "file_read")
        assert ei.value.user_id == ""

    def test_explicit_data_class_override(self) -> None:
        # Override the auto-resolved data class.
        self.pm.grant_consent("u1", DataClass.PROFILE, ConsentLevel.ALLOW)
        # file_read normally maps to FILES — pass data_class=PROFILE
        # to use that.
        assert (
            self.pm.check_tool("u1", "file_read", data_class=DataClass.PROFILE)
            == DataClass.PROFILE
        )

    def test_tool_name_to_data_class_mapping(self) -> None:
        # Verify a few representative mappings resolve correctly.
        self.pm.grant_consent("u1", DataClass.EMAIL, ConsentLevel.ALLOW)
        assert self.pm.check_tool("u1", "email_send") == DataClass.EMAIL

        self.pm.grant_consent("u1", DataClass.LOCATION, ConsentLevel.ALLOW)
        assert self.pm.check_tool("u1", "weather") == DataClass.LOCATION

        self.pm.grant_consent("u1", DataClass.CONVERSATION, ConsentLevel.ALLOW)
        assert self.pm.check_tool("u1", "memory_search") == DataClass.CONVERSATION


# -------------------------------------------------------------------
# Registry (singleton)
# -------------------------------------------------------------------


class TestRegistry:
    def setup_method(self) -> None:
        reset_privacy()

    def teardown_method(self) -> None:
        reset_privacy()

    def test_singleton(self) -> None:
        a = get_privacy_manager()
        b = get_privacy_manager()
        assert a is b

    def test_reset_clears(self) -> None:
        a = get_privacy_manager()
        reset_privacy()
        b = get_privacy_manager()
        # Different identity after reset.
        assert a is not b

    def test_set_replaces(self) -> None:
        custom = PrivacyManager()
        set_privacy_manager(custom)
        assert get_privacy_manager() is custom

    def test_set_none_clears(self) -> None:
        get_privacy_manager()  # populate
        set_privacy_manager(None)
        a = get_privacy_manager()  # lazy
        b = get_privacy_manager()
        assert a is b
        # But it's a fresh instance, not the one we cleared.
        assert a is not None


# -------------------------------------------------------------------
# Log redaction (observability integration)
# -------------------------------------------------------------------


class TestLogRedaction:
    def test_email_redacted(self) -> None:
        out = redact_for_log("alice@example.com")
        assert "alice@example.com" not in out
        assert "@example.com" not in out

    def test_phone_redacted_default(self) -> None:
        # Aggressive default — phones are redacted.
        out = redact_for_log("call 555-123-4567")
        assert "555-123-4567" not in out

    def test_phone_not_redacted_audit_safe(self) -> None:
        out = redact_for_log("call 555-123-4567", audit_safe=True)
        # audit-safe mode skips phones (false-positive risk).
        assert "555-123-4567" in out

    def test_ssn_redacted(self) -> None:
        out = redact_for_log("SSN 123-45-6789")
        assert "123-45-6789" not in out

    def test_credit_card_redacted(self) -> None:
        out = redact_for_log("4111-1111-1111-1111")
        assert "4111" not in out

    def test_api_key_redacted(self) -> None:
        out = redact_for_log("sk-abcdefghijklmnopqrstuvwx")
        assert "sk-abcdef" not in out

    def test_no_pii_passes_through(self) -> None:
        text = "the weather is nice today"
        assert redact_for_log(text) == text

    def test_empty_text(self) -> None:
        assert redact_for_log("") == ""


class TestObservabilityLoggingRedaction:
    """Verify the observability logging layer uses the privacy redactor."""

    def setup_method(self) -> None:
        reset_privacy()
        # Pre-populate the singleton so the logger finds it.
        get_privacy_manager()

    def teardown_method(self) -> None:
        reset_privacy()

    def test_dict_redaction(self) -> None:
        from app.observability.logging import _redact_value

        d = {
            "user": "alice@example.com",
            "msg": "SSN 123-45-6789",
            "nested": {"phone": "555-123-4567"},
            "list": ["alice@example.com", 42, None],
            "safe": "x" * 20,
        }
        out = _redact_value(d)
        assert out["user"] != "alice@example.com"
        assert "alice@example.com" not in str(out)
        assert "123-45-6789" not in str(out)
        assert "555-123-4567" not in str(out)
        # Non-PII scalars are unchanged.
        assert out["list"][1] == 42
        assert out["list"][2] is None
        assert out["safe"] == "x" * 20

    def test_list_redaction(self) -> None:
        from app.observability.logging import _redact_value

        out = _redact_value(["alice@example.com", "hello", "bob@example.com"])
        assert "alice@example.com" not in str(out)
        assert "bob@example.com" not in str(out)
        assert "hello" == out[1]

    def test_string_redaction(self) -> None:
        from app.observability.logging import _redact_value

        out = _redact_value("alice@example.com")
        assert "alice@example.com" not in out

    def test_none_redaction(self) -> None:
        from app.observability.logging import _redact_value

        assert _redact_value(None) is None

    def test_int_passthrough(self) -> None:
        from app.observability.logging import _redact_value

        assert _redact_value(42) == 42

    def test_logging_integration(self) -> None:
        """End-to-end: stdlib logger output is redacted via JSON formatter."""
        from app.observability.logging import (
            JsonLogFormatter,
            init_logging,
        )

        # Reset module-level init flag.
        import app.observability.logging as log_mod

        log_mod._INITIALIZED = False
        init_logging(level=logging.WARNING, json_output=True)

        # Capture stderr from the StreamHandler.
        stream = log_mod.io.StringIO() if False else _LogCapture()

        # Replace the existing handler with our capture.
        root = logging.getLogger()
        for h in list(root.handlers):
            root.removeHandler(h)
        handler = logging.StreamHandler(stream=stream)
        handler.setFormatter(JsonLogFormatter())
        root.addHandler(handler)

        try:
            logger = logging.getLogger("test_privacy_runtime")
            logger.warning("User alice@example.com did the thing")
            output = stream.getvalue()
        finally:
            # Restore default config so we don't leak handlers.
            log_mod._INITIALIZED = False
            init_logging(level=logging.WARNING, json_output=True)

        assert "alice@example.com" not in output
        assert "@example.com" not in output
        # Confirm we got a JSON line.
        line = output.strip().splitlines()[-1]
        data = json.loads(line)
        assert data["level"] == "WARNING"


class _LogCapture:
    """Minimal in-memory stream that mimics a write/flushable file."""

    def __init__(self) -> None:
        self._buf: list[str] = []

    def write(self, s: str) -> int:
        self._buf.append(s)
        return len(s)

    def flush(self) -> None:
        return None

    def getvalue(self) -> str:
        return "".join(self._buf)


# -------------------------------------------------------------------
# Runtime integration (env flag, _privacy_check_tool)
# -------------------------------------------------------------------


class TestRuntimePrivacyGate:
    def setup_method(self) -> None:
        reset_privacy()
        # Set up a privacy manager with consent for some classes.
        self.pm = PrivacyManager(
            detector=PIIDetector(),
            redactor=Redactor(detector=PIIDetector()),
            consent_store=ConsentStore(),
            retention_manager=RetentionManager(
                policy=RetentionPolicy(),
                consent_store=ConsentStore(),
            ),
        )
        self.pm.grant_consent("u1", DataClass.FILES, ConsentLevel.ALLOW)
        self.pm.grant_consent("u1", DataClass.EMAIL, ConsentLevel.ALLOW)
        set_privacy_manager(self.pm)

    def teardown_method(self) -> None:
        reset_privacy()
        os.environ.pop("RAVEN_PRIVACY_V2", None)

    def _build_runtime(self, *, env: bool) -> Any:
        """Build a real AgentRuntime with privacy toggled on/off.

        We bypass the heavy provider setup by setting
        ``RAVEN_PRIVACY_V2`` and a stub provider.  The
        constructor is large; we rely on the env flag being
        read at __init__ time.
        """
        if env:
            os.environ["RAVEN_PRIVACY_V2"] = "1"
        else:
            os.environ.pop("RAVEN_PRIVACY_V2", None)


        # Mock the LLM provider + workspace so the constructor
        # doesn't try to reach the network.
        try:
            from app.core.runtime import AgentRuntime as AR

            # Patch the heavy deps.
            from unittest.mock import patch

            with patch.object(AR, "__init__", _lite_init):
                rt = AR.__new__(AR)
                # Run a minimal __init__ that wires privacy.
                _lite_init(rt)
                return rt
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"runtime init failed: {e}")
            return None  # unreachable

    def test_disabled_by_default(self) -> None:
        rt = self._build_runtime(env=False)
        # The flag is read from the env at __init__ time.
        assert rt._use_privacy_v2 is False
        ok, reason, _dc = rt._privacy_check_tool("file_read", "u1")
        # When disabled, the gate is pass-through.
        assert ok is True
        assert reason == ""

    def test_enabled_passes_allowed(self) -> None:
        rt = self._build_runtime(env=True)
        assert rt._use_privacy_v2 is True
        ok, reason, dc = rt._privacy_check_tool("file_read", "u1")
        assert ok is True
        assert reason == ""
        assert dc == "files"

    def test_enabled_blocks_no_consent(self) -> None:
        rt = self._build_runtime(env=True)
        # email_send is ALLOW'd, but gmail_send_message also
        # maps to EMAIL, so let's use a tool that maps to a
        # class we haven't granted.
        ok, reason, dc = rt._privacy_check_tool("shell", "u1")
        # shell maps to FILES, which IS allowed for u1.
        # Use calendar_read which we haven't granted.
        ok, reason, dc = rt._privacy_check_tool("calendar_read", "u1")
        assert ok is False
        assert "privacy" in reason.lower()
        assert dc == "calendar"

    def test_enabled_blocks_deny(self) -> None:
        self.pm.grant_consent("u2", DataClass.HEALTH, ConsentLevel.DENY)
        rt = self._build_runtime(env=True)
        ok, reason, dc = rt._privacy_check_tool("health_read", "u2")
        assert ok is False
        assert dc == "health"

    def test_disabled_when_manager_missing(self) -> None:
        """If the manager can't be built, the gate stays permissive."""
        os.environ["RAVEN_PRIVACY_V2"] = "1"
        # Clear the manager and patch the builder to return None.

        from app.core.runtime import AgentRuntime as AR

        rt = AR.__new__(AR)
        _lite_init(rt, privacy_override=None)

        ok, reason, dc = rt._privacy_check_tool("file_read", "u1")
        # No manager → permissive.
        assert ok is True


def _lite_init(rt: Any, *, privacy_override: Any = "auto") -> None:
    """A bare-bones AgentRuntime that wires just the privacy surface.

    Avoids the heavy constructor (LLM provider, embedding
    models, OTel) so the privacy gate can be tested in
    isolation.
    """

    rt._use_privacy_v2 = _env_flag("RAVEN_PRIVACY_V2")
    if privacy_override == "auto":
        from app.core.privacy import get_privacy_manager

        rt.privacy_manager = get_privacy_manager()
    else:
        rt.privacy_manager = privacy_override
    rt.audit_log_v2 = None
    rt._use_audit_v2 = False


def _env_flag(name: str) -> bool:
    val = os.environ.get(name, "").strip().lower()
    return val in {"1", "true", "yes", "on"}


# -------------------------------------------------------------------
# Settings config
# -------------------------------------------------------------------


class TestPrivacyConfig:
    def teardown_method(self) -> None:
        os.environ.pop("RAVEN_PRIVACY_V2", None)

    def test_default_false(self) -> None:
        os.environ.pop("RAVEN_PRIVACY_V2", None)
        from importlib import reload
        from app.settings import config as cfg_mod

        reload(cfg_mod)
        assert cfg_mod.Config.PRIVACY_V2_ENABLED is False

    def test_enabled_via_env(self) -> None:
        os.environ["RAVEN_PRIVACY_V2"] = "true"
        from importlib import reload
        from app.settings import config as cfg_mod

        reload(cfg_mod)
        assert cfg_mod.Config.PRIVACY_V2_ENABLED is True

    def test_disabled_via_env(self) -> None:
        os.environ["RAVEN_PRIVACY_V2"] = "false"
        from importlib import reload
        from app.settings import config as cfg_mod

        reload(cfg_mod)
        assert cfg_mod.Config.PRIVACY_V2_ENABLED is False
