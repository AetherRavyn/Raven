"""Bootstrap routines that wire the proactive engine into a running system.

The :func:`register_proactive_core` function is called once at
startup.  For each user listed in ``MORNING_BRIEFING_USERS`` it
creates a :class:`ProactiveEngine` with sensible defaults and
registers a corresponding :class:`DeliveryAdapter`.

The registry is process-global (a module-level dict).  Tests can
call :func:`reset_registry` to start clean.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.core.botsignal import BotSignal, get_botsignal
from app.settings.config import Config

if TYPE_CHECKING:
    from app.core.proactive_core import (
        EngineConfig,
        ProactiveEngine,
        QuietWindow,
    )
    from app.core.proactive_core.delivery import DeliveryAdapter

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class UserProactiveContext:
    """Per-user engine + adapter.

    Holds references to both, plus the channel/chat_id that
    produced them, so the operator can inspect the wiring.
    """

    user_id: str
    chat_id: str
    channel: str
    engine: "ProactiveEngine"
    adapter: "DeliveryAdapter"


_REGISTRY: dict[str, UserProactiveContext] = {}


def get_context(user_id: str) -> UserProactiveContext | None:
    return _REGISTRY.get(user_id)


def all_contexts() -> list[UserProactiveContext]:
    return list(_REGISTRY.values())


def reset_registry() -> None:
    """Clear the registry — used by tests."""
    _REGISTRY.clear()


@dataclass(slots=True)
class ProactiveBootstrapConfig:
    """User-overridable knobs for the bootstrap."""

    default_channel: str = "telegram"
    quiet_window: QuietWindow | None = None
    # Per-user channel override; the standard env var is parsed
    # first, this dict is the override layer.
    channel_overrides: dict[str, str] = field(default_factory=dict)
    engine_config: EngineConfig | None = None


def _parse_user_entry(entry: str) -> tuple[str, str, str] | None:
    """Parse a "platform:user_id:chat_id" entry.  Returns None on bad input."""
    parts = entry.strip().split(":")
    if len(parts) != 3:
        return None
    return parts[0], parts[1], parts[2]


def register_proactive_core(
    botsignal: BotSignal | None = None,
    config: ProactiveBootstrapConfig | None = None,
    raw_users: str | None = None,
) -> list[UserProactiveContext]:
    """Wire engines + adapters for every configured user.

    Idempotent — re-registering a user replaces the previous
    context.  Returns the new contexts.
    """
    # Imports deferred to avoid a circular import at module load.
    from app.core.proactive_core import configure_default_engine
    from app.core.proactive_core.delivery import DeliveryAdapter

    cfg = config or ProactiveBootstrapConfig()
    bs = botsignal or get_botsignal()
    raw = raw_users if raw_users is not None else Config.MORNING_BRIEFING_USERS
    if not raw:
        logger.debug("No proactive users configured; bootstrap skipped")
        return []

    contexts: list[UserProactiveContext] = []
    for entry in raw.split(","):
        parsed = _parse_user_entry(entry)
        if parsed is None:
            logger.debug("Skipping malformed user entry: %r", entry)
            continue
        platform, user_id, chat_id = parsed
        channel = cfg.channel_overrides.get(user_id, platform) or cfg.default_channel
        engine = configure_default_engine(
            user_id,
            chat_id=chat_id,
            channel=channel,
            quiet_window=cfg.quiet_window,
        )
        adapter = DeliveryAdapter(engine, botsignal=bs)
        ctx = UserProactiveContext(
            user_id=user_id,
            chat_id=chat_id,
            channel=channel,
            engine=engine,
            adapter=adapter,
        )
        _REGISTRY[user_id] = ctx
        contexts.append(ctx)
        logger.info(
            "Proactive core registered for user_id=%s channel=%s chat_id=%s",
            user_id,
            channel,
            chat_id,
        )
    return contexts


def unregister(user_id: str) -> bool:
    """Remove a user from the registry.  Returns True if removed."""
    return _REGISTRY.pop(user_id, None) is not None
