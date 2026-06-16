"""HelixDB-backed persistence for continuity.

The in-memory ``SessionManager`` and ``IdentityRegistry`` are
the source of truth at runtime.  This module snapshots them
to HelixDB on a periodic / explicit basis so the workspace
survives a restart.

The on-disk schema is intentionally simple:

  * ``ContinuitySession`` node  — id, user_id, channel_id,
    started_at, last_active_at, ended_at, target_channel_id,
    tags (string JSON), context (string JSON), events (string
    JSON)
  * ``ContinuityUser``    — id, display_name, roles, metadata
  * ``ContinuityDevice``  — id, user_id, kind, name, capabilities
  * ``ContinuityChannel`` — id (platform:chat_id), user_id,
    device_id, platform, chat_id, metadata

Reads and writes are best-effort: if HelixDB is unavailable,
we log and continue with the in-memory state.  This keeps the
runtime alive when the DB is being restarted.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any

from app.core.continuity.identity import (
    Channel,
    Device,
    IdentityRegistry,
    UserIdentity,
)
from app.core.continuity.session import Session, SessionEvent, SessionManager

logger = logging.getLogger(__name__)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _from_iso(s: str | None) -> datetime | None:
    if s is None:
        return None
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def _session_from_props(props: dict[str, Any]) -> Session:
    sess = Session(
        id=props.get("id") or props.get("ID", ""),
        user_id=props.get("user_id", ""),
        channel_id=props.get("channel_id", ""),
        started_at=_from_iso(props.get("started_at")) or datetime.now(timezone.utc),
        last_active_at=_from_iso(props.get("last_active_at")) or datetime.now(timezone.utc),
        ended_at=_from_iso(props.get("ended_at")),
        target_channel_id=props.get("target_channel_id", ""),
        tags=tuple(json.loads(props.get("tags", "[]"))),
        context=dict(json.loads(props.get("context", "{}"))),
    )
    sess.events = deque(maxlen=sess.events.maxlen)
    for ev in json.loads(props.get("events", "[]")):
        sess.events.append(
            SessionEvent(
                id=ev.get("id", ""),
                session_id=sess.id,
                role=ev.get("role", "user"),
                content=ev.get("content", ""),
                created_at=_from_iso(ev.get("created_at")) or datetime.now(timezone.utc),
                metadata=dict(ev.get("metadata", {})),
            )
        )
    return sess


class HelixContinuityStore:
    """Best-effort snapshot of identity + sessions to HelixDB.

    All methods are no-ops (with a warning) if the underlying
    Helix client is not available.
    """

    def __init__(self, helix: Any | None = None) -> None:
        self._helix = helix
        self._available = False
        self._probe()

    @property
    def available(self) -> bool:
        return self._available

    def _probe(self) -> None:
        if self._helix is None:
            try:
                from app.db.helix import get_helix  # type: ignore

                self._helix = get_helix()
            except Exception as exc:  # noqa: BLE001
                logger.info("helix unavailable for continuity store: %s", exc)
                self._helix = None
                return
        try:
            self._available = bool(self._helix.is_available())
        except Exception as exc:  # noqa: BLE001
            logger.info("helix probe failed: %s", exc)
            self._available = False

    # ---- users ----

    def save_user(self, user: UserIdentity) -> bool:
        if not self._available or self._helix is None:
            return False
        try:
            self._helix.execute(
                "AddN(ContinuityUser { id: String, display_name: String, "
                "roles: String, created_at: String, metadata: String })",
                {
                    "id": user.id,
                    "display_name": user.display_name,
                    "roles": json.dumps(list(user.roles)),
                    "created_at": _iso(user.created_at) or "",
                    "metadata": json.dumps(user.metadata),
                },
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.info("save_user(%s) failed: %s", user.id, exc)
            return False

    def list_users(self) -> list[UserIdentity]:
        if not self._available or self._helix is None:
            return []
        try:
            res = self._helix.execute(
                "N<ContinuityUser>::Where(_::Has(id))::{id, display_name, roles, created_at, metadata}",
                {},
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("list_users failed: %s", exc)
            return []
        out: list[UserIdentity] = []
        for row in res or []:
            props = row.get("properties") or row
            try:
                out.append(
                    UserIdentity(
                        id=props.get("id", ""),
                        display_name=props.get("display_name", ""),
                        roles=tuple(json.loads(props.get("roles", "[]"))),
                        created_at=_from_iso(props.get("created_at")) or datetime.now(timezone.utc),
                        metadata=dict(json.loads(props.get("metadata", "{}"))),
                    )
                )
            except Exception:  # noqa: BLE001
                continue
        return out

    # ---- devices ----

    def save_device(self, device: Device) -> bool:
        if not self._available or self._helix is None:
            return False
        try:
            self._helix.execute(
                "AddN(ContinuityDevice { id: String, user_id: String, kind: String, "
                "name: String, last_seen_at: String, capabilities: String, metadata: String })",
                {
                    "id": device.id,
                    "user_id": device.user_id,
                    "kind": device.kind,
                    "name": device.name,
                    "last_seen_at": _iso(device.last_seen_at) or "",
                    "capabilities": json.dumps(list(device.capabilities)),
                    "metadata": json.dumps(device.metadata),
                },
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.info("save_device(%s) failed: %s", device.id, exc)
            return False

    # ---- channels ----

    def save_channel(self, channel: Channel) -> bool:
        if not self._available or self._helix is None:
            return False
        try:
            self._helix.execute(
                "AddN(ContinuityChannel { id: String, user_id: String, device_id: String, "
                "platform: String, chat_id: String, last_active_at: String, metadata: String })",
                {
                    "id": channel.id,
                    "user_id": "",
                    "device_id": channel.device_id,
                    "platform": channel.platform,
                    "chat_id": channel.chat_id,
                    "last_active_at": _iso(channel.last_active_at) or "",
                    "metadata": json.dumps(channel.metadata),
                },
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.info("save_channel(%s) failed: %s", channel.id, exc)
            return False

    # ---- sessions ----

    def save_session(self, session: Session) -> bool:
        if not self._available or self._helix is None:
            return False
        try:
            self._helix.execute(
                "AddN(ContinuitySession { id: String, user_id: String, channel_id: String, "
                "started_at: String, last_active_at: String, ended_at: String, "
                "target_channel_id: String, tags: String, context: String, "
                "events: String })",
                {
                    "id": session.id,
                    "user_id": session.user_id,
                    "channel_id": session.channel_id,
                    "started_at": _iso(session.started_at) or "",
                    "last_active_at": _iso(session.last_active_at) or "",
                    "ended_at": _iso(session.ended_at) or "",
                    "target_channel_id": session.target_channel_id,
                    "tags": json.dumps(list(session.tags)),
                    "context": json.dumps(dict(session.context)),
                    "events": json.dumps(
                        [
                            {
                                "id": e.id,
                                "role": e.role,
                                "content": e.content,
                                "created_at": _iso(e.created_at) or "",
                                "metadata": dict(e.metadata),
                            }
                            for e in session.events
                        ]
                    ),
                },
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.info("save_session(%s) failed: %s", session.id, exc)
            return False

    def list_sessions(self, user_id: str) -> list[Session]:
        if not self._available or self._helix is None:
            return []
        try:
            res = self._helix.execute(
                "N<ContinuitySession>::Where(_::Has(user_id))::{id, channel_id, "
                "started_at, last_active_at, ended_at, target_channel_id, "
                "tags, context, events}",
                {"user_id": user_id},
            )
        except Exception as exc:  # noqa: BLE001
            logger.info("list_sessions(%s) failed: %s", user_id, exc)
            return []
        out: list[Session] = []
        for row in res or []:
            props = row.get("properties") or row
            try:
                out.append(_session_from_props(dict(props)))
            except Exception:  # noqa: BLE001
                continue
        return out


# -------------------------------------------------------------------
# snapshot helpers
# -------------------------------------------------------------------


def snapshot(
    registry: IdentityRegistry,
    sessions: SessionManager,
    store: HelixContinuityStore | None = None,
) -> int:
    """Persist the in-memory state to Helix (best-effort).

    Returns the number of writes that succeeded.  Zero
    indicates Helix was unavailable.
    """
    if store is None:
        store = HelixContinuityStore()
    if not store.available:
        return 0
    written = 0
    for user in registry.list_users():
        if store.save_user(user):
            written += 1
    seen_devices: set[str] = set()
    for user in registry.list_users():
        for device in registry.list_devices(user.id):
            if device.id in seen_devices:
                continue
            seen_devices.add(device.id)
            if store.save_device(device):
                written += 1
    for user in registry.list_users():
        for sess in sessions.list_sessions(user.id, include_ended=True):
            if store.save_session(sess):
                written += 1
    return written


def load_sessions(
    store: HelixContinuityStore,
    user_id: str,
    manager: SessionManager,
) -> list[Session]:
    """Read previously persisted sessions into the in-memory manager.

    Returns the list of loaded sessions.  New ids are
    generated for re-hydration so the in-memory store doesn't
    collide with future persisted writes — callers can use
    the session context / events but should treat the id as
    ephemeral.
    """
    loaded = store.list_sessions(user_id)
    out: list[Session] = []
    for sess in loaded:
        if sess is None:
            continue
        new_sess, _ = manager.get_or_create(user_id, sess.channel_id)
        new_sess.context.update(sess.context)
        new_sess.target_channel_id = sess.target_channel_id
        for ev in sess.events:
            new_sess.append_event(ev)
        out.append(new_sess)
    return out
