"""Tests for the privacy package (Day 19, Phase E)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.privacy import (
    ConsentLevel,
    ConsentStore,
    DataClass,
    PIIDetection,
    PIIDetector,
    PIIKind,
    PrivacyManager,
    RedactionPolicy,
    Redactor,
    RetentionManager,
    RetentionPolicy,
    all_default_kinds,
    detector_audit_safe,
    detector_with_kinds,
    redact_for_log,
)


# -------------------------------------------------------------------
# detection
# -------------------------------------------------------------------


class TestPIIDetection:
    def test_masks_email(self) -> None:
        d = PIIDetection(
            kind=PIIKind.EMAIL,
            value="alice@example.com",
            start=0,
            end=17,
            confidence=0.95,
            pattern_id="x",
        )
        assert "@" in d.masked
        assert "alice" not in d.masked

    def test_masks_short_value(self) -> None:
        d = PIIDetection(
            kind=PIIKind.API_KEY,
            value="abc",
            start=0,
            end=3,
            confidence=0.9,
            pattern_id="x",
        )
        assert d.masked == "***"

    def test_masks_ip(self) -> None:
        d = PIIDetection(
            kind=PIIKind.IP_ADDRESS,
            value="192.168.1.10",
            start=0,
            end=12,
            confidence=0.9,
            pattern_id="x",
        )
        assert d.masked.startswith("192.")
        assert d.masked.endswith(".10")

    def test_masks_dob(self) -> None:
        d = PIIDetection(
            kind=PIIKind.DATE_OF_BIRTH,
            value="1990-05-12",
            start=0,
            end=10,
            confidence=0.6,
            pattern_id="x",
        )
        assert d.masked == "****-**-**"


class TestPIIDetector:
    def test_email(self) -> None:
        d = PIIDetector()
        out = d.detect("Contact: alice@example.com")
        kinds = {x.kind for x in out}
        assert PIIKind.EMAIL in kinds

    def test_phone(self) -> None:
        d = PIIDetector()
        out = d.detect("Call me at 555-123-4567")
        assert any(x.kind == PIIKind.PHONE for x in out)

    def test_ssn(self) -> None:
        d = PIIDetector()
        out = d.detect("SSN: 123-45-6789")
        assert any(x.kind == PIIKind.SSN for x in out)

    def test_credit_card_luhn_valid(self) -> None:
        # 4111111111111111 is a well-known Luhn-valid test number
        d = PIIDetector()
        out = d.detect("Card: 4111-1111-1111-1111")
        assert any(x.kind == PIIKind.CREDIT_CARD for x in out)

    def test_credit_card_luhn_invalid(self) -> None:
        # 1234567890123456 fails Luhn
        d = PIIDetector()
        out = d.detect("Number: 1234-5678-9012-3456")
        # 1234-5678-9012-3456 — actually, let me check Luhn manually:
        # 1,2,3,4,5,6,7,8,9,0,1,2,3,4,5,6
        # doubled: 2,6,10->1,10->1,14->5,2,6,4,6,2
        # plus: 1+2+3+4+5+6+7+8+9+0+1+2+3+4+5+6 = 66 + 2+6+1+1+5+2+6+4+6+2 = 35
        # total = 66+35=101, not divisible by 10.  Luhn fails.
        assert not any(x.kind == PIIKind.CREDIT_CARD for x in out)

    def test_ip_optional(self) -> None:
        d_default = PIIDetector()
        out = d_default.detect("Server: 192.168.1.1")
        assert not any(x.kind == PIIKind.IP_ADDRESS for x in out)

        d_ip = PIIDetector(detect_ip=True)
        out = d_ip.detect("Server: 192.168.1.1")
        assert any(x.kind == PIIKind.IP_ADDRESS for x in out)

    def test_enabled_kinds_filters(self) -> None:
        d = PIIDetector(enabled_kinds={PIIKind.SSN})
        out = d.detect("alice@example.com SSN 123-45-6789")
        kinds = {x.kind for x in out}
        assert PIIKind.SSN in kinds
        assert PIIKind.EMAIL not in kinds

    def test_empty_text(self) -> None:
        d = PIIDetector()
        assert d.detect("") == []

    def test_register_custom_pattern(self) -> None:
        from app.core.privacy.detection import Pattern

        d = PIIDetector()
        d.register(
            Pattern(
                pattern_id="custom.foo",
                kind=PIIKind.OPAQUE_SECRET,
                regex=r"\bFOO-\d{4}\b",
                confidence=0.8,
            )
        )
        out = d.detect("token: FOO-1234")
        assert any(x.kind == PIIKind.OPAQUE_SECRET for x in out)

    def test_kinds_present(self) -> None:
        d = PIIDetector()
        kinds = d.kinds_present("alice@example.com 123-45-6789")
        assert PIIKind.EMAIL in kinds
        assert PIIKind.SSN in kinds


class TestDetectorFactories:
    def test_detector_with_kinds(self) -> None:
        d = detector_with_kinds(PIIKind.EMAIL)
        out = d.detect("alice@example.com 123-45-6789")
        kinds = {x.kind for x in out}
        assert kinds == {PIIKind.EMAIL}

    def test_detector_audit_safe(self) -> None:
        d = detector_audit_safe()
        out = d.detect("alice@example.com 123-45-6789 192.168.1.1")
        kinds = {x.kind for x in out}
        assert PIIKind.IP_ADDRESS not in kinds

    def test_all_default_kinds(self) -> None:
        kinds = set(all_default_kinds())
        assert PIIKind.EMAIL in kinds
        assert PIIKind.API_KEY in kinds


# -------------------------------------------------------------------
# redaction
# -------------------------------------------------------------------


class TestRedactor:
    def test_token_policy_replaces_value(self) -> None:
        r = Redactor()
        out = r.redact("Email: alice@example.com")
        assert "alice@example.com" not in out.text
        assert "<PII-EMAIL-1>" in out.text

    def test_full_policy(self) -> None:
        r = Redactor(policies={PIIKind.EMAIL: RedactionPolicy.FULL})
        out = r.redact("alice@example.com")
        assert "<EMAIL>" in out.text

    def test_partial_policy(self) -> None:
        r = Redactor(policies={PIIKind.EMAIL: RedactionPolicy.PARTIAL})
        out = r.redact("alice@example.com")
        # Should be something like "a***e@example.com"
        assert "alice" not in out.text
        assert "@example.com" in out.text

    def test_hash_policy(self) -> None:
        r = Redactor(policies={PIIKind.EMAIL: RedactionPolicy.HASH})
        out = r.redact("alice@example.com")
        assert "alice" not in out.text
        assert "<email:" in out.text

    def test_keep_policy(self) -> None:
        r = Redactor(policies={PIIKind.EMAIL: RedactionPolicy.KEEP})
        out = r.redact("alice@example.com")
        assert out.text == "alice@example.com"
        assert out.redactions == []

    def test_stable_tokens(self) -> None:
        r = Redactor()
        out = r.redact("alice@example.com and alice@example.com")
        # Same value → same token (stable).
        assert out.text.count("<PII-EMAIL-1>") == 2
        assert out.text.count("<PII-EMAIL-2>") == 0

    def test_unstable_tokens(self) -> None:
        r = Redactor(stable_tokens=False)
        out = r.redact("alice@example.com and alice@example.com")
        # Different tokens for the same value.
        assert "<PII-EMAIL-1>" in out.text
        assert "<PII-EMAIL-2>" in out.text

    def test_overlap_keeps_first(self) -> None:
        # credit_card.solid would match a 16-digit number; the
        # dashed form matches first because the pattern is
        # listed first.  We want the redactor to pick one,
        # not produce a mess.
        r = Redactor()
        out = r.redact("card: 4111-1111-1111-1111")
        # Should produce exactly one placeholder.
        assert out.text.count("<PII-") == 1
        assert len(out.redactions) == 1

    def test_no_pii_passes_through(self) -> None:
        r = Redactor()
        out = r.redact("hello world")
        assert out.text == "hello world"
        assert out.redactions == []

    def test_empty_text(self) -> None:
        r = Redactor()
        out = r.redact("")
        assert out.text == ""

    def test_unredact(self) -> None:
        r = Redactor()
        out = r.redact("alice@example.com")
        # Un-redact with the mapping.
        restored = Redactor.unredact(out.text, out.mapping)
        assert "alice@example.com" in restored

    def test_unredact_strict_missing_raises(self) -> None:
        with pytest.raises(KeyError):
            Redactor.unredact("text", {"<MISSING>": "v"}, strict=True)

    def test_set_policy(self) -> None:
        r = Redactor()
        r.set_policy(PIIKind.EMAIL, RedactionPolicy.FULL)
        out = r.redact("alice@example.com")
        assert "<EMAIL>" in out.text

    def test_redact_for_log_helper(self) -> None:
        text = "alice@example.com and 123-45-6789"
        out = redact_for_log(text)
        assert "alice@example.com" not in out
        assert "123-45-6789" not in out

    def test_multiple_kinds(self) -> None:
        r = Redactor()
        out = r.redact("alice@example.com 123-45-6789")
        assert "<PII-EMAIL-1>" in out.text
        assert "<PII-SSN-1>" in out.text
        assert len(out.redactions) == 2


# -------------------------------------------------------------------
# consent
# -------------------------------------------------------------------


class TestConsentStore:
    def test_grant_and_check(self) -> None:
        s = ConsentStore()
        s.grant("u1", DataClass.EMAIL, ConsentLevel.ALLOW)
        c = s.check("u1", DataClass.EMAIL)
        assert c is not None
        assert c.level == ConsentLevel.ALLOW

    def test_check_unknown_returns_none(self) -> None:
        s = ConsentStore()
        assert s.check("u1", DataClass.EMAIL) is None

    def test_revoke_sets_deny(self) -> None:
        s = ConsentStore()
        s.grant("u1", DataClass.EMAIL, ConsentLevel.ALLOW)
        assert s.revoke("u1", DataClass.EMAIL) is True
        c = s.check("u1", DataClass.EMAIL)
        assert c is not None
        assert c.level == ConsentLevel.DENY
        assert c.is_active is False

    def test_revoke_unknown_returns_false(self) -> None:
        s = ConsentStore()
        assert s.revoke("u1", DataClass.EMAIL) is False

    def test_ttl_expiry(self) -> None:
        s = ConsentStore()
        s.grant(
            "u1",
            DataClass.LOCATION,
            ConsentLevel.ALLOW,
            ttl=timedelta(milliseconds=10),
        )
        import time as _t

        _t.sleep(0.05)
        c = s.check("u1", DataClass.LOCATION)
        assert c is not None
        assert c.is_expired is True
        assert c.is_active is False

    def test_metadata(self) -> None:
        s = ConsentStore()
        s.grant(
            "u1",
            DataClass.EMAIL,
            ConsentLevel.ALLOW,
            metadata={"source": "onboarding"},
        )
        c = s.check("u1", DataClass.EMAIL)
        assert c is not None
        assert c.metadata == {"source": "onboarding"}

    def test_all_for_user(self) -> None:
        s = ConsentStore()
        s.grant("u1", DataClass.EMAIL, ConsentLevel.ALLOW)
        s.grant("u1", DataClass.LOCATION, ConsentLevel.DENY)
        s.grant("u2", DataClass.EMAIL, ConsentLevel.ALLOW)
        assert len(s.all_for_user("u1")) == 2
        assert len(s.all_for_user("u2")) == 1
        assert len(s.all_for_user("u3")) == 0

    def test_all_for_class(self) -> None:
        s = ConsentStore()
        s.grant("u1", DataClass.EMAIL, ConsentLevel.ALLOW)
        s.grant("u2", DataClass.EMAIL, ConsentLevel.DENY)
        s.grant("u1", DataClass.LOCATION, ConsentLevel.ALLOW)
        assert len(s.all_for_class(DataClass.EMAIL)) == 2

    def test_list_expired(self) -> None:
        s = ConsentStore()
        s.grant("u1", DataClass.EMAIL, ConsentLevel.ALLOW, ttl=timedelta(milliseconds=5))
        s.grant("u2", DataClass.EMAIL, ConsentLevel.ALLOW)
        import time as _t

        _t.sleep(0.05)
        expired = s.list_expired()
        assert len(expired) == 1
        assert expired[0].user_id == "u1"

    def test_clear_user(self) -> None:
        s = ConsentStore()
        s.grant("u1", DataClass.EMAIL, ConsentLevel.ALLOW)
        s.grant("u1", DataClass.LOCATION, ConsentLevel.ALLOW)
        s.grant("u2", DataClass.EMAIL, ConsentLevel.ALLOW)
        assert s.clear_user("u1") == 2
        assert s.all_for_user("u1") == []
        assert len(s.all_for_user("u2")) == 1

    def test_summary(self) -> None:
        s = ConsentStore()
        s.grant("u1", DataClass.EMAIL, ConsentLevel.ALLOW)
        s.grant("u2", DataClass.EMAIL, ConsentLevel.DENY)
        summary = s.summary()
        assert summary["total"] == 2
        assert summary["by_level"]["allow"] == 1
        assert summary["by_level"]["deny"] == 1


# -------------------------------------------------------------------
# retention
# -------------------------------------------------------------------


class TestRetentionPolicy:
    def test_default_ttl(self) -> None:
        p = RetentionPolicy()
        assert p.ttl_for(DataClass.EMAIL) == p.default_ttl

    def test_per_class_override(self) -> None:
        p = RetentionPolicy(by_class={DataClass.CREDENTIALS: timedelta(days=30)})
        assert p.ttl_for(DataClass.CREDENTIALS) == timedelta(days=30)
        assert p.ttl_for(DataClass.EMAIL) == p.default_ttl

    def test_compute_until_exempt(self) -> None:
        p = RetentionPolicy(exempt={DataClass.CREDENTIALS})
        assert p.compute_until(DataClass.CREDENTIALS) is None

    def test_compute_until_default(self) -> None:
        p = RetentionPolicy(default_ttl=timedelta(days=10))
        result = p.compute_until(DataClass.EMAIL)
        assert result is not None
        delta = result - datetime.now(timezone.utc)
        # 10 days +/- a few seconds
        assert 9 <= delta.days <= 10


class TestRetentionManager:
    def test_mark_for_purge_uses_default_ttl(self) -> None:
        p = RetentionPolicy(default_ttl=timedelta(days=10))
        m = RetentionManager(policy=p)
        r = m.mark_for_purge("r1", DataClass.EMAIL, "u1")
        assert r.retention_until is not None

    def test_mark_for_purge_exempt_no_until(self) -> None:
        p = RetentionPolicy(exempt={DataClass.CREDENTIALS})
        m = RetentionManager(policy=p)
        r = m.mark_for_purge("r1", DataClass.CREDENTIALS, "u1")
        assert r.retention_until is None

    def test_list_due(self) -> None:
        p = RetentionPolicy(default_ttl=timedelta(milliseconds=5))
        m = RetentionManager(policy=p)
        m.mark_for_purge("r1", DataClass.EMAIL, "u1")
        m.mark_for_purge("r2", DataClass.LOCATION, "u1")
        import time as _t

        _t.sleep(0.05)
        due = m.list_due()
        assert len(due) == 2

    def test_purge_due_no_purger_raises(self) -> None:
        m = RetentionManager()
        m.mark_for_purge("r1", DataClass.EMAIL, "u1")
        with pytest.raises(RuntimeError):
            m.purge_due()

    def test_purge_due_invokes_purger(self) -> None:
        seen: list[tuple[str, DataClass]] = []

        def my_purger(record_id: str, data_class: DataClass) -> None:
            seen.append((record_id, data_class))

        p = RetentionPolicy(default_ttl=timedelta(milliseconds=5))
        m = RetentionManager(policy=p, purger=my_purger)
        m.mark_for_purge("r1", DataClass.EMAIL, "u1")
        m.mark_for_purge("r2", DataClass.LOCATION, "u1")
        import time as _t

        _t.sleep(0.05)
        purged = m.purge_due()
        assert set(purged) == {"r1", "r2"}
        assert set(seen) == {
            ("r1", DataClass.EMAIL),
            ("r2", DataClass.LOCATION),
        }
        # Records are gone after a successful purge.
        assert m.list_due() == []

    def test_purge_due_handles_purger_exception(self) -> None:
        def bad_purger(record_id: str, data_class: DataClass) -> None:
            if record_id == "r1":
                raise RuntimeError("explode")

        p = RetentionPolicy(default_ttl=timedelta(milliseconds=5))
        m = RetentionManager(policy=p, purger=bad_purger)
        m.mark_for_purge("r1", DataClass.EMAIL, "u1")
        m.mark_for_purge("r2", DataClass.LOCATION, "u1")
        import time as _t

        _t.sleep(0.05)
        purged = m.purge_due()
        # r1 raises, so it stays.  r2 succeeds.
        assert purged == ["r2"]
        assert len(m.list_due()) == 1

    def test_purge_user(self) -> None:
        seen: list[tuple[str, DataClass]] = []

        def my_purger(record_id: str, data_class: DataClass) -> None:
            seen.append((record_id, data_class))

        cs = ConsentStore()
        cs.grant("u1", DataClass.EMAIL, ConsentLevel.ALLOW)
        m = RetentionManager(purger=my_purger, consent_store=cs)
        m.mark_for_purge("r1", DataClass.EMAIL, "u1")
        m.mark_for_purge("r2", DataClass.LOCATION, "u1")
        m.mark_for_purge("r3", DataClass.EMAIL, "u2")
        purged = m.purge_user("u1", reason="gdpr")
        assert set(purged) == {"r1", "r2"}
        assert cs.check("u1", DataClass.EMAIL) is None
        # u2 untouched
        assert m.get("r3") is not None

    def test_cancel(self) -> None:
        m = RetentionManager()
        m.mark_for_purge("r1", DataClass.EMAIL, "u1")
        assert m.cancel("r1") is True
        assert m.get("r1") is None

    def test_cancel_unknown(self) -> None:
        m = RetentionManager()
        assert m.cancel("nope") is False

    def test_clear_user(self) -> None:
        m = RetentionManager()
        m.mark_for_purge("r1", DataClass.EMAIL, "u1")
        m.mark_for_purge("r2", DataClass.EMAIL, "u2")
        assert m.clear_user("u1") == 1
        assert m.get("r1") is None
        assert m.get("r2") is not None

    def test_explain(self) -> None:
        p = RetentionPolicy(default_ttl=timedelta(days=30))
        m = RetentionManager(policy=p)
        m.mark_for_purge("r1", DataClass.EMAIL, "u1")
        m.mark_for_purge("r2", DataClass.LOCATION, "u1")
        out = m.explain()
        assert out["total"] == 2
        assert out["by_class"]["email"] == 1
        assert out["by_class"]["location"] == 1
        assert out["default_ttl_days"] == 30


# -------------------------------------------------------------------
# PrivacyManager (orchestrator)
# -------------------------------------------------------------------


class TestPrivacyManager:
    def test_default_construction(self) -> None:
        pm = PrivacyManager()
        assert pm.detector() is not None
        assert pm.redactor() is not None

    def test_redact_text(self) -> None:
        pm = PrivacyManager()
        out = pm.redact_text("alice@example.com")
        assert "alice@example.com" not in out.text

    def test_grant_and_is_allowed(self) -> None:
        pm = PrivacyManager()
        pm.grant_consent("u1", DataClass.EMAIL, ConsentLevel.ALLOW)
        assert pm.is_allowed("u1", DataClass.EMAIL) is True

    def test_is_allowed_no_consent(self) -> None:
        pm = PrivacyManager()
        # No consent = default deny.
        assert pm.is_allowed("u1", DataClass.EMAIL) is False

    def test_is_allowed_deny(self) -> None:
        pm = PrivacyManager()
        pm.grant_consent("u1", DataClass.EMAIL, ConsentLevel.DENY)
        assert pm.is_allowed("u1", DataClass.EMAIL) is False

    def test_revoke(self) -> None:
        pm = PrivacyManager()
        pm.grant_consent("u1", DataClass.EMAIL, ConsentLevel.ALLOW)
        assert pm.revoke_consent("u1", DataClass.EMAIL) is True
        assert pm.is_allowed("u1", DataClass.EMAIL) is False

    def test_schedule_retention(self) -> None:
        pm = PrivacyManager()
        r = pm.schedule_retention("r1", DataClass.CONVERSATION, "u1")
        assert r.record_id == "r1"

    def test_purge_due(self) -> None:
        seen: list[str] = []

        def my_purger(record_id: str, data_class: DataClass) -> None:
            seen.append(record_id)

        pm = PrivacyManager()
        pm.set_purger(my_purger)
        pm.schedule_retention("r1", DataClass.CONVERSATION, "u1")
        # Default TTL is 90 days, so it won't be due yet.
        assert pm.purge_due() == []
        assert seen == []

    def test_delete_user(self) -> None:
        seen: list[str] = []

        def my_purger(record_id: str, data_class: DataClass) -> None:
            seen.append(record_id)

        pm = PrivacyManager()
        pm.set_purger(my_purger)
        pm.grant_consent("u1", DataClass.EMAIL, ConsentLevel.ALLOW)
        pm.schedule_retention("r1", DataClass.EMAIL, "u1")
        purged = pm.delete_user("u1", reason="gdpr")
        assert purged == ["r1"]
        assert pm.check_consent("u1", DataClass.EMAIL) is None

    def test_redact_for_log(self) -> None:
        pm = PrivacyManager()
        out = pm.redact_for_log("alice@example.com 123-45-6789")
        assert "alice@example.com" not in out
        assert "123-45-6789" not in out

    def test_explain(self) -> None:
        pm = PrivacyManager()
        pm.grant_consent("u1", DataClass.EMAIL, ConsentLevel.ALLOW)
        out = pm.explain()
        assert "consent" in out
        assert "retention" in out
        assert out["consent"]["by_level"]["allow"] == 1
