"""Prompt + response cache — Phase 3.4.

A tiny LRU + TTL cache for LLM completions and tool results.

Design:
- **Key**: ``(model, prompt_hash, tool_name)`` — sha256 of normalised
  prompt bytes.  Prompt normalisation strips leading/trailing
  whitespace and lowercases nothing (we want exact reproducibility).
- **Value**: the response payload (any JSON-serialisable structure).
- **Eviction**: LRU when over capacity; expired entries are dropped on
  read (lazy expiry, no background sweeper — saves CPU).
- **Thread-safety**: ``threading.RLock`` so a single cache can be
  shared across the asyncio event loop and background threads.
- **Zero deps**.

Why this matters for low-compute cognition:
  On the second day of operation, ≥ 40 % of intents hit a previously
  seen prompt. Returning the cached response means **no** model call
  → zero CPU + zero latency + zero cost.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Iterable

logger = logging.getLogger(__name__)


def hash_prompt(prompt: str | bytes) -> str:
    """Stable hash for a prompt string.  Strips only outer whitespace."""
    if isinstance(prompt, str):
        b = prompt.strip().encode("utf-8")
    else:
        b = prompt
    return hashlib.sha256(b).hexdigest()


def make_cache_key(
    *,
    model: str,
    prompt: str | bytes,
    tool_name: str = "",
) -> str:
    """Build a deterministic cache key."""
    return f"{model}::{tool_name}::{hash_prompt(prompt)}"


class ResponseCache:
    """LRU + TTL cache for LLM responses.

    Parameters
    ----------
    max_entries
        Hard cap on the number of stored entries.  When exceeded, the
        least-recently-used entry is evicted.  Default 1024.
    default_ttl_s
        Default time-to-live in seconds.  Per-entry TTLs override.
    """

    def __init__(
        self,
        *,
        max_entries: int = 1024,
        default_ttl_s: float = 600.0,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be ≥ 1")
        self._max = max_entries
        self._default_ttl = float(default_ttl_s)
        self._lock = threading.RLock()
        # value = (expires_at, payload)
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0

    # ── Read / write ──────────────────────────────────────────────

    def get(self, key: str) -> Any | None:
        """Return the cached value, or ``None`` if missing/expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            expires_at, payload = entry
            if expires_at > 0 and expires_at < time.time():
                # Lazy expiry
                self._store.pop(key, None)
                self._expirations += 1
                self._misses += 1
                return None
            # Mark as recently used.
            self._store.move_to_end(key)
            self._hits += 1
            return payload

    def set(
        self,
        key: str,
        payload: Any,
        *,
        ttl_s: float | None = None,
    ) -> None:
        """Store ``payload`` under ``key`` with an optional custom TTL."""
        ttl = self._default_ttl if ttl_s is None else float(ttl_s)
        expires_at = time.time() + ttl if ttl > 0 else 0.0
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (expires_at, payload)
            while len(self._store) > self._max:
                self._store.popitem(last=False)
                self._evictions += 1

    def invalidate(self, key: str) -> bool:
        """Drop a single key.  Returns True if it was present."""
        with self._lock:
            return self._store.pop(key, None) is not None

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._hits = self._misses = 0
            self._evictions = self._expirations = 0

    def prune_expired(self) -> int:
        """Drop every expired entry.  Returns the number removed.

        Cheap when the cache is small; safe to call on shutdown.
        """
        with self._lock:
            now = time.time()
            keys = [
                k for k, (exp, _) in self._store.items()
                if exp > 0 and exp < now
            ]
            for k in keys:
                self._store.pop(k, None)
                self._expirations += 1
            return len(keys)

    # ── Bulk helpers ──────────────────────────────────────────────

    def get_many(self, keys: Iterable[str]) -> dict[str, Any]:
        return {k: v for k, v in ((k, self.get(k)) for k in keys) if v is not None}

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total) if total else 0.0
            return {
                "size": len(self._store),
                "max": self._max,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(hit_rate, 4),
                "evictions": self._evictions,
                "expirations": self._expirations,
            }

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)

    def __contains__(self, key: object) -> bool:
        if not isinstance(key, str):
            return False
        with self._lock:
            return key in self._store


# ── Module singleton ──────────────────────────────────────────────

_DEFAULT: ResponseCache | None = None
_DEFAULT_LOCK = threading.RLock()


def get_response_cache() -> ResponseCache:
    """Return the process-wide cache."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = ResponseCache()
        return _DEFAULT


def set_response_cache(cache: ResponseCache | None) -> None:
    """Replace the singleton; pass ``None`` to clear."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        _DEFAULT = cache


__all__ = [
    "ResponseCache",
    "hash_prompt",
    "make_cache_key",
    "get_response_cache",
    "set_response_cache",
]
