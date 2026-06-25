# app/core/ratelimit.py
"""Rate limiter with SQLite persistence — survives restarts."""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

logger = logging.getLogger(__name__)

_WINDOW_SECONDS = 60
_MAX_REQUESTS_PER_WINDOW = 20
_BURST_WINDOW_SECONDS = 5
_MAX_BURST = 5


class RateLimiter:
    """Sliding window rate limiter with optional SQLite persistence."""

    def __init__(
        self,
        window_seconds: int = _WINDOW_SECONDS,
        max_requests: int = _MAX_REQUESTS_PER_WINDOW,
        burst_window: int = _BURST_WINDOW_SECONDS,
        max_burst: int = _MAX_BURST,
    ) -> None:
        self._window = window_seconds
        self._limit = max_requests
        self._burst_window = burst_window
        self._burst_limit = max_burst
        self._history: dict[str, deque[float]] = defaultdict(deque)
        self._db: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        """Initialize SQLite persistence."""
        try:
            db_path = Path("workspace/ratelimit.sqlite")
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(db_path), check_same_thread=False)
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS rate_limits (
                    user_key TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    PRIMARY KEY (user_key, timestamp)
                )
            """)
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_rl_key ON rate_limits(user_key)"
            )
            self._db.commit()
        except Exception as exc:
            logger.debug("RateLimiter SQLite init failed (in-memory mode): %s", exc)
            self._db = None

    def _load_history(self, user_key: str) -> deque[float]:
        """Load request history from SQLite."""
        if not self._db:
            return self._history[user_key]
        try:
            cutoff = time.time() - self._window
            rows = self._db.execute(
                "SELECT timestamp FROM rate_limits WHERE user_key = ? AND timestamp > ?",
                (user_key, cutoff),
            ).fetchall()
            return deque(r[0] for r in rows)
        except Exception:
            return self._history[user_key]

    def _save_timestamp(self, user_key: str, ts: float) -> None:
        """Persist a timestamp to SQLite."""
        if not self._db:
            return
        try:
            self._db.execute(
                "INSERT INTO rate_limits (user_key, timestamp) VALUES (?, ?)",
                (user_key, ts),
            )
            self._db.commit()
        except Exception:
            pass

    def _cleanup_old(self) -> None:
        """Remove old entries from SQLite."""
        if not self._db:
            return
        try:
            cutoff = time.time() - self._window * 2
            self._db.execute("DELETE FROM rate_limits WHERE timestamp < ?", (cutoff,))
            self._db.commit()
        except Exception:
            pass

    def is_allowed(self, user_key: str) -> tuple[bool, str]:
        """Check if the request is within rate limits."""
        now = time.monotonic()
        wall_now = time.time()

        with self._lock:
            history = self._load_history(user_key)

            # Remove timestamps outside the main window
            while history and now - history[0] > self._window:
                history.popleft()

            # Check burst
            burst_count = sum(1 for t in history if now - t <= self._burst_window)
            if burst_count >= self._burst_limit:
                retry_after = self._burst_window
                return (
                    False,
                    f"Slow down — max {self._burst_limit} requests per {self._burst_window}s.",
                )

            # Check main window
            if len(history) >= self._limit:
                return (
                    False,
                    f"Rate limit exceeded — max {self._limit} requests per {self._window}s.",
                )

            history.append(now)
            self._history[user_key] = history
            self._save_timestamp(user_key, wall_now)

        # Periodic cleanup
        if hash(user_key) % 20 == 0:
            self._cleanup_old()

        return True, ""


_GLOBAL_RATE_LIMITER: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """Return the rate limiter (SQLite-backed, persistent across restarts)."""
    global _GLOBAL_RATE_LIMITER
    if _GLOBAL_RATE_LIMITER is not None:
        return _GLOBAL_RATE_LIMITER
    _GLOBAL_RATE_LIMITER = RateLimiter()
    return _GLOBAL_RATE_LIMITER
