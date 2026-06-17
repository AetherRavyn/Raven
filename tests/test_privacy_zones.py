"""Tests for app.core.privacy.zones (Day 28)."""

from __future__ import annotations

import pytest

from app.core.privacy.consent import DataClass
from app.core.privacy.zones import (
    Zone,
    ZoneManager,
    ZonePolicy,
    ZoneRegistry,
    get_default_zone_manager,
    reset_default_zone_manager,
    set_default_zone_manager,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    reset_default_zone_manager()
    yield
    reset_default_zone_manager()


@pytest.fixture
def zm() -> ZoneManager:
    return ZoneManager()


# --------------------------------------------------------------------------- #
# ZonePolicy                                                                  #
# --------------------------------------------------------------------------- #


class TestZonePolicy:
    def test_creation(self) -> None:
        p = ZonePolicy(data_class=DataClass.LOCATION)
        assert p.zone is Zone.LOCAL_ONLY
        assert p.encryption_required is True
        assert p.retention_days == 90

    def test_creation_with_string(self) -> None:
        p = ZonePolicy(data_class="location", zone="local_only")
        assert p.data_class is DataClass.LOCATION
        assert p.zone is Zone.LOCAL_ONLY

    def test_allows_local(self) -> None:
        p = ZonePolicy(data_class=DataClass.LOCATION, zone=Zone.LOCAL_ONLY)
        assert p.allows_local() is True
        p2 = ZonePolicy(data_class=DataClass.LOCATION, zone=Zone.CLOUD_SYNC)
        assert p2.allows_local() is False

    def test_allows_cloud(self) -> None:
        p = ZonePolicy(data_class=DataClass.EMAIL, zone=Zone.CLOUD_SYNC)
        assert p.allows_cloud() is True
        p2 = ZonePolicy(data_class=DataClass.EMAIL, zone=Zone.LOCAL_ONLY)
        assert p2.allows_cloud() is False

    def test_invalid_zone_raises(self) -> None:
        with pytest.raises(ValueError):
            ZonePolicy(data_class=DataClass.LOCATION, zone="nowhere")


# --------------------------------------------------------------------------- #
# ZoneRegistry                                                                #
# --------------------------------------------------------------------------- #


class TestZoneRegistry:
    def test_default_has_all_data_classes(self) -> None:
        reg = ZoneRegistry()
        for dc in DataClass:
            assert reg.get(dc) is not None

    def test_get_unknown_returns_safe_default(self) -> None:
        reg = ZoneRegistry()
        # Patch out defaults to force fallback.
        reg._policies.clear()  # noqa: SLF001
        p = reg.get(DataClass.LOCATION)
        assert p.zone is Zone.LOCAL_ONLY
        assert p.encryption_required is True
        assert p.retention_days == 90

    def test_set_overrides(self) -> None:
        reg = ZoneRegistry()
        custom = ZonePolicy(
            data_class=DataClass.LOCATION,
            zone=Zone.BOTH,
            retention_days=7,
        )
        reg.set(custom)
        assert reg.get(DataClass.LOCATION) is custom

    def test_all_returns_list(self) -> None:
        reg = ZoneRegistry()
        assert len(reg.all()) == len(list(DataClass))

    def test_reset_restores_defaults(self) -> None:
        reg = ZoneRegistry()
        reg.set(ZonePolicy(data_class=DataClass.LOCATION, zone=Zone.BOTH))
        reg.reset()
        assert reg.get(DataClass.LOCATION).zone is Zone.LOCAL_ONLY

    def test_custom_defaults(self) -> None:
        custom = {
            DataClass.LOCATION: ZonePolicy(
                data_class=DataClass.LOCATION,
                zone=Zone.BOTH,
            )
        }
        reg = ZoneRegistry(defaults=custom)
        assert reg.get(DataClass.LOCATION).zone is Zone.BOTH


# --------------------------------------------------------------------------- #
# ZoneManager                                                                 #
# --------------------------------------------------------------------------- #


class TestZoneManager:
    def test_get_policy(self, zm: ZoneManager) -> None:
        p = zm.get_policy(DataClass.LOCATION)
        assert p.zone is Zone.LOCAL_ONLY

    def test_set_policy(self, zm: ZoneManager) -> None:
        p = ZonePolicy(data_class=DataClass.EMAIL, zone=Zone.BOTH, retention_days=14)
        zm.set_policy(p)
        assert zm.get_policy(DataClass.EMAIL).retention_days == 14

    def test_is_allowed_local(self, zm: ZoneManager) -> None:
        assert zm.is_allowed(DataClass.LOCATION, Zone.LOCAL_ONLY) is True
        assert zm.is_allowed(DataClass.LOCATION, Zone.CLOUD_SYNC) is False

    def test_is_allowed_cloud(self, zm: ZoneManager) -> None:
        assert zm.is_allowed(DataClass.EMAIL, Zone.CLOUD_SYNC) is True
        assert zm.is_allowed(DataClass.EMAIL, Zone.LOCAL_ONLY) is False

    def test_is_allowed_with_string_zone(self, zm: ZoneManager) -> None:
        assert zm.is_allowed(DataClass.EMAIL, "cloud_sync") is True

    def test_requires_encryption(self, zm: ZoneManager) -> None:
        assert zm.requires_encryption(DataClass.HEALTH) is True

    def test_retention_days(self, zm: ZoneManager) -> None:
        assert zm.retention_days(DataClass.HEALTH) == 1825

    def test_all_policies(self, zm: ZoneManager) -> None:
        assert len(zm.all_policies()) == len(list(DataClass))

    def test_reset(self, zm: ZoneManager) -> None:
        zm.set_policy(ZonePolicy(data_class=DataClass.EMAIL, zone=Zone.LOCAL_ONLY))
        zm.reset()
        assert zm.get_policy(DataClass.EMAIL).zone is Zone.CLOUD_SYNC


# --------------------------------------------------------------------------- #
# Singleton                                                                   #
# --------------------------------------------------------------------------- #


class TestSingleton:
    def test_get_default(self) -> None:
        m1 = get_default_zone_manager()
        m2 = get_default_zone_manager()
        assert m1 is m2

    def test_set_replaces(self) -> None:
        custom = ZoneManager()
        set_default_zone_manager(custom)
        try:
            assert get_default_zone_manager() is custom
        finally:
            set_default_zone_manager(None)
        assert get_default_zone_manager() is not custom

    def test_reset_clears(self) -> None:
        get_default_zone_manager()
        reset_default_zone_manager()
        m1 = get_default_zone_manager()
        assert len(m1.all_policies()) == len(list(DataClass))
