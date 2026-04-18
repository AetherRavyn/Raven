from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.core.proactive import (
    ProactiveDigest,
    build_cross_platform_targets,
    send_proactive_digest,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EventDigest:
    title: str
    items: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def anomaly_to_digest(payload: dict[str, Any]) -> EventDigest:
    camera = payload.get("camera_id") or payload.get("camera") or "unknown"
    desc = payload.get("description") or payload.get("event_type") or "event"
    risk = payload.get("risk_level") or payload.get("severity") or "info"
    return EventDigest(
        title=f"Alert: {desc}",
        items=[f"Camera: {camera}", f"Risk: {risk}"],
        metadata=payload,
    )


async def broadcast_event_digest(event: dict[str, Any]) -> None:
    digest = anomaly_to_digest(event)
    proactive = ProactiveDigest(title=digest.title, items=digest.items, source="event")
    targets = build_cross_platform_targets()
    if not targets:
        logger.debug("No proactive targets configured; dropping event digest")
        return
    for target in targets:
        await send_proactive_digest(target, proactive)
