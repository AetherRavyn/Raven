"""Live Canvas — Agent-driven visual workspace (A2UI-inspired).

The agent generates and controls UI components in real-time. Components
are rendered as HTML via the web dashboard WebSocket endpoint.

Supported components:
- Text/Markdown blocks
- Data tables
- Charts (bar, line, pie)
- Code editors
- Forms with input fields
- Image viewers
- Terminal output
- Progress indicators
- Metric cards

Usage:
    canvas = LiveCanvas()
    card = canvas.add(MetricCard(title="CPU", value="42%"))
    canvas.update(card.id, {"value": "38%"})
    html = canvas.render()
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ComponentType(str, Enum):
    MARKDOWN = "markdown"
    TABLE = "table"
    CHART = "chart"
    CODE = "code"
    FORM = "form"
    IMAGE = "image"
    TERMINAL = "terminal"
    PROGRESS = "progress"
    METRIC = "metric"
    DIVIDER = "divider"


@dataclass
class CanvasComponent:
    """A single UI component on the canvas."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    type: str = ComponentType.MARKDOWN.value
    title: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    visible: bool = True
    order: int = 0
    width: str = "full"   # "full", "half", "third", "quarter"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = ""


class LiveCanvas:
    """Agent-driven visual workspace.

    The agent adds, updates, and removes components. The canvas state
    is serialized to JSON and pushed to connected clients via WebSocket.
    """

    def __init__(self, canvas_id: str = "main") -> None:
        self._id = canvas_id
        self._components: dict[str, CanvasComponent] = {}
        self._order_counter = 0
        self._listeners: list[Any] = []
        self._version = 0

    # ── Component CRUD ──────────────────────────────────────────────

    def add(
        self,
        component_type: str | ComponentType,
        title: str = "",
        data: dict[str, Any] | None = None,
        width: str = "full",
        component_id: str | None = None,
    ) -> CanvasComponent:
        """Add a component to the canvas."""
        if isinstance(component_type, ComponentType):
            component_type = component_type.value

        self._order_counter += 1
        comp = CanvasComponent(
            id=component_id or uuid.uuid4().hex[:10],
            type=component_type,
            title=title,
            data=data or {},
            order=self._order_counter,
            width=width,
        )
        self._components[comp.id] = comp
        self._version += 1
        self._notify("add", comp)
        return comp

    def update(self, component_id: str, data: dict[str, Any]) -> bool:
        """Update a component's data."""
        comp = self._components.get(component_id)
        if comp is None:
            return False
        comp.data.update(data)
        comp.updated_at = datetime.now(timezone.utc).isoformat()
        self._version += 1
        self._notify("update", comp)
        return True

    def remove(self, component_id: str) -> bool:
        """Remove a component from the canvas."""
        if component_id in self._components:
            comp = self._components.pop(component_id)
            self._version += 1
            self._notify("remove", comp)
            return True
        return False

    def get(self, component_id: str) -> CanvasComponent | None:
        return self._components.get(component_id)

    def clear(self) -> None:
        """Remove all components."""
        self._components.clear()
        self._order_counter = 0
        self._version += 1
        self._notify("clear", None)

    # ── Convenience Builders ────────────────────────────────────────

    def add_markdown(self, content: str, title: str = "") -> CanvasComponent:
        return self.add(ComponentType.MARKDOWN, title, {"content": content})

    def add_table(
        self, headers: list[str], rows: list[list[str]], title: str = ""
    ) -> CanvasComponent:
        return self.add(ComponentType.TABLE, title, {"headers": headers, "rows": rows})

    def add_chart(
        self,
        chart_type: str,
        labels: list[str],
        datasets: list[dict[str, Any]],
        title: str = "",
    ) -> CanvasComponent:
        return self.add(
            ComponentType.CHART, title,
            {"chart_type": chart_type, "labels": labels, "datasets": datasets},
        )

    def add_code(self, code: str, language: str = "python", title: str = "") -> CanvasComponent:
        return self.add(ComponentType.CODE, title, {"code": code, "language": language})

    def add_metric(
        self, label: str, value: str, trend: str = "", icon: str = ""
    ) -> CanvasComponent:
        return self.add(
            ComponentType.METRIC, "",
            {"label": label, "value": value, "trend": trend, "icon": icon},
            width="quarter",
        )

    def add_progress(self, label: str, value: float, max_val: float = 1.0) -> CanvasComponent:
        return self.add(
            ComponentType.PROGRESS, "",
            {"label": label, "value": value, "max": max_val},
        )

    def add_terminal(self, output: str, title: str = "Terminal") -> CanvasComponent:
        return self.add(ComponentType.TERMINAL, title, {"output": output})

    def add_image(self, url: str, alt: str = "", title: str = "") -> CanvasComponent:
        return self.add(ComponentType.IMAGE, title, {"url": url, "alt": alt})

    # ── Serialization ───────────────────────────────────────────────

    def to_json(self) -> str:
        """Serialize canvas state as JSON for WebSocket push."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def to_dict(self) -> dict[str, Any]:
        components = sorted(self._components.values(), key=lambda c: c.order)
        return {
            "canvas_id": self._id,
            "version": self._version,
            "component_count": len(components),
            "components": [asdict(c) for c in components],
        }

    # ── Event System ────────────────────────────────────────────────

    def on_change(self, callback: Any) -> None:
        """Register a listener for canvas changes."""
        self._listeners.append(callback)

    def _notify(self, action: str, component: CanvasComponent | None) -> None:
        """Notify listeners of a canvas change."""
        for listener in self._listeners:
            try:
                listener(action, component, self._version)
            except Exception as exc:
                logger.debug("Canvas listener error: %s", exc)

    # ── Properties ──────────────────────────────────────────────────

    @property
    def component_count(self) -> int:
        return len(self._components)

    @property
    def version(self) -> int:
        return self._version

    @property
    def canvas_id(self) -> str:
        return self._id

    def list_components(self) -> list[CanvasComponent]:
        return sorted(self._components.values(), key=lambda c: c.order)


# ── Module singleton ────────────────────────────────────────────────

_CANVASES: dict[str, LiveCanvas] = {}


def get_canvas(canvas_id: str = "main") -> LiveCanvas:
    if canvas_id not in _CANVASES:
        _CANVASES[canvas_id] = LiveCanvas(canvas_id)
    return _CANVASES[canvas_id]
