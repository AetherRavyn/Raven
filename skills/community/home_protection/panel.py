"""Dashboard UI surface for the Home Protection module.

``render_panel`` is the ``ui_surface`` contribution declared in ``module.yaml``
(``panel.py:render_panel``). It is a module-level coroutine that returns a small
HTML fragment (:data:`~app.modules.models.PanelHtml`) the dashboard embeds as the
module's camera panel.
"""

from __future__ import annotations

import logging

from app.modules.models import PanelHtml

logger = logging.getLogger(__name__)

PANEL_NAME = "camera_panel"


async def render_panel() -> PanelHtml:
    """Render the Home Protection camera panel as an HTML fragment."""
    logger.debug("Rendering %s", PANEL_NAME)
    return (
        '<section class="ravyn-panel home-protection" '
        'data-panel="camera_panel">'
        "<h3>Home Protection</h3>"
        '<p class="status">Front door camera: monitoring</p>'
        '<ul class="capabilities">'
        "<li>Source: front_door_camera</li>"
        "<li>Detector: stranger_detector (CRITICAL)</li>"
        "<li>Reaction: intruder_response &rarr; snapshot + notify</li>"
        "</ul>"
        "</section>"
    )
