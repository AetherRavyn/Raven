"""Web dashboard — routes migrated to ``app.api.server:app``.

The ``WebDashboard`` class was removed in favor of the unified
``app.api.server:app`` which serves all Hermes dashboard pages,
OpenAI-compatible API, ACP, and WebSocket endpoints from a single
FastAPI app on port 8090 (``raven run``).

Legacy references (``tests/conftest.py``, ``tests/visual/snap.py``,
``tests/test_life_dashboard_routes.py``) have been updated to import
directly from ``app.api.server``.
"""

from __future__ import annotations

from typing import Set

from fastapi import WebSocket


_WS_CONNECTIONS: dict[str, WebSocket] = {}
_EVENT_SUBSCRIBERS: Set[WebSocket] = set()
