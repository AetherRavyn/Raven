"""Subscription management and rate-limiting proxy.

Handles tier-based access control, token consumption tracking,
and per-user rate limiting with SQLite persistence.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Token estimation ────────────────────────────────────────────────────────

_CHARS_PER_TOKEN = 4.0

BASE_COST_LLM_CALL = "input_tokens + output_tokens"
BASE_COST_TOOL_CALL = 50
BASE_COST_FILE_OP = 10
BASE_COST_SEARCH = 5
BASE_COST_VOICE = 100


def estimate_tokens(text: str) -> int:
    """Rough character-based token estimation (~4 chars per token)."""
    if not text:
        return 0
    return max(1, len(text) // int(_CHARS_PER_TOKEN))


def compute_action_cost(action: str, *, input_tokens: int = 0, output_tokens: int = 0, text: str = "") -> int:
    """Return the token cost for a given action type."""
    normalized = action.strip().lower()
    if normalized == "llm_call":
        return max(1, input_tokens + output_tokens)
    if normalized == "tool_call":
        return BASE_COST_TOOL_CALL
    if normalized == "file_operation":
        return BASE_COST_FILE_OP
    if normalized == "search":
        return BASE_COST_SEARCH
    if normalized == "voice":
        return BASE_COST_VOICE
    return estimate_tokens(text) if text else 1


# ── Enums & Dataclasses ─────────────────────────────────────────────────────

class SubscriptionTier(str, Enum):
    """Available subscription tiers with their resource limits."""

    BASIC = "basic"
    PRO = "pro"
    ENTERPRISE = "enterprise"
    BETA = "beta"

    @property
    def monthly_tokens(self) -> int:
        return _TIER_LIMITS[self]["monthly_tokens"]

    @property
    def max_agents(self) -> int:
        return _TIER_LIMITS[self]["max_agents"]

    @property
    def max_tools(self) -> int:
        return _TIER_LIMITS[self]["max_tools"]

    @property
    def features(self) -> list[str]:
        return list(_TIER_LIMITS[self]["features"])


_TIER_LIMITS: dict[SubscriptionTier, dict[str, Any]] = {
    SubscriptionTier.BASIC: {
        "monthly_tokens": 100_000,
        "max_agents": 3,
        "max_tools": 10,
        "features": ["basic_voice", "basic_memory", "basic_automation"],
    },
    SubscriptionTier.PRO: {
        "monthly_tokens": 500_000,
        "max_agents": 10,
        "max_tools": 50,
        "features": [
            "advanced_voice",
            "unlimited_memory",
            "advanced_automation",
            "kanban",
            "blueprints",
            "lsp",
            "hooks",
        ],
    },
    SubscriptionTier.ENTERPRISE: {
        "monthly_tokens": 5_000_000,
        "max_agents": -1,  # unlimited
        "max_tools": -1,  # unlimited
        "features": ["all"],
    },
    SubscriptionTier.BETA: {
        "monthly_tokens": 50_000,
        "max_agents": 15,
        "max_tools": 100,
        "features": ["all"],
    },
}


@dataclass
class Subscription:
    """A user's subscription record."""

    user_id: str
    tier: SubscriptionTier
    tokens_used: int = 0
    started_at: str = ""
    expires_at: str | None = None
    active: bool = True
    features_override: list[str] | None = None

    @property
    def tokens_remaining(self) -> int:
        return max(0, self.tier.monthly_tokens - self.tokens_used)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "tier": self.tier.value,
            "tokens_used": self.tokens_used,
            "started_at": self.started_at,
            "expires_at": self.expires_at,
            "active": self.active,
            "features_override": json.dumps(self.features_override or []),
        }

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> Subscription:
        features_override_raw = row.get("features_override") or "[]"
        if isinstance(features_override_raw, str):
            parsed = json.loads(features_override_raw)
        elif isinstance(features_override_raw, (list, tuple)):
            parsed = list(features_override_raw)
        else:
            parsed = []
        return cls(
            user_id=row["user_id"],
            tier=SubscriptionTier(row["tier"]),
            tokens_used=row["tokens_used"],
            started_at=row["started_at"],
            expires_at=row.get("expires_at"),
            active=bool(row["active"]),
            features_override=parsed or None,
        )


@dataclass
class UsageRecord:
    """A single token consumption event."""

    id: str = ""
    user_id: str = ""
    action: str = ""
    tokens_consumed: int = 0
    timestamp: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RateLimitConfig:
    """Configuration for per-user rate limiting."""

    max_requests_per_minute: int = 60
    max_tokens_per_hour: int = 100_000
    burst_capacity: int = 10
    cooldown_seconds: int = 30


@dataclass
class RateLimitStatus:
    """Result of a rate limit check."""

    allowed: bool
    remaining: int
    reset_at: str = ""
    retry_after: int = 0


# ── SQLite Schema ───────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS subscriptions (
    user_id TEXT PRIMARY KEY,
    tier TEXT NOT NULL DEFAULT 'basic',
    tokens_used INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    expires_at TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    features_override TEXT
);

CREATE TABLE IF NOT EXISTS usage_records (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    tokens_consumed INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (user_id) REFERENCES subscriptions(user_id)
);

CREATE INDEX IF NOT EXISTS idx_usage_user ON usage_records(user_id);
CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage_records(timestamp);
"""

_DB_PATH = Path("workspace/memory/subscriptions.db")


# ── SubscriptionManager ─────────────────────────────────────────────────────

class SubscriptionManager:
    """Persistent subscription management backed by SQLite."""

    def __init__(self, db_path: str | Path = _DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    # ── connection management ───────────────────────────────────────────

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=5000")
        return self._local.conn

    def _init_db(self) -> None:
        """Create tables and indexes if they don't exist."""
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    # ── public API ──────────────────────────────────────────────────────

    def create_subscription(self, user_id: str, tier: str) -> Subscription:
        """Create a new subscription for a user."""
        normalized_tier = tier.strip().lower()
        tier_enum = SubscriptionTier(normalized_tier)
        now = datetime.now(timezone.utc).isoformat()
        sub = Subscription(
            user_id=user_id,
            tier=tier_enum,
            started_at=now,
        )
        self._conn.execute(
            """INSERT INTO subscriptions (user_id, tier, tokens_used, started_at, expires_at, active, features_override)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                sub.user_id,
                sub.tier.value,
                sub.tokens_used,
                sub.started_at,
                sub.expires_at,
                int(sub.active),
                json.dumps(sub.features_override or []),
            ),
        )
        self._conn.commit()
        logger.info("Created %s subscription for user=%s", tier, user_id)
        return sub

    def get_subscription(self, user_id: str) -> Subscription | None:
        """Retrieve a user's subscription, or None if not found."""
        row = self._conn.execute(
            "SELECT * FROM subscriptions WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            return None
        return Subscription.from_dict(dict(row))

    def update_tier(self, user_id: str, new_tier: str) -> bool:
        """Change a user's subscription tier. Returns True if updated."""
        normalized = new_tier.strip().lower()
        try:
            SubscriptionTier(normalized)
        except ValueError:
            logger.warning("Invalid tier '%s' for user=%s", new_tier, user_id)
            return False
        cur = self._conn.execute(
            "UPDATE subscriptions SET tier = ? WHERE user_id = ?",
            (normalized, user_id),
        )
        self._conn.commit()
        updated = cur.rowcount > 0
        if updated:
            logger.info("Updated tier to %s for user=%s", new_tier, user_id)
        return updated

    def cancel_subscription(self, user_id: str) -> bool:
        """Deactivate a user's subscription. Returns True if cancelled."""
        cur = self._conn.execute(
            "UPDATE subscriptions SET active = 0 WHERE user_id = ? AND active = 1",
            (user_id,),
        )
        self._conn.commit()
        cancelled = cur.rowcount > 0
        if cancelled:
            logger.info("Cancelled subscription for user=%s", user_id)
        return cancelled

    def list_active_subscriptions(self) -> list[Subscription]:
        """Return all active subscriptions."""
        rows = self._conn.execute(
            "SELECT * FROM subscriptions WHERE active = 1"
        ).fetchall()
        return [Subscription.from_dict(dict(r)) for r in rows]

    def check_feature_access(self, user_id: str, feature: str) -> bool:
        """Check if a user has access to a specific feature."""
        sub = self.get_subscription(user_id)
        if sub is None or not sub.active:
            return False
        if sub.features_override:
            return feature in sub.features_override
        if "all" in sub.tier.features:
            return True
        return feature in sub.tier.features

    def consume_tokens(self, user_id: str, amount: int) -> tuple[bool, int]:
        """Deduct tokens from a user's allowance.

        Returns (success, tokens_remaining).
        """
        sub = self.get_subscription(user_id)
        if sub is None or not sub.active:
            return False, 0
        if sub.tokens_remaining < amount:
            return False, sub.tokens_remaining
        new_used = sub.tokens_used + amount
        self._conn.execute(
            "UPDATE subscriptions SET tokens_used = ? WHERE user_id = ?",
            (new_used, user_id),
        )
        self._conn.commit()
        remaining = max(0, sub.tier.monthly_tokens - new_used)
        return True, remaining

    def has_tokens(self, user_id: str, required: int) -> bool:
        """Check if a user has enough tokens remaining."""
        sub = self.get_subscription(user_id)
        if sub is None or not sub.active:
            return False
        return sub.tokens_remaining >= required

    def get_tier(self, tier_name: str) -> SubscriptionTier | None:
        """Resolve a tier name to a SubscriptionTier enum member."""
        try:
            return SubscriptionTier(tier_name.strip().lower())
        except ValueError:
            return None

    def list_tiers(self) -> list[SubscriptionTier]:
        """Return all available subscription tiers."""
        return list(SubscriptionTier)

    def record_usage(
        self,
        user_id: str,
        action: str,
        tokens_consumed: int,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Persist a usage record and return its ID."""
        record_id = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """INSERT INTO usage_records (id, user_id, action, tokens_consumed, timestamp, metadata)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (record_id, user_id, action, tokens_consumed, now, json.dumps(metadata or {})),
        )
        self._conn.commit()
        return record_id

    def get_usage_history(
        self,
        user_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[UsageRecord]:
        """Fetch recent usage records for a user."""
        rows = self._conn.execute(
            """SELECT * FROM usage_records WHERE user_id = ?
               ORDER BY timestamp DESC LIMIT ? OFFSET ?""",
            (user_id, limit, offset),
        ).fetchall()
        return [
            UsageRecord(
                id=r["id"],
                user_id=r["user_id"],
                action=r["action"],
                tokens_consumed=r["tokens_consumed"],
                timestamp=r["timestamp"],
                metadata=json.loads(r["metadata"]),
            )
            for r in rows
        ]


# ── RateLimiter ─────────────────────────────────────────────────────────────

class RateLimiter:
    """Per-user sliding-window rate limiter with SQLite persistence."""

    def __init__(self, config: RateLimitConfig | None = None) -> None:
        self._config = config or RateLimitConfig()
        self._local = threading.local()
        self._window_windows: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            db_path = Path("workspace/memory/rate_limits.db")
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._local.conn = sqlite3.connect(str(db_path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=5000")
            self._local.conn.execute(
                """CREATE TABLE IF NOT EXISTS rate_windows (
                    window_key TEXT PRIMARY KEY,
                    count INTEGER NOT NULL DEFAULT 0,
                    tokens INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                )"""
            )
            self._local.conn.commit()
        return self._local.conn

    def _get_window_key(self, user_id: str) -> str:
        """Minute-based window key for a user."""
        now_ts = int(time.time())
        window_start = now_ts - (now_ts % 60)
        return f"{user_id}:{window_start}"

    def _cleanup_expired(self) -> None:
        """Purge rate window rows older than 2 minutes."""
        try:
            cutoff = time.time() - 120
            self._conn.execute("DELETE FROM rate_windows WHERE created_at < ?", (cutoff,))
            self._conn.commit()
        except Exception:
            pass

    async def check_rate_limit(self, user_id: str) -> RateLimitStatus:
        """Check whether a user is currently rate-limited without consuming."""
        window_key = self._get_window_key(user_id)
        now = time.time()

        with self._lock:
            row = self._conn.execute(
                "SELECT count, tokens, created_at FROM rate_windows WHERE window_key = ?",
                (window_key,),
            ).fetchone()

            count = row["count"] if row else 0
            tokens = row["tokens"] if row else 0

            effective_limit = self._config.max_requests_per_minute + self._config.burst_capacity
            remaining_reqs = max(0, effective_limit - count)

            if count >= effective_limit:
                retry_after = self._config.cooldown_seconds
                reset_at = datetime.fromtimestamp(now + retry_after, tz=timezone.utc).isoformat()
                return RateLimitStatus(allowed=False, remaining=0, reset_at=reset_at, retry_after=retry_after)

            if tokens >= self._config.max_tokens_per_hour:
                retry_after = 3600 - (int(now) % 3600)
                reset_at = datetime.fromtimestamp(
                    (int(now) - (int(now) % 3600)) + 3600, tz=timezone.utc
                ).isoformat()
                return RateLimitStatus(allowed=False, remaining=0, reset_at=reset_at, retry_after=retry_after)

            return RateLimitStatus(allowed=True, remaining=remaining_reqs)

    async def consume(self, user_id: str, tokens: int = 1) -> RateLimitStatus:
        """Record a request attempt and return the resulting rate limit status.

        Returns RateLimitStatus with allowed=False if the request should be blocked.
        """
        window_key = self._get_window_key(user_id)
        now = time.time()

        with self._lock:
            self._conn.execute(
                """INSERT INTO rate_windows (window_key, count, tokens, created_at)
                   VALUES (?, 1, ?, ?)
                   ON CONFLICT(window_key) DO UPDATE SET
                       count = count + 1,
                       tokens = tokens + ?,
                       created_at = ?""",
                (window_key, tokens, now, tokens, now),
            )
            self._conn.commit()

            row = self._conn.execute(
                "SELECT count, tokens FROM rate_windows WHERE window_key = ?",
                (window_key,),
            ).fetchone()

            count = row["count"] if row else 0
            total_tokens = row["tokens"] if row else 0

        effective_limit = self._config.max_requests_per_minute + self._config.burst_capacity
        remaining = max(0, effective_limit - count)

        if count > effective_limit:
            retry_after = self._config.cooldown_seconds
            reset_at = datetime.fromtimestamp(now + retry_after, tz=timezone.utc).isoformat()
            return RateLimitStatus(allowed=False, remaining=0, reset_at=reset_at, retry_after=retry_after)

        if total_tokens > self._config.max_tokens_per_hour:
            retry_after = 3600 - (int(now) % 3600)
            reset_at = datetime.fromtimestamp(
                (int(now) - (int(now) % 3600)) + 3600, tz=timezone.utc
            ).isoformat()
            return RateLimitStatus(allowed=False, remaining=0, reset_at=reset_at, retry_after=retry_after)

        # Periodic cleanup
        if hash(user_id) % 20 == 0:
            self._cleanup_expired()

        return RateLimitStatus(allowed=True, remaining=remaining)

    def get_usage_summary(self, user_id: str) -> dict[str, int]:
        """Return current rate window usage for a user."""
        window_key = self._get_window_key(user_id)
        row = self._conn.execute(
            "SELECT count, tokens FROM rate_windows WHERE window_key = ?",
            (window_key,),
        ).fetchone()
        if row is None:
            return {"requests": 0, "tokens": 0}
        return {"requests": row["count"], "tokens": row["tokens"]}
