"""Signal delivery adapter (Day 23).

Bridges the :mod:`app.core.scheduling.signal` abstraction
(typed reactive events from watchers) and the delivery layer
(:class:`BotSignal`).  Without this, the v2 watchers in
:mod:`app.routines` produce :class:`Signal` objects that
sit in the :class:`SignalRouter` queue but never reach the
user — because the watcher's own :func:`generate_signals`
returns the signals without knowing how to render them.

The adapter:

* subscribes to a :class:`SignalRouter` for a configurable
  set of :class:`SignalKind` values
* converts each :class:`Signal` into a :class:`SignalPayload`
  (the delivery-layer representation)
* resolves the (platform, chat_id) target from the signal
  payload (set by the watcher)
* calls ``botsignal.send`` for delivery

DND / value-gate filtering is intentionally NOT done here:
the proactive engine has its own contract (D11) and
bridging into it requires converting to ``ProactiveSignal``.
That integration is left for a follow-up day; the Day 23
adapter guarantees that signals are *at least delivered*,
which is a strict improvement over the v2 watchers that
currently produce signals no one consumes.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Sequence

from app.core.models import ReplyTarget, SignalPayload
from app.core.scheduling.signal import Signal, SignalKind, SignalRouter

logger = logging.getLogger(__name__)


# The platform/chat_id keys that watchers are expected to
# embed in their Signal payload.  Centralised here so the
# adapter stays the single source of truth for target
# resolution.
PLATFORM_KEY = "platform"
CHAT_ID_KEY = "chat_id"


class SignalDeliveryAdapter:
    """Subscribe to a router and deliver selected signals to the user.

    Parameters
    ----------
    router:
        The :class:`SignalRouter` to subscribe to.  Usually
        the process-wide default (``get_default_signal_router()``).
    botsignal:
        The delivery primitive.  Anything with an
        ``async send(target, payload)`` method works; in
        production this is :class:`BotSignal`.
    kinds:
        Which :class:`SignalKind` values to deliver.  Defaults
        to the three watcher kinds (``CALENDAR``, ``INTERNET``,
        ``AUTONOMY``); a no-op when a watcher omits one.
    user_id_resolver:
        Optional callable that maps a signal to a user_id.
        Defaults to ``signal.user_id``; provided so callers
        that build signals without a user_id (e.g. global
        ``SYSTEM`` signals) can still route them.
    """

    def __init__(
        self,
        router: SignalRouter,
        botsignal: Any,
        *,
        kinds: Sequence[SignalKind] = (
            SignalKind.CALENDAR,
            SignalKind.INTERNET,
            SignalKind.AUTONOMY,
        ),
        user_id_resolver: Callable[[Signal], str] | None = None,
    ) -> None:
        self.router = router
        self.botsignal = botsignal
        self.kinds: frozenset[SignalKind] = frozenset(kinds)
        self._user_id_resolver = user_id_resolver or (lambda s: s.user_id)
        self._unsubscribe: Callable[[], None] | None = None
        # Diagnostic counters — useful for /metrics and tests.
        self.delivered_count = 0
        self.skipped_count = 0
        self.error_count = 0

    # -- lifecycle --------------------------------------------------------

    def start(self) -> None:
        """Subscribe to the router.

        Idempotent: calling ``start`` twice is a no-op.
        """
        if self._unsubscribe is not None:
            return
        self._unsubscribe = self.router.subscribe(
            self._handle,
            name=f"signal_delivery_{id(self)}",
            predicate=self._filter,
        )
        logger.debug(
            "SignalDeliveryAdapter started: kinds=%s", sorted(k.value for k in self.kinds)
        )

    def stop(self) -> None:
        """Unsubscribe from the router.

        Idempotent: calling ``stop`` when not started is a no-op.
        """
        if self._unsubscribe is None:
            return
        self._unsubscribe()
        self._unsubscribe = None
        logger.debug("SignalDeliveryAdapter stopped")

    @property
    def is_running(self) -> bool:
        return self._unsubscribe is not None

    # -- filter + handler -------------------------------------------------

    def _filter(self, signal: Signal) -> bool:
        return signal.kind in self.kinds

    async def _handle(self, signal: Signal) -> None:
        target = self._resolve_target(signal)
        if target is None:
            self.skipped_count += 1
            return
        payload = self._to_payload(signal)
        try:
            await self.botsignal.send(target, payload)
        except Exception as exc:  # noqa: BLE001
            self.error_count += 1
            logger.warning(
                "SignalDeliveryAdapter: botsignal.send failed for %s: %s",
                signal.id,
                exc,
            )
            return
        self.delivered_count += 1

    # -- helpers ----------------------------------------------------------

    def _resolve_target(self, signal: Signal) -> ReplyTarget | None:
        """Build a :class:`ReplyTarget` from the signal payload.

        Returns ``None`` if the signal carries no usable
        platform/chat_id pair (e.g. a global ``SYSTEM``
        signal that wasn't targeted at any user).
        """
        platform = signal.payload.get(PLATFORM_KEY)
        chat_id = signal.payload.get(CHAT_ID_KEY)
        if not platform or not chat_id:
            logger.debug(
                "SignalDeliveryAdapter: signal %s missing %s/%s, skipping",
                signal.id,
                PLATFORM_KEY,
                CHAT_ID_KEY,
            )
            return None
        return ReplyTarget(platform=platform, chat_id=chat_id)

    @staticmethod
    def _to_payload(signal: Signal) -> SignalPayload:
        """Convert a :class:`Signal` into a :class:`SignalPayload`.

        Uses ``signal.body`` (longer-form markdown) when
        available, otherwise ``signal.title``.  The
        ``source_kind`` is set to ``"signal_<kind>"`` so
        downstream consumers can distinguish reactive
        watcher events from proactive briefings.
        """
        return SignalPayload(
            text=signal.body or signal.title,
            source_kind=f"signal_{signal.kind.value}",
        )

    # -- diagnostics ------------------------------------------------------

    def stats(self) -> dict[str, int]:
        return {
            "delivered": self.delivered_count,
            "skipped": self.skipped_count,
            "errors": self.error_count,
            "kinds": len(self.kinds),
        }


# -- module-level singleton (mirrors the Scheduler + Router pattern) -----

_adapter: SignalDeliveryAdapter | None = None


def get_default_signal_delivery_adapter() -> SignalDeliveryAdapter | None:
    """Return the process-wide adapter, or ``None`` if not wired."""
    return _adapter


def set_default_signal_delivery_adapter(adapter: SignalDeliveryAdapter | None) -> None:
    """Set or clear the process-wide adapter (mainly for tests)."""
    global _adapter
    _adapter = adapter


def reset_default_signal_delivery_adapter() -> None:
    set_default_signal_delivery_adapter(None)


__all__ = [
    "CHAT_ID_KEY",
    "PLATFORM_KEY",
    "SignalDeliveryAdapter",
    "get_default_signal_delivery_adapter",
    "reset_default_signal_delivery_adapter",
    "set_default_signal_delivery_adapter",
]
