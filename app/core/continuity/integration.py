"""Continuity-aware target resolution for proactive delivery.

When the proactive engine decides to SPEAK, it needs a
``(platform, chat_id)`` to send to.  The :class:`TargetResolver`
protocol decouples "decide to speak" from "where to send".

Three implementations:

  * :class:`DefaultTargetResolver` — returns the bootstrap
    channel (the (channel, chat_id) configured at startup).
  * :class:`ContinuityTargetResolver` — looks up the user's
    primary active session and returns its channel.  Falls
    back to any bound channel.  Falls back to None.
  * :class:`CompositeTargetResolver` — tries each child in
    order, returns the first non-None result.

The default wiring in :func:`register_proactive_core` uses a
composite: continuity first, default as the last resort.  That
makes the engine "follow the user" — proactive messages go to
the device they're actively using, not the device that
happened to register the context.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# protocol
# -------------------------------------------------------------------


class TargetResolver(Protocol):
    """Map a user_id to a (platform, chat_id) tuple.

    Returns None when no target is available — the caller
    should treat that as a SILENCE decision.
    """

    def resolve(self, user_id: str) -> tuple[str, str] | None: ...


# -------------------------------------------------------------------
# default: bootstrap channel
# -------------------------------------------------------------------


@dataclass(slots=True)
class DefaultTargetResolver:
    """Always returns the bootstrap-configured (platform, chat_id)."""

    platform: str = "telegram"
    chat_id: str = ""

    def resolve(self, user_id: str) -> tuple[str, str] | None:
        if not self.chat_id:
            return None
        return self.platform, self.chat_id


# -------------------------------------------------------------------
# continuity-aware
# -------------------------------------------------------------------


@dataclass(slots=True)
class ContinuityTargetResolver:
    """Resolve a user to their currently-active channel.

    Lookup order:
      1. primary active session's channel_id (most recent)
      2. any bound channel for the user (any device)
      3. None

    All lookups are read-only against the in-memory continuity
    store.  No locks are taken inside the resolver — callers
    serialize dispatch on the engine, and the continuity
    singleton is itself thread-safe.
    """

    def resolve(self, user_id: str) -> tuple[str, str] | None:
        try:
            from app.core.continuity import continuity

            c = continuity()
        except Exception as exc:  # noqa: BLE001
            logger.debug("continuity unavailable for resolver: %s", exc)
            return None

        # 1. primary session
        primary = c.primary_session(user_id)
        if primary is not None and primary.channel_id:
            pair = self._split(primary.channel_id)
            if pair is not None:
                return pair

        # 2. any bound channel
        for ch in c.identity.list_channels():
            device = c.identity.get_device(ch.device_id)
            if device is None:
                continue
            if device.user_id == user_id:
                pair = self._split(ch.id)
                if pair is not None:
                    return pair
        return None

    @staticmethod
    def _split(channel_id: str) -> tuple[str, str] | None:
        if ":" not in channel_id:
            return None
        platform, chat_id = channel_id.split(":", 1)
        if not platform or not chat_id:
            return None
        return platform, chat_id


# -------------------------------------------------------------------
# composite: try in order
# -------------------------------------------------------------------


@dataclass(slots=True)
class CompositeTargetResolver:
    """Try each child in order; first non-None wins.

    Used by the bootstrap to layer "continuity first, default
    as last resort".  A child returning None is not a failure
    — the next child is tried.
    """

    resolvers: tuple[TargetResolver, ...] = ()

    def resolve(self, user_id: str) -> tuple[str, str] | None:
        for r in self.resolvers:
            try:
                pair = r.resolve(user_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("resolver %s failed: %s", type(r).__name__, exc)
                continue
            if pair is not None:
                return pair
        return None


# -------------------------------------------------------------------
# helpers
# -------------------------------------------------------------------


def build_default_resolver(
    *,
    platform: str = "telegram",
    chat_id: str = "",
    use_continuity: bool = True,
) -> TargetResolver:
    """One-call helper for the bootstrap.

    Returns a composite resolver: continuity first (if
    requested and importable), then the bootstrap default.
    """
    chain: list[TargetResolver] = []
    if use_continuity:
        chain.append(ContinuityTargetResolver())
    chain.append(DefaultTargetResolver(platform=platform, chat_id=chat_id))
    if len(chain) == 1:
        return chain[0]
    return CompositeTargetResolver(resolvers=tuple(chain))


def resolve_user_channels(
    user_ids: Iterable[str],
    resolver: TargetResolver,
) -> dict[str, tuple[str, str] | None]:
    """Resolve a batch of users.  Used by the operator dashboard."""
    return {uid: resolver.resolve(uid) for uid in user_ids}
