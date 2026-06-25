"""Stranger anomaly detector for the Home Protection module.

``StrangerDetector`` is the ``anomaly_detector`` contribution declared in
``module.yaml`` (``detectors.py:StrangerDetector``). It listens to the
``front_door_camera`` event source and raises a CRITICAL
:class:`~app.modules.models.RaisedEvent` whenever a ``stranger`` frame arrives
with a confidence above the alerting threshold.

The Module_Loader instantiates the detector with no constructor arguments.
"""

from __future__ import annotations

import logging

from app.core.output_router import Priority
from app.modules.models import ModuleEvent, RaisedEvent

logger = logging.getLogger(__name__)

# Minimum confidence before a stranger frame is escalated. Mirrors the manifest's
# proactive-reaction condition (``event.confidence > 0.7``) so the detector and
# the standing reaction agree on what counts as an intruder.
_STRANGER_CONFIDENCE_THRESHOLD = 0.7


class StrangerDetector:
    """Raises a CRITICAL event when an unknown person appears at the door.

    Attributes:
        name: The detector name (matches the manifest ``provides`` entry).
        listens_to: The event-source name this detector inspects events from.
        default_priority: The priority used when none is otherwise supplied.
    """

    name = "stranger_detector"
    listens_to = "front_door_camera"
    default_priority: Priority = Priority.CRITICAL

    async def inspect(self, event: ModuleEvent) -> RaisedEvent | None:
        """Inspect a camera event and raise a CRITICAL event for strangers.

        Returns ``None`` for any non-stranger event or a stranger seen below the
        confidence threshold, so only credible intruders are escalated.
        """
        if event.type != "stranger":
            return None
        if event.confidence <= _STRANGER_CONFIDENCE_THRESHOLD:
            logger.debug(
                "Stranger below threshold (confidence=%.2f); not raising",
                event.confidence,
            )
            return None

        label = str(event.payload.get("label", "unknown person"))
        logger.warning(
            "Stranger detected at %s (confidence=%.2f)",
            event.payload.get("camera_id", "front_door"),
            event.confidence,
        )
        return RaisedEvent(
            detector_name=self.name,
            message=f"Stranger detected at the front door: {label}",
            priority=Priority.CRITICAL.name,
            payload={
                "camera_id": event.payload.get("camera_id", "front_door"),
                "label": label,
                "confidence": event.confidence,
            },
        )
