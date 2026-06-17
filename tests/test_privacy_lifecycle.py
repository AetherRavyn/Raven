"""Tests for app.core.privacy.lifecycle (Day 28)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.core.privacy.consent import ConsentLevel, ConsentStore, DataClass
from app.core.privacy.lifecycle import (
    AccessAuditEntry,
    DeleteResult,
    ExportArchive,
    LifecycleManager,
    get_default_lifecycle_manager,
    reset_default_lifecycle_manager,
    set_default_lifecycle_manager,
)
from app.core.privacy.retention import RetentionManager, RetentionPolicy


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    reset_default_lifecycle_manager()
    yield
    reset_default_lifecycle_manager()


@pytest.fixture
def consent() -> ConsentStore:
    return ConsentStore()


@pytest.fixture
def retention() -> RetentionManager:
    return RetentionManager(policy=RetentionPolicy())


@pytest.fixture
def lm(consent: ConsentStore, retention: RetentionManager) -> LifecycleManager:
    return LifecycleManager(consent=consent, retention=retention)


# --------------------------------------------------------------------------- #
# Provider registration                                                      #
# --------------------------------------------------------------------------- #


class TestProviders:
    def test_register_export(self, lm: LifecycleManager) -> None:
        def provider(uid: str) -> dict[str, object]:
            return {"count": 1}

        lm.register_export_provider("memory", provider)
        assert "memory" in lm.export_providers()

    def test_register_delete(self, lm: LifecycleManager) -> None:
        lm.register_delete_provider("memory", lambda uid: {"items": 5})
        assert "memory" in lm.delete_providers()

    def test_unregister(self, lm: LifecycleManager) -> None:
        lm.register_export_provider("memory", lambda uid: {})
        lm.unregister("memory")
        assert "memory" not in lm.export_providers()

    def test_providers_listed(self, lm: LifecycleManager) -> None:
        lm.register_export_provider("a", lambda uid: {})
        lm.register_export_provider("b", lambda uid: {})
        assert set(lm.export_providers()) == {"a", "b"}


# --------------------------------------------------------------------------- #
# Export                                                                     #
# --------------------------------------------------------------------------- #


class TestExport:
    def test_export_empty(self, lm: LifecycleManager) -> None:
        archive = lm.export_all("u1")
        assert archive.user_id == "u1"
        assert archive.consent == []
        assert archive.retention == []

    def test_export_includes_consent(
        self,
        lm: LifecycleManager,
        consent: ConsentStore,
    ) -> None:
        consent.grant("u1", DataClass.LOCATION, ConsentLevel.ALLOW)
        consent.grant("u1", DataClass.EMAIL, ConsentLevel.DENY)
        archive = lm.export_all("u1")
        assert len(archive.consent) == 2

    def test_export_includes_retention(
        self,
        lm: LifecycleManager,
        retention: RetentionManager,
    ) -> None:
        retention.mark_for_purge("rec_1", DataClass.LOCATION, "u1")
        archive = lm.export_all("u1")
        assert len(archive.retention) == 1

    def test_export_includes_sections(self, lm: LifecycleManager) -> None:
        lm.register_export_provider("memory", lambda uid: {"facts": ["a", "b"]})
        lm.register_export_provider("kg", lambda uid: {"nodes": 42})
        archive = lm.export_all("u1")
        assert archive.sections["memory"] == {"facts": ["a", "b"]}
        assert archive.sections["kg"] == {"nodes": 42}

    def test_export_provider_error_captured(self, lm: LifecycleManager) -> None:
        def bad(uid: str) -> dict[str, object]:
            raise RuntimeError("boom")

        lm.register_export_provider("broken", bad)
        archive = lm.export_all("u1")
        assert "error" in archive.sections["broken"]

    def test_export_records_access_audit(self, lm: LifecycleManager) -> None:
        lm.export_all("u1", actor="test")
        log = lm.access_log(user_id="u1")
        assert len(log) == 1
        assert log[0].action == "export"


# --------------------------------------------------------------------------- #
# Delete                                                                     #
# --------------------------------------------------------------------------- #


class TestDelete:
    def test_delete_empty(self, lm: LifecycleManager) -> None:
        result = lm.delete_user("u1")
        assert result.user_id == "u1"
        assert result.total_deleted == 0

    def test_delete_clears_consent(
        self,
        lm: LifecycleManager,
        consent: ConsentStore,
    ) -> None:
        consent.grant("u1", DataClass.LOCATION, ConsentLevel.ALLOW)
        consent.grant("u1", DataClass.EMAIL, ConsentLevel.DENY)
        result = lm.delete_user("u1")
        assert result.consent_cleared == 2
        assert consent.check("u1", DataClass.LOCATION) is None

    def test_delete_clears_retention(
        self,
        lm: LifecycleManager,
        retention: RetentionManager,
    ) -> None:
        retention.mark_for_purge("rec_1", DataClass.LOCATION, "u1")
        retention.mark_for_purge("rec_2", DataClass.EMAIL, "u1")
        result = lm.delete_user("u1")
        assert result.retention_cleared == 2

    def test_delete_calls_providers(self, lm: LifecycleManager) -> None:
        lm.register_delete_provider("memory", lambda uid: {"items": 10})
        lm.register_delete_provider("kg", lambda uid: {"nodes": 3})
        result = lm.delete_user("u1")
        assert result.provider_counts.get("memory.items") == 10
        assert result.provider_counts.get("kg.nodes") == 3

    def test_delete_provider_error(self, lm: LifecycleManager) -> None:
        def bad(uid: str) -> dict[str, int]:
            raise RuntimeError("kaboom")

        lm.register_delete_provider("broken", bad)
        result = lm.delete_user("u1")
        # No positive counts, but no crash.
        assert "broken.error" not in result.provider_counts

    def test_delete_records_access_audit(self, lm: LifecycleManager) -> None:
        lm.delete_user("u1", actor="test")
        log = lm.access_log(user_id="u1")
        assert len(log) == 1
        assert log[0].action == "delete"


# --------------------------------------------------------------------------- #
# Access audit                                                                #
# --------------------------------------------------------------------------- #


class TestAccessAudit:
    def test_record_access(self, lm: LifecycleManager) -> None:
        lm.record_access(
            user_id="u1",
            data_class=DataClass.LOCATION,
            actor="test",
            action="read",
        )
        log = lm.access_log()
        assert len(log) == 1
        assert log[0].action == "read"

    def test_filter_by_user(self, lm: LifecycleManager) -> None:
        lm.record_access(user_id="u1", data_class=DataClass.LOCATION, actor="t", action="read")
        lm.record_access(user_id="u2", data_class=DataClass.LOCATION, actor="t", action="read")
        assert len(lm.access_log(user_id="u1")) == 1

    def test_filter_by_data_class(self, lm: LifecycleManager) -> None:
        lm.record_access(user_id="u1", data_class=DataClass.LOCATION, actor="t", action="read")
        lm.record_access(user_id="u1", data_class=DataClass.EMAIL, actor="t", action="read")
        assert len(lm.access_log(data_class=DataClass.LOCATION)) == 1

    def test_reset_clears_log(self, lm: LifecycleManager) -> None:
        lm.record_access(user_id="u1", data_class=DataClass.LOCATION, actor="t", action="read")
        lm.reset()
        assert len(lm.access_log()) == 0


# --------------------------------------------------------------------------- #
# ExportArchive serialisation                                                #
# --------------------------------------------------------------------------- #


class TestExportArchive:
    def test_to_json_round_trip(self) -> None:
        archive = ExportArchive(
            user_id="u1",
            exported_at=datetime.now(timezone.utc),
            consent=[{"data_class": "location"}],
        )
        text = archive.to_json()
        loaded = ExportArchive.from_dict(json.loads(text))
        assert loaded.user_id == "u1"
        assert loaded.consent == [{"data_class": "location"}]

    def test_to_dict_includes_all_sections(self) -> None:
        archive = ExportArchive(
            user_id="u1",
            exported_at=datetime(2026, 6, 17, tzinfo=timezone.utc),
        )
        d = archive.to_dict()
        assert d["user_id"] == "u1"
        assert d["exported_at"] == "2026-06-17T00:00:00+00:00"


# --------------------------------------------------------------------------- #
# DeleteResult                                                                #
# --------------------------------------------------------------------------- #


class TestDeleteResult:
    def test_total_deleted(self) -> None:
        r = DeleteResult(
            user_id="u1",
            deleted_at=datetime.now(timezone.utc),
            consent_cleared=2,
            retention_cleared=3,
            provider_counts={"memory.items": 10},
        )
        assert r.total_deleted == 15

    def test_to_dict(self) -> None:
        r = DeleteResult(
            user_id="u1",
            deleted_at=datetime(2026, 6, 17, tzinfo=timezone.utc),
            consent_cleared=1,
        )
        d = r.to_dict()
        assert d["consent_cleared"] == 1
        assert d["total_deleted"] == 1


# --------------------------------------------------------------------------- #
# AccessAuditEntry                                                            #
# --------------------------------------------------------------------------- #


class TestAccessAuditEntry:
    def test_to_dict(self) -> None:
        e = AccessAuditEntry(
            user_id="u1",
            data_class=DataClass.LOCATION,
            actor="test",
            action="read",
            timestamp=datetime(2026, 6, 17, tzinfo=timezone.utc),
        )
        d = e.to_dict()
        assert d["user_id"] == "u1"
        assert d["data_class"] == "location"
        assert d["action"] == "read"


# --------------------------------------------------------------------------- #
# Singleton                                                                   #
# --------------------------------------------------------------------------- #


class TestSingleton:
    def test_get_default(self) -> None:
        m1 = get_default_lifecycle_manager()
        m2 = get_default_lifecycle_manager()
        assert m1 is m2

    def test_set_replaces(self) -> None:
        custom = LifecycleManager()
        set_default_lifecycle_manager(custom)
        try:
            assert get_default_lifecycle_manager() is custom
        finally:
            set_default_lifecycle_manager(None)
        assert get_default_lifecycle_manager() is not custom
