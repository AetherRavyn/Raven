"""Cached approval-config reader (Phase 0.4).

`SecurityGuard.requires_approval()` and the legacy `PolicyEngine.
requires_approval()` historically read `~/.raven/user_config.json` on
every call — slow and prone to race conditions.

This module provides a single, cached reader backed by the same JSON
file. Reads are coalesced for 30 s; writes invalidate the cache
immediately so live edits still take effect.

Usage:

    from app.core.policy_cache import get_approval_config

    cfg = get_approval_config()
    level = cfg.get("approval_level", "Balanced")
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 30.0

_lock = threading.Lock()
_cache: dict[str, Any] | None = None
_cached_at: float = 0.0


def _config_path() -> Path:
    return Path(os.path.expanduser("~/.raven/user_config.json"))


def _read_from_disk() -> dict[str, Any]:
    """Read the user config from disk, returning {} on any failure."""
    p = _config_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # nosec - we want to fall back gracefully
        logger.debug("policy_cache: failed to read %s: %s", p, exc)
        return {}


def invalidate() -> None:
    """Force the next call to re-read from disk."""
    global _cache, _cached_at
    with _lock:
        _cache = None
        _cached_at = 0.0


def get_approval_config(*, ttl: float = DEFAULT_TTL_SECONDS) -> dict[str, Any]:
    """Return the current approval config, cached for ``ttl`` seconds.

    The first call reads from disk; subsequent calls within ``ttl``
    return the cached dict without touching the disk.

    The cache is invalidated automatically when the file's mtime moves
    forward — so manual edits are picked up within one TTL window even
    if :func:`invalidate` is not called.
    """
    global _cache, _cached_at
    now = time.monotonic()
    p = _config_path()
    try:
        mtime = p.stat().st_mtime if p.exists() else 0.0
    except OSError:
        mtime = 0.0

    with _lock:
        if (
            _cache is not None
            and (now - _cached_at) < ttl
            and _cache.get("__mtime__") == mtime
        ):
            return _cache
        fresh = _read_from_disk()
        fresh["__mtime__"] = mtime
        _cache = fresh
        _cached_at = now
        return _cache


__all__ = ["get_approval_config", "invalidate", "DEFAULT_TTL_SECONDS"]