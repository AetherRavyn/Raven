"""Delivery adapter — ProactiveDecision → BotSignal.

A :class:`DeliveryAdapter` is the bridge between the (pure)
:mod:`app.core.proactive_core` decision engine and the (impure)
:mod:`app.core.botsignal` delivery layer.  It:

1. Calls :meth:`ProactiveEngine.evaluate` on a signal.
2. If the decision is ``SPEAK``, formats the payload and sends it
   via the registered :class:`BotSignal`.
3. Always records an audit-style decision log so the operator can
   see *why* a signal was muted.

The adapter is intentionally thin — it does not retry, queue, or
back-off.  Those concerns belong to the delivery layer
(BotSignal / channel connectors).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from app.core.audit import AuditEvent, get_action_logger
from app.core.botsignal import BotSignal, get_botsignal
from app.core.models import SignalPayload

if TYPE_CHECKING:
    from app.core.proactive_core import (
        DecisionVerdict,
        ProactiveDecision,
        ProactiveEngine,
        ProactiveSignal,
    )

logger = logging.getLogger(__name__)


# Type for the optional delivery callback (used in tests).
DeliverySender = Callable[["ProactiveDecision"], Awaitable[None]]


class DeliveryAdapter:
    """Send a signal through the engine and act on the decision.

    The adapter can run in two modes:

    * **Real** — calls BotSignal to deliver ``SPEAK`` decisions.
    * **Test** — uses a custom ``sender`` callable so unit tests
      can assert on the decision stream without touching BotSignal.
    """

    def __init__(
        self,
        engine: ProactiveEngine,
        *,
        botsignal: BotSignal | None = None,
        sender: DeliverySender | None = None,
    ) -> None:
        self._engine = engine
        self._botsignal = botsignal
        self._custom_sender = sender
        self._logger = get_action_logger()

    async def dispatch(
        self,
        signal: ProactiveSignal,
        *,
        sender: DeliverySender | None = None,
    ) -> ProactiveDecision:
        """Run the engine, then act on the decision.

        ``sender`` overrides the constructor's sender for this call
        only — used in tests to assert on a single signal.
        """
        decision = await self._engine.evaluate(signal)
        self._record_decision(decision)
        from app.core.proactive_core import DecisionVerdict

        if decision.verdict != DecisionVerdict.SPEAK:
            return decision

        effective_sender = sender or self._custom_sender
        if effective_sender is not None:
            await effective_sender(decision)
            return decision

        if self._botsignal is None:
            logger.warning(
                "SPEAK decision with no sender configured: id=%s kind=%s",
                signal.id,
                signal.kind.value,
            )
            return decision

        await self._botsignal.send(
            decision.target,  # type: ignore[arg-type]
            self._build_payload(decision),
        )
        return decision

    def _build_payload(self, decision: ProactiveDecision) -> SignalPayload:
        signal = decision.signal
        text_parts: list[str] = []
        if signal.title:
            text_parts.append(signal.title)
        if signal.body:
            text_parts.append(signal.body)
        text = "\n".join(text_parts).strip()
        if not text:
            text = "(empty proactive signal)"

        return SignalPayload(
            text=text,
            source_kind=signal.source or "proactive",
        )

    def _record_decision(self, decision: ProactiveDecision) -> None:
        """Emit an audit event for the decision."""
        from app.core.proactive_core import DecisionVerdict

        try:
            self._logger.record(
                AuditEvent(
                    kind="proactive_decision",
                    actor="proactive_engine",
                    action=decision.verdict.value,
                    target=decision.signal.id,
                    success=decision.verdict == DecisionVerdict.SPEAK,
                    risk_level=self._risk_for(decision),
                    detail=decision.reason or None,
                    metadata={
                        "user_id": decision.signal.user_id,
                        "kind": decision.signal.kind.value,
                        "urgency": decision.signal.urgency.value,
                        "stage": decision.stage,
                        "score": decision.score,
                        "channel": decision.channel,
                    },
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Audit log of proactive decision failed: %s", exc)

    def _risk_for(self, decision: ProactiveDecision) -> Any:
        """Map decision outcomes to audit log risk levels."""
        # Lazy import so we don't introduce a hard dependency on
        # the audit package's enum at module load time.
        from app.core.audit.types import RiskLevel

        if decision.verdict == DecisionVerdict.SPEAK:
            return RiskLevel.LOW
        if decision.verdict == DecisionVerdict.DEFER:
            return RiskLevel.LOW
        return RiskLevel.LOW  # we treat mute decisions as low-risk audit


def build_default_adapter(
    user_id: str,
    *,
    chat_id: str,
    channel: str = "telegram",
    botsignal: BotSignal | None = None,
) -> DeliveryAdapter:
    """One-call helper: build an engine + adapter for a user."""
    from app.core.proactive_core import configure_default_engine

    engine = configure_default_engine(user_id, chat_id=chat_id, channel=channel)
    return DeliveryAdapter(engine, botsignal=botsignal or get_botsignal())
