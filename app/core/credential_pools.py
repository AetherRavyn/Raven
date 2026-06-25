"""Credential Pools — distribute API calls across multiple keys with rotation.

Manages pools of API keys per provider, rotates on rate limits/failures,
and tracks usage per key for cost allocation.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CredentialPool:
    """Manages multiple API keys for a single provider with rotation."""

    def __init__(self, provider: str, keys: list[str], cooldown_seconds: int = 60) -> None:
        self.provider = provider
        self._keys = deque(keys)
        self._cooldowns: dict[str, float] = {}
        self._usage: dict[str, int] = {}
        self._cooldown_seconds = cooldown_seconds

    def get_key(self) -> str | None:
        """Get the next available API key (rotating through the pool)."""
        now = time.time()

        for _ in range(len(self._keys)):
            key = self._keys[0]
            self._keys.rotate(-1)

            # Check cooldown
            cooldown_until = self._cooldowns.get(key, 0)
            if now >= cooldown_until:
                self._usage[key] = self._usage.get(key, 0) + 1
                return key

        return None  # All keys on cooldown

    def mark_rate_limited(self, key: str) -> None:
        """Mark a key as rate-limited (cooldown)."""
        self._cooldowns[key] = time.time() + self._cooldown_seconds
        logger.warning("CredentialPool[%s]: key rate-limited, cooldown %ds", self.provider, self._cooldown_seconds)

    def mark_failed(self, key: str) -> None:
        """Mark a key as failed (shorter cooldown)."""
        self._cooldowns[key] = time.time() + 10

    def get_stats(self) -> dict[str, Any]:
        now = time.time()
        available = sum(1 for k in self._keys if self._cooldowns.get(k, 0) <= now)
        return {
            "provider": self.provider,
            "total_keys": len(self._keys),
            "available": available,
            "on_cooldown": len(self._keys) - available,
            "usage": dict(self._usage),
        }


class CredentialPoolManager:
    """Manages credential pools across all providers."""

    def __init__(self) -> None:
        self._pools: dict[str, CredentialPool] = {}

    def register_pool(self, provider: str, keys: list[str], cooldown: int = 60) -> None:
        """Register a credential pool for a provider."""
        if keys:
            self._pools[provider] = CredentialPool(provider, keys, cooldown)
            logger.info("CredentialPool: registered %d keys for %s", len(keys), provider)

    def get_key(self, provider: str) -> str | None:
        """Get next available key for a provider."""
        pool = self._pools.get(provider)
        if pool:
            return pool.get_key()
        return None

    def mark_rate_limited(self, provider: str, key: str) -> None:
        pool = self._pools.get(provider)
        if pool:
            pool.mark_rate_limited(key)

    def mark_failed(self, provider: str, key: str) -> None:
        pool = self._pools.get(provider)
        if pool:
            pool.mark_failed(key)

    def get_all_stats(self) -> dict[str, Any]:
        return {
            name: pool.get_stats()
            for name, pool in self._pools.items()
        }


# Singleton
_pool_manager: CredentialPoolManager | None = None


def get_credential_pool_manager() -> CredentialPoolManager:
    global _pool_manager
    if _pool_manager is None:
        _pool_manager = CredentialPoolManager()
        # Auto-register from environment
        import os
        for provider, env_var in [
            ("openai", "OPENAI_API_KEYS"),
            ("anthropic", "ANTHROPIC_API_KEYS"),
            ("google", "GOOGLE_API_KEYS"),
        ]:
            keys_str = os.environ.get(env_var, "")
            if keys_str:
                keys = [k.strip() for k in keys_str.split(",") if k.strip()]
                if keys:
                    _pool_manager.register_pool(provider, keys)
    return _pool_manager
