"""Tests for app.core.audit.redaction."""

from __future__ import annotations



from app.core.audit.redaction import (
    DEFAULT_PLACEHOLDER,
    RedactionConfig,
    redact_dict,
    safe_for_log,
)


# ---------------------------------------------------------------------------
# Default rules
# ---------------------------------------------------------------------------


class TestDefaultRules:
    def test_openai_key_redacted(self) -> None:
        out = redact_dict({"text": "key=sk-abcdefghijklmnopqrstuv"})
        assert "sk-abcdefghijklmnopqrstuv" not in out["text"]
        assert DEFAULT_PLACEHOLDER in out["text"]

    def test_anthropic_key_redacted(self) -> None:
        out = redact_dict({"text": "sk-ant-abcdefghijklmnopqrstuvwxyz1234"})
        assert "sk-ant-" not in out["text"]

    def test_aws_access_key_redacted(self) -> None:
        out = redact_dict({"text": "AKIAIOSFODNN7EXAMPLE"})
        assert "AKIAIOSFODNN7EXAMPLE" not in out["text"]

    def test_google_api_key_redacted(self) -> None:
        # 35 chars after "AIza" — matches the regex.
        out = redact_dict(
            {"text": "AIza" + "a" * 35}
        )
        assert "AIza" not in out["text"]

    def test_github_token_redacted(self) -> None:
        out = redact_dict({"text": "ghp_" + "A" * 40})
        assert "ghp_" not in out["text"]

    def test_slack_token_redacted(self) -> None:
        out = redact_dict({"text": "xoxb-1234567890-abcdefghij"})
        assert "xoxb-1234567890" not in out["text"]

    def test_private_key_block_redacted(self) -> None:
        text = "-----BEGIN RSA PRIVATE KEY-----\nfoo\n-----END RSA PRIVATE KEY-----"
        out = redact_dict({"text": text})
        assert "BEGIN RSA PRIVATE KEY" not in out["text"]
        assert "foo" not in out["text"]

    def test_jwt_redacted(self) -> None:
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.SflKxw"
        out = redact_dict({"text": f"token={jwt}"})
        assert jwt not in out["text"]

    def test_bearer_token_redacted(self) -> None:
        out = redact_dict({"header": "Bearer abcdefghij1234567890"})
        assert "abcdefghij1234567890" not in out["header"]
        assert "Bearer" in out["header"]

    def test_keyvalue_secret_redacted(self) -> None:
        out = redact_dict(
            {"config": "api_key=abcdef12345 other=value"}
        )
        assert "abcdef12345" not in out["config"]
        assert "other=value" in out["config"]


# ---------------------------------------------------------------------------
# Field-name heuristic
# ---------------------------------------------------------------------------


class TestFieldNameHeuristic:
    def test_password_field_redacted(self) -> None:
        out = redact_dict({"password": "hunter2"})
        assert "hunter2" not in str(out)

    def test_api_key_field_redacted(self) -> None:
        out = redact_dict({"api_key": "anything"})
        assert "anything" not in str(out)

    def test_token_field_redacted(self) -> None:
        out = redact_dict({"auth_token": "abc"})
        assert "abc" not in str(out)

    def test_non_secret_field_kept(self) -> None:
        out = redact_dict({"user_id": "u1", "action": "list"})
        assert out["user_id"] == "u1"
        assert out["action"] == "list"

    def test_partial_match_kept(self) -> None:
        # "tokenizer" is not a credential field, just a name.
        out = redact_dict({"tokenizer": "BPE"})
        assert out["tokenizer"] == "BPE"


# ---------------------------------------------------------------------------
# Nested structures
# ---------------------------------------------------------------------------


class TestNestedStructures:
    def test_nested_dict_redacted(self) -> None:
        out = redact_dict(
            {"context": {"password": "p", "name": "alice"}}
        )
        assert out["context"]["name"] == "alice"
        # The "p" char appears in the key "password" itself, so we
        # assert the value is the redaction placeholder.
        assert out["context"]["password"] == "[***REDACTED*** (field_name)]"

    def test_list_redacted(self) -> None:
        out = redact_dict({"secrets": ["sk-aaaaaaaaaaaaaaaaaaaaaa", "ok"]})
        assert "sk-aaaaaaaaaaaaaaaaaaaaaa" not in out["secrets"][0]
        assert out["secrets"][1] == "ok"

    def test_deeply_nested(self) -> None:
        out = redact_dict(
            {"a": {"b": {"c": {"password": "deep"}}}}
        )
        assert "deep" not in str(out)


# ---------------------------------------------------------------------------
# Optional rules
# ---------------------------------------------------------------------------


class TestOptionalRules:
    def test_email_redacted_by_default(self) -> None:
        out = redact_dict({"text": "contact alice@example.com"})
        assert "alice@example.com" not in out["text"]

    def test_email_not_redacted_when_disabled(self) -> None:
        cfg = RedactionConfig(redact_emails=False)
        out = redact_dict({"text": "contact alice@example.com"}, config=cfg)
        assert "alice@example.com" in out["text"]

    def test_credit_card_redacted_by_default(self) -> None:
        out = redact_dict({"text": "card 4111 1111 1111 1111"})
        assert "4111 1111 1111 1111" not in out["text"]

    def test_credit_card_not_redacted_when_disabled(self) -> None:
        cfg = RedactionConfig(redact_credit_cards=False)
        out = redact_dict(
            {"text": "card 4111 1111 1111 1111"}, config=cfg
        )
        assert "4111 1111 1111 1111" in out["text"]


# ---------------------------------------------------------------------------
# Custom config
# ---------------------------------------------------------------------------


class TestCustomConfig:
    def test_extra_pattern(self) -> None:
        cfg = RedactionConfig(extra_patterns=[("foo", r"\bFOO-\d{4}\b")])
        out = redact_dict({"text": "FOO-1234 bar"}, config=cfg)
        assert "FOO-1234" not in out["text"]
        assert "bar" in out["text"]

    def test_disabled_rule_skipped(self) -> None:
        cfg = RedactionConfig(disabled={"openai_key"})
        out = redact_dict({"text": "sk-abcdefghijklmnopqrstuv"}, config=cfg)
        # The key should be present (not redacted) because we disabled
        # the openai_key rule.
        assert "sk-abcdefghijklmnopqrstuv" in out["text"]

    def test_custom_placeholder(self) -> None:
        cfg = RedactionConfig(placeholder="<HIDDEN>")
        out = redact_dict({"text": "sk-abcdefghijklmnopqrstuv"}, config=cfg)
        assert "<HIDDEN>" in out["text"]
        assert DEFAULT_PLACEHOLDER not in out["text"]

    def test_extra_overrides_default_by_name(self) -> None:
        cfg = RedactionConfig(
            extra_patterns=[("openai_key", r"\bsk-X{20}\b")]
        )
        out = redact_dict(
            {"a": "sk-XXXXXXXXXXXXXXXXXXXX", "b": "sk-YYYYYYYYYYYYYYYYYYYY"},
            config=cfg,
        )
        # Custom rule matches sk-X
        assert "sk-X" not in out["a"]
        # sk-Y doesn't match the custom rule and the default was
        # overridden by name, so it stays visible.
        assert "sk-YYYY" in out["b"]


# ---------------------------------------------------------------------------
# safe_for_log
# ---------------------------------------------------------------------------


class TestSafeForLog:
    def test_string_redacted(self) -> None:
        out = safe_for_log("password=hunter2")
        assert "hunter2" not in out

    def test_dict_redacted(self) -> None:
        out = safe_for_log({"password": "hunter2"})
        assert "hunter2" not in out

    def test_non_string_passes_through(self) -> None:
        assert safe_for_log(42) == "42"
        assert safe_for_log(None) == "None"


# ---------------------------------------------------------------------------
# AuditEvent integration
# ---------------------------------------------------------------------------


class TestAuditEventIntegration:
    def test_event_to_dict_redacts(self) -> None:
        from app.core.audit import AuditEvent, AuditKind

        ev = AuditEvent(
            kind=AuditKind.CONFIG,
            actor="admin",
            action="set_api_key",
            detail="value is sk-abcdefghijklmnopqrstuv",
            metadata={"api_key": "secretvalue"},
        )
        d = ev.to_dict()
        assert "sk-abcdefghijklmnopqrstuv" not in str(d)
        assert "secretvalue" not in str(d)

    def test_event_to_dict_redact_false(self) -> None:
        from app.core.audit import AuditEvent, AuditKind

        ev = AuditEvent(
            kind=AuditKind.CONFIG,
            actor="admin",
            action="set",
            detail="value is sk-abcdefghijklmnopqrstuv",
        )
        d = ev.to_dict(redact=False)
        # Raw value preserved when redaction is off.
        assert "sk-abcdefghijklmnopqrstuv" in d["detail"]
