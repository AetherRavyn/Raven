"""Front-door camera event source for the Home Protection module.

``FrontDoorCamera`` is the ``event_source`` contribution declared in
``module.yaml`` (``sources.py:FrontDoorCamera``). The Module_Loader instantiates
it with no constructor arguments and the Event_Bridge drives its lifecycle:
``start(emit)`` begins producing :class:`~app.modules.models.ModuleEvent`s and
``stop()`` halts production and releases resources.

This reference implementation does not open a real RTSP stream; it emits a small
sequence of synthetic frame events so the worked example can run end-to-end. A
production source would read ``CAMERA_RTSP_URL`` and the manifest ``config``
(``camera_id``/``fps``) to pull real frames.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.modules.models import ModuleEvent

logger = logging.getLogger(__name__)

MODULE_ID = "skill.home.protection"

# Synthetic frame stream used by the worked example: a couple of benign frames
# followed by a high-confidence stranger so the detector + reaction fire.
_DEMO_FRAMES: tuple[dict[str, object], ...] = (
    {"type": "frame", "label": "known_resident", "confidence": 0.95},
    {"type": "frame", "label": "empty_porch", "confidence": 0.99},
    {"type": "stranger", "label": "unknown_person", "confidence": 0.88},
)


class FrontDoorCamera:
    """A camera event source that emits front-door frame events.

    Attributes:
        name: The source name the Event_Bridge keys detectors against
            (must match the manifest ``provides`` entry and each detector's
            ``listens_to``).
    """

    name = "front_door_camera"

    def __init__(self) -> None:
        self._camera_id = "front_door"
        self._fps = 5
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    async def start(self, emit: Callable[[ModuleEvent], Awaitable[None]]) -> None:
        """Begin producing frame events, delivering each through ``emit``.

        Runs until :meth:`stop` is called. Each synthetic frame becomes a
        ``ModuleEvent`` tagged with this module and source so detectors listening
        to ``front_door_camera`` can inspect it.
        """
        self._stopped.clear()
        logger.info(
            "FrontDoorCamera starting (camera_id=%s, fps=%s)",
            self._camera_id,
            self._fps,
        )
        try:
            for frame in _DEMO_FRAMES:
                if self._stopped.is_set():
                    break
                await emit(
                    ModuleEvent(
                        module_id=MODULE_ID,
                        source_name=self.name,
                        type=str(frame["type"]),
                        payload={
                            "camera_id": self._camera_id,
                            "label": frame["label"],
                        },
                        confidence=float(frame["confidence"]),  # type: ignore[arg-type]
                    )
                )
                # Pace emissions at the configured frame rate without blocking.
                await asyncio.sleep(1 / self._fps)
        except asyncio.CancelledError:  # pragma: no cover - cooperative shutdown
            logger.debug("FrontDoorCamera emit loop cancelled")
            raise

    async def stop(self) -> None:
        """Stop producing events and release any held resources."""
        self._stopped.set()
        logger.info("FrontDoorCamera stopped (camera_id=%s)", self._camera_id)
