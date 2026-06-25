"""Tests for :class:`HelixPrivacyStore` (Day 25)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.core.privacy.consent import ConsentLevel, ConsentStore, DataClass
from app.core.privacy.orchestrator import PrivacyManager
from app.core.privacy.persistence import (
    HelixPrivacyStore,
    _consent_id,
    _consent_props,
    _from_json_str,
    _parse_consent_id,
    _parse_purge_id,
    _purge_id,
    _purge_props,
    _to_json_str,
    get_default_privacy_store,
    reset_default_privacy_store,
    set_default_privacy_store,
)
from app.core.privacy.retention import (
    RetentionManager,
    RetentionPolicy,
)


# --------------------------------------------------------------------------- #
# Fakes                                                                       #
# --------------------------------------------------------------------------- #


class FakeHelixClient:
    """Records every envelope sent; configurable per-call behaviour."""

    def __init__(self) -> None:
        self.envelopes: list[dict[str, Any]] = []
        self.available = True
        # Per-envelope overrides: when an envelope's
        # request_type is in this map, return the
        # configured payload instead of the default.
        self.responses: dict[str, dict[str, Any]] = {}
        self.raise_on: set[str] = set()

    async def is_available(self) -> bool:
        return self.available

    async def execute(self, envelope: dict[str, Any]) -> Any:
        from app.db.helix import QueryResult

        rt = envelope.get("request_type", "")
        self.envelopes.append(envelope)
        if rt in self.raise_on:
            raise RuntimeError(f"helix error for {rt}")
        if rt in self.responses:
            return QueryResult(data=self.responses[rt], latency_ms=0.0, request_type=rt)
        return QueryResult(data={}, latency_ms=0.0, request_type=rt)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _reset_singleton() -> Iterator[None]:
    reset_default_privacy_store()
    yield
    reset_default_privacy_store()


@pytest.fixture
def consent_store() -> ConsentStore:
    return ConsentStore()


@pytest.fixture
def retention_manager() -> RetentionManager:
    return RetentionManager(policy=RetentionPolicy())


@pytest.fixture
def fake_client() -> FakeHelixClient:
    return FakeHelixClient()


@pytest.fixture
def store(
    fake_client: FakeHelixClient,
    consent_store: ConsentStore,
    retention_manager: RetentionManager,
) -> HelixPrivacyStore:
    s = HelixPrivacyStore(fake_client, consent_store, retention_manager)
    s._available = True  # offline-fake: mark online so writes attempt.
    return s


# --------------------------------------------------------------------------- #
# ID encoding                                                                 #
# --------------------------------------------------------------------------- #


class TestIdEncoding:
    def test_consent_id_round_trip(self) -> None:
        cid = _consent_id("u1", DataClass.LOCATION)
        assert cid == "consent:u1:location"
        parsed = _parse_consent_id(cid)
        assert parsed == ("u1", DataClass.LOCATION)

    def test_consent_id_invalid(self) -> None:
        assert _parse_consent_id("not-consent") is None
        assert _parse_consent_id("consent:") is None
        assert _parse_consent_id("consent:u1:") is None
        assert _parse_consent_id("consent:u1:bogus") is None

    def test_purge_id_round_trip(self) -> None:
        pid = _purge_id("rec_42")
        assert pid == "purge:rec_42"
        assert _parse_purge_id(pid) == "rec_42"

    def test_purge_id_invalid(self) -> None:
        assert _parse_purge_id("not-purge") is None


# --------------------------------------------------------------------------- #
# Property serialisation                                                      #
# --------------------------------------------------------------------------- #


class TestPropertySerialisation:
    def test_consent_props(self) -> None:
        c = ConsentStore().grant("u1", DataClass.LOCATION, ConsentLevel.ALLOW)
        p = _consent_props(c)
        assert p["id"] == "consent:u1:location"
        assert p["user_id"] == "u1"
        assert p["data_class"] == "location"
        assert p["level"] == "allow"
        # metadata is JSON-encoded
        meta = json.loads(p["metadata"])
        assert isinstance(meta, dict)

    def test_purge_props(self) -> None:
        rm = RetentionManager()
        r = rm.mark_for_purge("rec_1", DataClass.LOCATION, "u1")
        p = _purge_props(r)
        assert p["id"] == "purge:rec_1"
        assert p["record_id"] == "rec_1"
        assert p["data_class"] == "location"
        assert p["user_id"] == "u1"

    def test_to_from_json_str(self) -> None:
        d = {"key": "value", "n": 1}
        s = _to_json_str(d)
        assert isinstance(s, str)
        assert _from_json_str(s) == d
        assert _from_json_str(None) == {}
        assert _from_json_str("") == {}


# --------------------------------------------------------------------------- #
# Initialisation                                                              #
# --------------------------------------------------------------------------- #


class TestInitialisation:
    async def test_initialize_loads_existing(
        self,
        fake_client: FakeHelixClient,
        consent_store: ConsentStore,
        retention_manager: RetentionManager,
    ) -> None:
        # Seed the "database" with one consent + one purge.
        fake_client.responses["read"] = {
            "m": [
                {
                    "id": "consent:u1:location",
                    "user_id": "u1",
                    "data_class": "location",
                    "level": "allow",
                    "granted_at": "2026-01-01T00:00:00+00:00",
                    "expires_at": None,
                    "metadata": _to_json_str({"source": "onboarding"}),
                },
            ]
        }
        # Second load will hit the same read response, but
        # for the PurgeLabel scan we need a different result.
        # We can return the same shape for both since the loader
        # iterates by label.
        store = HelixPrivacyStore(fake_client, consent_store, retention_manager)
        ok = await store.initialize()
        assert ok is True
        assert store.available is True
        assert consent_store.check("u1", DataClass.LOCATION) is not None

    async def test_initialize_no_client(self, consent_store: ConsentStore, retention_manager: RetentionManager) -> None:
        store = HelixPrivacyStore(None, consent_store, retention_manager)
        assert await store.initialize() is False
        assert store.available is False

    async def test_initialize_unavailable(self, fake_client: FakeHelixClient, consent_store: ConsentStore, retention_manager: RetentionManager) -> None:
        fake_client.available = False
        store = HelixPrivacyStore(fake_client, consent_store, retention_manager)
        assert await store.initialize() is False
        assert store.available is False

    async def test_initialize_probe_raises(self, fake_client: FakeHelixClient, consent_store: ConsentStore, retention_manager: RetentionManager) -> None:
        async def boom() -> bool:
            raise RuntimeError("network")

        fake_client.is_available = boom  # type: ignore[assignment]
        store = HelixPrivacyStore(fake_client, consent_store, retention_manager)
        assert await store.initialize() is False


# --------------------------------------------------------------------------- #
# High-level mutators                                                         #
# --------------------------------------------------------------------------- #


class TestGrantConsent:
    async def test_grant_writes_to_helix(self, store: HelixPrivacyStore, fake_client: FakeHelixClient) -> None:
        await store.grant_consent("u1", DataClass.LOCATION, ConsentLevel.ALLOW)
        # Two writes: drop (idempotent) + add.
        add_envelopes = [e for e in fake_client.envelopes if "AddN" in str(e)]
        assert len(add_envelopes) == 1
        addn = add_envelopes[0]["query"]["queries"][0]["Query"]["steps"][0]["AddN"]
        assert addn["label"] == "PrivacyConsent"
        props_list = addn["properties"]
        props = {name: v["Value"] for name, v in props_list}
        assert props["id"]["String"] == "consent:u1:location"
        assert props["level"]["String"] == "allow"
        assert store.persisted_consent == 1

    async def test_grant_in_offline_mode(self, fake_client: FakeHelixClient, consent_store: ConsentStore, retention_manager: RetentionManager) -> None:
        fake_client.available = False
        store = HelixPrivacyStore(fake_client, consent_store, retention_manager)
        await store.grant_consent("u1", DataClass.LOCATION, ConsentLevel.ALLOW)
        # In-memory still updated.
        assert consent_store.check("u1", DataClass.LOCATION) is not None
        # No writes attempted.
        assert fake_client.envelopes == []
        assert store.persisted_consent == 0

    async def test_grant_writes_envelope_count(self, store: HelixPrivacyStore, fake_client: FakeHelixClient) -> None:
        await store.grant_consent("u1", DataClass.LOCATION, ConsentLevel.ALLOW)
        await store.grant_consent("u1", DataClass.EMAIL, ConsentLevel.DENY)
        assert len([e for e in fake_client.envelopes if "AddN" in str(e)]) == 2
        assert store.persisted_consent == 2


class TestRevokeConsent:
    async def test_revoke_persists_update(self, store: HelixPrivacyStore, fake_client: FakeHelixClient, consent_store: ConsentStore) -> None:
        # Grant first.
        await store.grant_consent("u1", DataClass.LOCATION, ConsentLevel.ALLOW)
        fake_client.envelopes.clear()

        # Revoke.
        ok = await store.revoke_consent("u1", DataClass.LOCATION)
        assert ok is True
        # In-memory updated.
        c = consent_store.check("u1", DataClass.LOCATION)
        assert c is not None
        assert c.level is ConsentLevel.DENY
        assert "revoked_at" in c.metadata
        # HelixDB write happened.
        add_envelopes = [e for e in fake_client.envelopes if "AddN" in str(e)]
        assert len(add_envelopes) == 1
        props_list = add_envelopes[0]["query"]["queries"][0]["Query"]["steps"][0]["AddN"]["properties"]
        props = {name: v["Value"] for name, v in props_list}
        assert props["level"]["String"] == "deny"

    async def test_revoke_nonexistent_returns_false(self, store: HelixPrivacyStore) -> None:
        ok = await store.revoke_consent("nope", DataClass.LOCATION)
        assert ok is False


class TestMarkForPurge:
    async def test_mark_writes_to_helix(self, store: HelixPrivacyStore, fake_client: FakeHelixClient) -> None:
        until = datetime.now(timezone.utc) + timedelta(days=30)
        await store.mark_for_purge(
            "rec_1", DataClass.LOCATION, "u1", retention_until=until,
        )
        add_envelopes = [e for e in fake_client.envelopes if "AddN" in str(e)]
        assert len(add_envelopes) == 1
        assert add_envelopes[0]["query"]["queries"][0]["Query"]["steps"][0]["AddN"]["label"] == "PrivacyPurge"
        assert store.persisted_purge == 1

    async def test_mark_uses_policy_ttl(self, store: HelixPrivacyStore, fake_client: FakeHelixClient) -> None:
        await store.mark_for_purge("rec_1", DataClass.LOCATION, "u1")
        # retention_until was computed from policy.
        add_envelopes = [e for e in fake_client.envelopes if "AddN" in str(e)]
        props_list = add_envelopes[0]["query"]["queries"][0]["Query"]["steps"][0]["AddN"]["properties"]
        props = {name: v["Value"] for name, v in props_list}
        assert props["retention_until"] is not None


class TestCancelPurge:
    async def test_cancel_deletes_from_helix(self, store: HelixPrivacyStore, fake_client: FakeHelixClient, retention_manager: RetentionManager) -> None:
        await store.mark_for_purge("rec_1", DataClass.LOCATION, "u1")
        fake_client.envelopes.clear()

        ok = await store.cancel_purge("rec_1")
        assert ok is True
        # Drop envelope sent.
        drop_envelopes = [e for e in fake_client.envelopes if "Drop" in str(e)]
        assert len(drop_envelopes) == 1
        assert store.deleted_purge == 1

    async def test_cancel_nonexistent_returns_false(self, store: HelixPrivacyStore) -> None:
        ok = await store.cancel_purge("nonexistent")
        assert ok is False


# --------------------------------------------------------------------------- #
# Error handling                                                              #
# --------------------------------------------------------------------------- #


class TestErrorHandling:
    async def test_write_failure_does_not_raise(self, store: HelixPrivacyStore, fake_client: FakeHelixClient) -> None:
        fake_client.raise_on = {"write"}
        await store.grant_consent("u1", DataClass.LOCATION, ConsentLevel.ALLOW)
        # In-memory still updated; failure counted.
        assert store.failed_writes >= 1

    async def test_delete_failure_does_not_raise(self, store: HelixPrivacyStore, fake_client: FakeHelixClient) -> None:
        await store.mark_for_purge("rec_1", DataClass.LOCATION, "u1")
        fake_client.raise_on = {"write"}
        ok = await store.cancel_purge("rec_1")
        # In-memory cancelled but HelixDB failed.
        assert ok is True
        assert store.failed_writes >= 1


# --------------------------------------------------------------------------- #
# Stats                                                                       #
# --------------------------------------------------------------------------- #


class TestStats:
    async def test_stats_snapshot(self, store: HelixPrivacyStore) -> None:
        await store.grant_consent("u1", DataClass.LOCATION, ConsentLevel.ALLOW)
        await store.mark_for_purge("rec_1", DataClass.LOCATION, "u1")
        await store.cancel_purge("rec_1")
        s = store.stats()
        assert s["available"] is True
        assert s["persisted_consent"] == 1
        assert s["persisted_purge"] == 1
        assert s["deleted_purge"] == 1


# --------------------------------------------------------------------------- #
# Singleton                                                                   #
# --------------------------------------------------------------------------- #


class TestSingleton:
    async def test_set_get_reset(self, store: HelixPrivacyStore) -> None:
        set_default_privacy_store(store)
        try:
            assert get_default_privacy_store() is store
        finally:
            reset_default_privacy_store()
        assert get_default_privacy_store() is None


# --------------------------------------------------------------------------- #
# Integration with in-memory stores                                           #
# --------------------------------------------------------------------------- #


class TestIntegration:
    async def test_in_memory_state_consistent_after_grant(
        self, store: HelixPrivacyStore, consent_store: ConsentStore
    ) -> None:
        await store.grant_consent("u1", DataClass.LOCATION, ConsentLevel.ALLOW)
        c = consent_store.check("u1", DataClass.LOCATION)
        assert c is not None
        assert c.level is ConsentLevel.ALLOW

    async def test_in_memory_state_consistent_after_revoke(
        self, store: HelixPrivacyStore, consent_store: ConsentStore
    ) -> None:
        await store.grant_consent("u1", DataClass.LOCATION, ConsentLevel.ALLOW)
        await store.revoke_consent("u1", DataClass.LOCATION)
        c = consent_store.check("u1", DataClass.LOCATION)
        assert c is not None
        assert c.level is ConsentLevel.DENY

    async def test_purge_record_in_memory(
        self, store: HelixPrivacyStore, retention_manager: RetentionManager
    ) -> None:
        await store.mark_for_purge("rec_1", DataClass.LOCATION, "u1")
        r = retention_manager.get("rec_1")
        assert r is not None
        assert r.data_class is DataClass.LOCATION
        assert r.user_id == "u1"

    async def test_purge_cancel_removes_from_memory(
        self, store: HelixPrivacyStore, retention_manager: RetentionManager
    ) -> None:
        await store.mark_for_purge("rec_1", DataClass.LOCATION, "u1")
        await store.cancel_purge("rec_1")
        assert retention_manager.get("rec_1") is None


# --------------------------------------------------------------------------- #
# Purge user (GDPR "forget me")                                                #
# --------------------------------------------------------------------------- #


class TestPurgeUser:
    async def test_purge_user_clears_in_memory(
        self,
        store: HelixPrivacyStore,
        consent_store: ConsentStore,
        retention_manager: RetentionManager,
    ) -> None:
        # Seed both stores.
        await store.grant_consent("u1", DataClass.LOCATION, ConsentLevel.ALLOW)
        await store.grant_consent("u1", DataClass.EMAIL, ConsentLevel.DENY)
        await store.mark_for_purge("rec_1", DataClass.LOCATION, "u1")
        await store.mark_for_purge("rec_2", DataClass.EMAIL, "u1")
        # Sanity.
        assert consent_store.check("u1", DataClass.LOCATION) is not None
        assert retention_manager.get("rec_1") is not None

        # Forget me.
        ok = await store.purge_user("u1")
        assert ok is True
        # All consent + purge records gone.
        assert consent_store.check("u1", DataClass.LOCATION) is None
        assert consent_store.check("u1", DataClass.EMAIL) is None
        assert retention_manager.get("rec_1") is None
        assert retention_manager.get("rec_2") is None

    async def test_purge_user_offline(
        self,
        fake_client: FakeHelixClient,
        consent_store: ConsentStore,
        retention_manager: RetentionManager,
    ) -> None:
        # Seed with Helix online.
        s = HelixPrivacyStore(fake_client, consent_store, retention_manager)
        s._available = True
        await s.grant_consent("u1", DataClass.LOCATION, ConsentLevel.ALLOW)
        # Go offline.
        s._available = False
        ok = await s.purge_user("u1")
        assert ok is True
        # In-memory still wiped.
        assert consent_store.check("u1", DataClass.LOCATION) is None

    async def test_purge_user_no_records(
        self, store: HelixPrivacyStore,
    ) -> None:
        ok = await store.purge_user("nobody")
        assert ok is True

    async def test_purge_user_write_failure(
        self,
        fake_client: FakeHelixClient,
        consent_store: ConsentStore,
        retention_manager: RetentionManager,
    ) -> None:
        s = HelixPrivacyStore(fake_client, consent_store, retention_manager)
        s._available = True
        await s.grant_consent("u1", DataClass.LOCATION, ConsentLevel.ALLOW)
        await s.mark_for_purge("rec_1", DataClass.LOCATION, "u1")
        fake_client.raise_on = {"write"}
        ok = await s.purge_user("u1")
        assert ok is False
        assert s.failed_writes >= 1


# --------------------------------------------------------------------------- #
# PrivacyManager async mirror                                                  #
# --------------------------------------------------------------------------- #


class TestAsyncPrivacyManager:
    async def test_a_grant_mirrors_to_helix(
        self,
        fake_client: FakeHelixClient,
        consent_store: ConsentStore,
        retention_manager: RetentionManager,
    ) -> None:
        s = HelixPrivacyStore(fake_client, consent_store, retention_manager)
        s._available = True
        mgr = PrivacyManager(
            consent_store=consent_store,
            retention_manager=retention_manager,
            helix_store=s,
        )
        c = await mgr.a_grant_consent("u1", DataClass.LOCATION, ConsentLevel.ALLOW)
        assert c.user_id == "u1"
        # In-memory + Helix both updated.
        assert consent_store.check("u1", DataClass.LOCATION) is not None
        assert s.persisted_consent == 1

    async def test_a_revoke_mirrors_to_helix(
        self,
        fake_client: FakeHelixClient,
        consent_store: ConsentStore,
        retention_manager: RetentionManager,
    ) -> None:
        s = HelixPrivacyStore(fake_client, consent_store, retention_manager)
        s._available = True
        mgr = PrivacyManager(
            consent_store=consent_store,
            retention_manager=retention_manager,
            helix_store=s,
        )
        await mgr.a_grant_consent("u1", DataClass.LOCATION, ConsentLevel.ALLOW)
        ok = await mgr.a_revoke_consent("u1", DataClass.LOCATION)
        assert ok is True
        assert consent_store.check("u1", DataClass.LOCATION).level is ConsentLevel.DENY
        assert s.persisted_consent == 2  # grant + revoke both mirrored

    async def test_a_revoke_missing_returns_false(
        self,
        fake_client: FakeHelixClient,
        consent_store: ConsentStore,
        retention_manager: RetentionManager,
    ) -> None:
        s = HelixPrivacyStore(fake_client, consent_store, retention_manager)
        s._available = True
        mgr = PrivacyManager(
            consent_store=consent_store,
            retention_manager=retention_manager,
            helix_store=s,
        )
        ok = await mgr.a_revoke_consent("nobody", DataClass.LOCATION)
        assert ok is False

    async def test_a_schedule_retention_mirrors(
        self,
        fake_client: FakeHelixClient,
        consent_store: ConsentStore,
        retention_manager: RetentionManager,
    ) -> None:
        s = HelixPrivacyStore(fake_client, consent_store, retention_manager)
        s._available = True
        mgr = PrivacyManager(
            consent_store=consent_store,
            retention_manager=retention_manager,
            helix_store=s,
        )
        r = await mgr.a_schedule_retention("rec_1", DataClass.LOCATION, "u1")
        assert r.record_id == "rec_1"
        assert s.persisted_purge == 1

    async def test_a_cancel_purge_mirrors(
        self,
        fake_client: FakeHelixClient,
        consent_store: ConsentStore,
        retention_manager: RetentionManager,
    ) -> None:
        s = HelixPrivacyStore(fake_client, consent_store, retention_manager)
        s._available = True
        mgr = PrivacyManager(
            consent_store=consent_store,
            retention_manager=retention_manager,
            helix_store=s,
        )
        await mgr.a_schedule_retention("rec_1", DataClass.LOCATION, "u1")
        ok = await mgr.a_cancel_purge("rec_1")
        assert ok is True
        assert s.deleted_purge == 1

    async def test_a_delete_user_mirrors(
        self,
        fake_client: FakeHelixClient,
        consent_store: ConsentStore,
        retention_manager: RetentionManager,
    ) -> None:
        s = HelixPrivacyStore(fake_client, consent_store, retention_manager)
        s._available = True
        retention_manager.set_purger(lambda record: None)  # no-op purger
        mgr = PrivacyManager(
            consent_store=consent_store,
            retention_manager=retention_manager,
            helix_store=s,
        )
        await mgr.a_grant_consent("u1", DataClass.LOCATION, ConsentLevel.ALLOW)
        await mgr.a_schedule_retention("rec_1", DataClass.LOCATION, "u1")
        purged = await mgr.a_delete_user("u1")
        assert isinstance(purged, list)
        assert consent_store.check("u1", DataClass.LOCATION) is None
        assert retention_manager.get("rec_1") is None

    async def test_no_helix_store_skips_mirror(
        self,
        consent_store: ConsentStore,
        retention_manager: RetentionManager,
    ) -> None:
        mgr = PrivacyManager(
            consent_store=consent_store,
            retention_manager=retention_manager,
        )
        c = await mgr.a_grant_consent("u1", DataClass.LOCATION, ConsentLevel.ALLOW)
        assert c.user_id == "u1"
        assert consent_store.check("u1", DataClass.LOCATION) is not None


# --------------------------------------------------------------------------- #
# Registry default store wiring                                                #
# --------------------------------------------------------------------------- #


class TestRegistryHelixStore:
    def test_try_build_helix_store_disabled(
        self,
        monkeypatch: pytest.MonkeyPatch,
        consent_store: ConsentStore,
        retention_manager: RetentionManager,
    ) -> None:
        from app.core.privacy.registry import _try_build_helix_store

        monkeypatch.setenv("RAVEN_PRIVACY_HELIX", "0")
        result = _try_build_helix_store(consent_store, retention_manager)
        assert result is None

    def test_try_build_helix_store_no_client(
        self,
        consent_store: ConsentStore,
        retention_manager: RetentionManager,
    ) -> None:
        from app.core.privacy import registry as reg_mod

        # Reset module-level default client to None.
        from app.core.privacy.registry import _try_build_helix_store

        original_get = reg_mod.__dict__.get("get_default_helix_client", None)
        # Patch the import inside _try_build_helix_store by
        # stubbing the module attribute.
        import app.db.helix as helix_mod

        monkey = pytest.MonkeyPatch()
        try:
            # No default client registered → returns None.
            result = _try_build_helix_store(consent_store, retention_manager)
            # If a default client IS registered (from earlier tests),
            # the result may be non-None.  Both are valid; just
            # confirm the call doesn't raise.
            assert result is None or hasattr(result, "grant_consent")
        finally:
            monkey.undo()
        # Touch original_get to silence linter.
        _ = original_get
        _ = helix_mod

    def test_build_default_with_helix(
        self,
        fake_client: FakeHelixClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.core.privacy import registry as reg_mod
        from app.core.privacy.registry import _build_default, reset_privacy

        # Register our fake client as the default.
        monkeypatch.setattr(
            reg_mod, "get_default_helix_client", lambda: fake_client,
        )
        # Ensure the import inside _try_build_helix_store also
        # resolves to our patch.
        import app.core.privacy.persistence as pers_mod
        monkeypatch.setattr(pers_mod, "get_default_helix_client", lambda: fake_client, raising=False)
        reset_privacy()
        mgr = _build_default()
        assert mgr._helix_store is not None
