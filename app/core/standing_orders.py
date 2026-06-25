from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class StandingOrder:
    title: str
    rule: str
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class StandingOrderStore:
    """Loads persistent standing orders from workspace files."""

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config
        from app.settings.config import Config
        from app.settings.config import Config
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path(Config.MEMORY_ROOT) if workspace_dir else Path(Config.MEMORY_ROOT)
        self.orders_file = self.workspace_dir / "standing_orders.md"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def load_raw(self) -> str:
        if not self.orders_file.exists():
            return ""
        return self.orders_file.read_text(encoding="utf-8")

    def save_raw(self, content: str) -> None:
        self.orders_file.write_text(content, encoding="utf-8")

    def parse(self) -> list[StandingOrder]:
        raw = self.load_raw()
        orders: list[StandingOrder] = []
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("-"):
                stripped = stripped.lstrip("- ")
            if "|" in stripped:
                title, rule = [part.strip() for part in stripped.split("|", 1)]
            else:
                title = stripped
                rule = stripped
            if title:
                orders.append(StandingOrder(title=title, rule=rule))
        return orders

    def render(self, orders: list[StandingOrder]) -> str:
        lines = ["# Standing Orders", ""]
        for order in orders:
            prefix = "[on]" if order.enabled else "[off]"
            lines.append(f"- {prefix} {order.title} | {order.rule}")
        return "\n".join(lines).strip() + "\n"

    def deregister_reaction(self, title: str) -> bool:
        """Remove the standing-order line whose ``title`` matches ``title``.

        Scans the raw ``standing_orders.md`` for any non-comment line
        whose ``title`` field equals ``title`` (matching the same
        ``- [on] <title> | <rule>`` / ``- [off] <title> | <rule>``
        shape that :meth:`render` emits and that the modular
        platform's :class:`EventBridge._persist_reaction` writes)
        and removes it.  Empty / whitespace-only files are left
        untouched.

        Returns ``True`` when a line was removed and ``False`` when
        no matching line was found (idempotent: the caller's
        hot-unload path treats both as success).

        This is a best-effort text edit; a malformed line that
        does not contain a ``|`` separator is left in place so
        user-authored standing orders survive a faulty module
        unload.
        """
        raw = self.load_raw()
        if not raw.strip():
            return False
        kept: list[str] = []
        removed = False
        for line in raw.splitlines():
            stripped = line.strip()
            if (
                stripped
                and not stripped.startswith("#")
                and "|" in stripped
            ):
                head = stripped.lstrip("- ").strip()
                # Strip the leading [on]/[off] flag if present so
                # the title match is invariant to the enabled state.
                if head.startswith("[") and "]" in head:
                    head = head.split("]", 1)[1].strip()
                line_title, _sep, _rule = head.partition("|")
                if line_title.strip() == title:
                    removed = True
                    continue
            kept.append(line)
        if removed:
            self.save_raw("\n".join(kept).rstrip("\n") + "\n")
        return removed
