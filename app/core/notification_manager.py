"""Persistent Notifications — fallback delivery when user is offline.

When the primary messaging channel (botsignal) fails to deliver a
notification (user offline, channel down), this system:
1. Stores the notification persistently in SQLite
2. Retries via email as a fallback
3. Retries via botsignal periodically until delivered
4. Tracks delivery status for audit
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time as _time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Notification:
    notification_id: str
    user_id: str
    channel: str
    title: str
    body: str
    priority: str = "normal"  # low, normal, high, critical
    created_at: float = 0.0
    delivered: bool = False
    delivery_method: str = ""  # botsignal, email, stored
    attempts: int = 0
    metadata: dict[str, Any] | None = None


class PersistentNotificationManager:
    """Stores notifications in SQLite and retries delivery."""

    def __init__(self, workspace_dir: str = "workspace") -> None:
        from app.settings.config import Config
        self._dir = Path(workspace_dir or Config.MEMORY_ROOT) / "notifications"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._dir / "notifications.db"
        self._init_db()

    def _init_db(self) -> None:
        self._db = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                priority TEXT DEFAULT 'normal',
                created_at REAL NOT NULL,
                delivered INTEGER DEFAULT 0,
                delivery_method TEXT DEFAULT '',
                attempts INTEGER DEFAULT 0,
                metadata TEXT DEFAULT '{}'
            )
        """)
        self._db.commit()

    def store(
        self,
        user_id: str,
        channel: str,
        title: str,
        body: str,
        priority: str = "normal",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Store a notification for delivery."""
        import uuid
        nid = f"notif_{uuid.uuid4().hex[:12]}"
        self._db.execute(
            "INSERT INTO notifications (id, user_id, channel, title, body, priority, created_at, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (nid, user_id, channel, title, body, priority, _time.time(), json.dumps(metadata or {})),
        )
        self._db.commit()
        return nid

    def mark_delivered(self, notification_id: str, method: str = "botsignal") -> None:
        self._db.execute(
            "UPDATE notifications SET delivered = 1, delivery_method = ?, attempts = attempts + 1 WHERE id = ?",
            (method, notification_id),
        )
        self._db.commit()

    def increment_attempt(self, notification_id: str) -> None:
        self._db.execute(
            "UPDATE notifications SET attempts = attempts + 1 WHERE id = ?",
            (notification_id,),
        )
        self._db.commit()

    def get_undelivered(self, limit: int = 20) -> list[Notification]:
        """Get notifications that haven't been delivered yet."""
        rows = self._db.execute(
            "SELECT id, user_id, channel, title, body, priority, created_at, delivered, delivery_method, attempts, metadata FROM notifications WHERE delivered = 0 ORDER BY created_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            Notification(
                notification_id=r[0], user_id=r[1], channel=r[2],
                title=r[3], body=r[4], priority=r[5], created_at=r[6],
                delivered=bool(r[7]), delivery_method=r[8], attempts=r[9],
                metadata=json.loads(r[10]) if r[10] else None,
            )
            for r in rows
        ]

    def retry_delivery(self) -> int:
        """Attempt to deliver pending notifications. Returns count of deliveries attempted."""
        pending = self.get_undelivered()
        delivered = 0

        for notif in pending:
            if notif.attempts >= 5:
                # Mark as permanently failed
                self.mark_delivered(notif.notification_id, "failed")
                continue

            # Try botsignal first
            try:
                from app.core.botsignal import get_botsignal
                signal = get_botsignal()
                if signal:
                    from app.core.models import SignalPayload
                    import asyncio
                    payload = SignalPayload(text=f"**{notif.title}**\n{notif.body}")
                    target = type("Target", (), {"platform": notif.channel, "chat_id": notif.user_id})()
                    if asyncio.get_event_loop().is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as pool:
                            pool.submit(asyncio.run, signal.send_text(target, notif.body)).result(timeout=10)
                    else:
                        asyncio.run(signal.send_text(target, notif.body))
                    self.mark_delivered(notif.notification_id, "botsignal")
                    delivered += 1
                    continue
            except Exception:
                pass

            # Fallback: try email
            try:
                from app.tools.mail import MailTool
                mail = MailTool()
                import asyncio
                result = asyncio.run(mail.execute(
                    operation="send",
                    to=notif.metadata.get("email", "") if notif.metadata else "",
                    subject=notif.title,
                    body=notif.body,
                ))
                if result.get("success"):
                    self.mark_delivered(notif.notification_id, "email")
                    delivered += 1
                    continue
            except Exception:
                pass

            # If both fail, increment attempt counter for later retry
            self.increment_attempt(notif.notification_id)

        return delivered

    def get_pending_count(self, user_id: str | None = None) -> int:
        if user_id:
            row = self._db.execute("SELECT COUNT(*) FROM notifications WHERE delivered = 0 AND user_id = ?", (user_id,)).fetchone()
        else:
            row = self._db.execute("SELECT COUNT(*) FROM notifications WHERE delivered = 0").fetchone()
        return row[0] if row else 0


# Singleton
_manager: PersistentNotificationManager | None = None


def get_notification_manager() -> PersistentNotificationManager:
    global _manager
    if _manager is None:
        _manager = PersistentNotificationManager()
    return _manager
