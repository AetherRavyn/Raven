"""Identity primitives for cross-platform continuity.

A user has one or more devices.  Each device has one or more
channels (a Telegram chat on a phone is a channel; the same
phone's web UI is a different channel).

The identity layer answers two questions:
  * "given a (platform, chat_id) tuple, who is the user?"
  * "given a user, what devices / channels do they have?"

Storage is pluggable.  The default is in-memory (good for
tests); a HelixDB-backed implementation lives in
``store.py``.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# dataclasses
# -------------------------------------------------------------------


@dataclass(slots=True)
class Channel:
    """A transport handle: a (platform, chat_id) pair bound to a device."""

    platform: str
    chat_id: str
    device_id: str
    last_active_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Free-form metadata: locale, timezone, capabilities.
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.platform}:{self.chat_id}"


@dataclass(slots=True)
class Device:
    """A physical endpoint (phone, laptop, voice assistant)."""

    id: str
    user_id: str
    kind: str  # "phone", "laptop", "voice", "watch", "tablet"
    name: str = ""
    last_seen_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class UserIdentity:
    """A user is the abstract owner of devices and sessions."""

    id: str
    display_name: str = ""
    # Free-form flags: "owner", "trusted", "guest", ...
    roles: tuple[str, ...] = field(default_factory=tuple)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


# -------------------------------------------------------------------
# deterministic id helpers
# -------------------------------------------------------------------


def derive_user_id(platform: str, chat_id: str) -> str:
    """Map a (platform, chat_id) tuple to a stable user id.

    Same algorithm the existing DM-pairing code uses, exposed
    here so the rest of the continuity package can build
    identities without importing the dm_pairing module.
    """
    blob = f"{platform.strip().lower()}:{chat_id.strip()}".encode("utf-8")
    return "u_" + hashlib.sha256(blob).hexdigest()[:16]


def derive_device_id(user_id: str, kind: str) -> str:
    blob = f"{user_id}:{kind.strip().lower()}".encode("utf-8")
    return "d_" + hashlib.sha256(blob).hexdigest()[:16]


# -------------------------------------------------------------------
# in-memory identity registry
# -------------------------------------------------------------------


class IdentityRegistry:
    """Thread-safe identity registry backed by SQLite for users.

    Devices and channels stay in-memory (ephemeral).
    User resolution delegates to UserIdentityStore (SQLite).
    """

    def __init__(self, user_store: Any | None = None) -> None:
        from app.core.user_identity import UserIdentityStore

        self._lock = threading.RLock()
        self._user_store = user_store or UserIdentityStore()
        self._users: dict[str, UserIdentity] = {}  # in-memory cache for upserted users
        self._devices: dict[str, Device] = {}
        self._channels: dict[str, Channel] = {}

    # ---- users (SQLite-backed with in-memory cache) ----

    def upsert_user(self, user: UserIdentity) -> UserIdentity:
        with self._lock:
            self._users[user.id] = user
        # Also register in SQLite store for cross-system resolution
        self._user_store.resolve("internal", user.id)
        return user

    def get_user(self, user_id: str) -> UserIdentity | None:
        with self._lock:
            return self._users.get(user_id)

    def list_users(self) -> list[UserIdentity]:
        with self._lock:
            return list(self._users.values())

    # ---- devices ----

    def upsert_device(self, device: Device) -> Device:
        with self._lock:
            device.last_seen_at = datetime.now(timezone.utc)
            self._devices[device.id] = device
            return device

    def get_device(self, device_id: str) -> Device | None:
        with self._lock:
            return self._devices.get(device_id)

    def list_devices(self, user_id: str) -> list[Device]:
        with self._lock:
            return [d for d in self._devices.values() if d.user_id == user_id]

    # ---- channels ----

    def upsert_channel(self, channel: Channel) -> Channel:
        with self._lock:
            channel.last_active_at = datetime.now(timezone.utc)
            self._channels[channel.id] = channel
            return channel

    def get_channel(self, channel_id: str) -> Channel | None:
        with self._lock:
            return self._channels.get(channel_id)

    def find_channel(self, platform: str, chat_id: str) -> Channel | None:
        cid = f"{platform}:{chat_id}"
        with self._lock:
            return self._channels.get(cid)

    def list_channels(self, device_id: str | None = None) -> list[Channel]:
        with self._lock:
            if device_id is None:
                return list(self._channels.values())
            return [c for c in self._channels.values() if c.device_id == device_id]

    # ---- binding ----

    def bind(
        self,
        platform: str,
        chat_id: str,
        user_id: str,
        device_kind: str = "phone",
        *,
        device_name: str = "",
        capabilities: Iterable[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> tuple[UserIdentity, Device, Channel]:
        """End-to-end: ensure user + device + channel exist for the given handle.

        User resolution is persisted to SQLite via UserIdentityStore.
        Devices and channels stay in-memory.
        """
        # Register in SQLite store for cross-system resolution
        self._user_store.resolve(platform, chat_id)

        channel_meta = metadata or {}
        with self._lock:
            user = self._users.get(user_id)
            if user is None:
                user = UserIdentity(id=user_id)
                self._users[user_id] = user

            device_id = derive_device_id(user_id, device_kind)
            device = self._devices.get(device_id)
            if device is None:
                device = Device(
                    id=device_id,
                    user_id=user_id,
                    kind=device_kind,
                    name=device_name or f"{user_id}-{device_kind}",
                    capabilities=tuple(capabilities),
                    metadata=dict(channel_meta.get("device_meta", {})),
                )
                self._devices[device_id] = device
            else:
                device.last_seen_at = datetime.now(timezone.utc)

            channel = Channel(
                platform=platform,
                chat_id=chat_id,
                device_id=device_id,
                metadata={k: v for k, v in channel_meta.items() if k != "device_meta"},
            )
            self._channels[channel.id] = channel
            return user, device, channel

    def clear(self) -> None:
        with self._lock:
            self._users.clear()
            self._devices.clear()
            self._channels.clear()
