# app/core/user_identity.py
"""Unified User Identity Resolution for cross-platform session continuity.

Maps platform-specific user IDs to a single canonical RAVEN user, enabling:
  - Start a conversation on Telegram, continue on Discord
  - Voice user automatically linked to Telegram profile
  - Single memory/profile store per real person

Storage: SQLite at workspace/memory/identity.sqlite
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class UserIdentityStore:
    """Maps platform-specific IDs to canonical RAVEN user IDs."""

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config

        base = Path(workspace_dir) if workspace_dir else Path(Config.MEMORY_ROOT)
        base.mkdir(parents=True, exist_ok=True)
        self._db_path = str(base / "identity.sqlite")
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_links (
                    platform TEXT NOT NULL,
                    platform_user_id TEXT NOT NULL,
                    canonical_id TEXT NOT NULL,
                    display_name TEXT DEFAULT '',
                    linked_at TEXT NOT NULL,
                    PRIMARY KEY (platform, platform_user_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS canonical_users (
                    canonical_id TEXT PRIMARY KEY,
                    primary_name TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_canonical ON user_links(canonical_id)
            """)
            conn.commit()

    # ── Resolution ─────────────────────────────────────────────────────

    def resolve(self, platform: str, platform_user_id: str) -> str:
        """
        Resolve a platform-specific ID to a canonical RAVEN user ID.
        Auto-creates a new canonical user if none exists.
        """
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT canonical_id FROM user_links WHERE platform = ? AND platform_user_id = ?",
                (platform.lower(), str(platform_user_id)),
            ).fetchone()

            if row:
                canonical_id = row[0]
                # Update last seen
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "UPDATE canonical_users SET last_seen_at = ? WHERE canonical_id = ?",
                    (now, canonical_id),
                )
                conn.commit()
                return canonical_id

            # Auto-create: new canonical user
            canonical_id = f"u_{uuid.uuid4().hex[:8]}"
            now = datetime.now(timezone.utc).isoformat()

            conn.execute(
                "INSERT INTO canonical_users (canonical_id, primary_name, created_at, last_seen_at) VALUES (?, ?, ?, ?)",
                (canonical_id, "", now, now),
            )
            conn.execute(
                "INSERT INTO user_links (platform, platform_user_id, canonical_id, display_name, linked_at) VALUES (?, ?, ?, ?, ?)",
                (platform.lower(), str(platform_user_id), canonical_id, "", now),
            )
            conn.commit()
            logger.info(
                "UserIdentity: created new canonical user %s for %s:%s",
                canonical_id,
                platform,
                platform_user_id,
            )
            return canonical_id

    # ── Linking ────────────────────────────────────────────────────────

    def link_accounts(
        self,
        platform_a: str,
        user_id_a: str,
        platform_b: str,
        user_id_b: str,
    ) -> str:
        """
        Link two platform accounts to the same canonical user.
        The canonical ID of the first account is used.
        Returns the shared canonical ID.
        """
        canonical_id = self.resolve(platform_a, user_id_a)
        now = datetime.now(timezone.utc).isoformat()

        with sqlite3.connect(self._db_path) as conn:
            # Check if B already has a different canonical ID
            row = conn.execute(
                "SELECT canonical_id FROM user_links WHERE platform = ? AND platform_user_id = ?",
                (platform_b.lower(), str(user_id_b)),
            ).fetchone()

            if row and row[0] != canonical_id:
                # Merge: update all of B's old canonical ID references to A's
                old_id = row[0]
                conn.execute(
                    "UPDATE user_links SET canonical_id = ? WHERE canonical_id = ?",
                    (canonical_id, old_id),
                )
                conn.execute(
                    "DELETE FROM canonical_users WHERE canonical_id = ?",
                    (old_id,),
                )
                logger.info(
                    "UserIdentity: merged canonical user %s into %s",
                    old_id,
                    canonical_id,
                )
            elif not row:
                conn.execute(
                    "INSERT INTO user_links (platform, platform_user_id, canonical_id, display_name, linked_at) VALUES (?, ?, ?, ?, ?)",
                    (platform_b.lower(), str(user_id_b), canonical_id, "", now),
                )

            conn.commit()

        logger.info(
            "UserIdentity: linked %s:%s ↔ %s:%s as %s",
            platform_a,
            user_id_a,
            platform_b,
            user_id_b,
            canonical_id,
        )
        return canonical_id

    # ── Query ──────────────────────────────────────────────────────────

    def get_all_links(self, canonical_id: str) -> List[Dict[str, str]]:
        """Get all platform accounts linked to a canonical user."""
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT platform, platform_user_id, display_name, linked_at FROM user_links WHERE canonical_id = ?",
                (canonical_id,),
            ).fetchall()
        return [
            {
                "platform": r[0],
                "platform_user_id": r[1],
                "display_name": r[2],
                "linked_at": r[3],
            }
            for r in rows
        ]

    def set_display_name(self, canonical_id: str, name: str) -> None:
        """Set the primary display name for a canonical user."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "UPDATE canonical_users SET primary_name = ? WHERE canonical_id = ?",
                (name, canonical_id),
            )
            conn.commit()

    def get_display_name(self, canonical_id: str) -> str:
        """Get the primary display name for a canonical user."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT primary_name FROM canonical_users WHERE canonical_id = ?",
                (canonical_id,),
            ).fetchone()
        return row[0] if row else ""


# ── Module singleton ───────────────────────────────────────────────────

_STORE: UserIdentityStore | None = None


def get_identity_store() -> UserIdentityStore:
    global _STORE
    if _STORE is None:
        _STORE = UserIdentityStore()
    return _STORE
