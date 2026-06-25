"""System notifications and mute rules for the companion.

When the orchestrator pushes a high-priority event, the companion
shows a system notification (macOS Notification Center, Windows
toast, Linux libnotify, mobile push).  The actual delivery is left
to the native shell (Tauri / Capacitor), which calls into the
platform's notification API.  This module:

  * Decides whether a given event should produce a notification
    (priority + mute rules).
  * Builds a stable notification payload (title, body, channel,
    deep link) that the native shell can render as-is.
  * Falls back to a no-op dispatcher in tests / headless / when the
    native shell is missing.

Mute rules support:
  * Per-channel:    "mute:alerts"   → never notify on the ``alerts`` channel.
  * Per-intent:     "intent:send_email" → never notify when the
                    trigger event is for ``send_email``.
  * Per-weekday:    "weekday:sunday"  → never notify on Sundays.
  * Per-priority:   "priority:low"    → never notify low-priority events.

A rule is "match if attribute == value" — they AND together.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# Notification backend — a callable that accepts a
# ``NotificationPayload`` and returns nothing.  Real shells override
# this with a function that talks to the OS notification API.
NotificationSink = Callable[["NotificationPayload"], None]


@dataclass(slots=True)
class NotificationPayload:
    """A rendered notification ready for the OS."""

    title: str
    body: str
    channel: str
    priority: str
    event_id: str
    deep_link: str = ""
    timestamp_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "body": self.body,
            "channel": self.channel,
            "priority": self.priority,
            "event_id": self.event_id,
            "deep_link": self.deep_link,
            "timestamp_ms": self.timestamp_ms,
        }


@dataclass(slots=True)
class MuteRule:
    """A single rule.  All set fields must match for the rule to fire."""

    channel: str = ""
    intent: str = ""
    weekday: str = ""  # "monday" .. "sunday"
    priority: str = ""  # "low" | "normal" | "high"

    def matches(self, event: "NotificationPayload") -> bool:
        if self.channel and event.channel != self.channel:
            return False
        if self.intent:
            intent = event.deep_link.split(":", 1)[-1] if event.deep_link else ""
            if intent != self.intent:
                return False
        if self.weekday:
            wd = datetime.fromtimestamp(
                event.timestamp_ms / 1000, tz=timezone.utc
            ).strftime("%A").lower()
            if wd != self.weekday.lower():
                return False
        if self.priority and event.priority != self.priority:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "intent": self.intent,
            "weekday": self.weekday,
            "priority": self.priority,
        }


def parse_mute_rule(spec: str) -> MuteRule:
    """Parse "kind:value" notation, e.g. ``"weekday:sunday"``."""
    if ":" not in spec:
        raise ValueError(f"mute rule must be kind:value, got {spec!r}")
    kind, value = spec.split(":", 1)
    kind = kind.strip().lower()
    value = value.strip()
    if kind == "channel":
        return MuteRule(channel=value)
    if kind == "intent":
        return MuteRule(intent=value)
    if kind == "weekday":
        return MuteRule(weekday=value)
    if kind == "priority":
        return MuteRule(priority=value)
    raise ValueError(f"unknown mute rule kind: {kind!r}")


class NotificationDispatcher:
    """Build, mute, and deliver notifications.

    The dispatcher is the single entry point the WebSocket loop calls
    when an event arrives.  It:

      1. Builds a :class:`NotificationPayload` from the event.
      2. Checks the rule table — if any rule matches, drops it.
      3. Hands the payload to the configured sink.

    The default sink is a no-op (``None``) that just appends to a
    list the tests can inspect.  The native shell registers a real
    sink on startup.
    """

    def __init__(
        self,
        sink: NotificationSink | None = None,
        rules: list[MuteRule] | None = None,
        min_priority: str = "normal",
    ) -> None:
        self._sink = sink
        self._rules: list[MuteRule] = list(rules or [])
        self._min_priority = min_priority
        self._dropped: list[NotificationPayload] = []
        self._delivered: list[NotificationPayload] = []

    # ── configuration ────────────────────────────────────────────

    def set_sink(self, sink: NotificationSink) -> None:
        self._sink = sink

    def add_rule(self, rule: MuteRule) -> None:
        self._rules.append(rule)

    def add_rule_spec(self, spec: str) -> None:
        self._rules.append(parse_mute_rule(spec))

    def rules(self) -> list[MuteRule]:
        return list(self._rules)

    def clear_rules(self) -> None:
        self._rules.clear()

    def set_min_priority(self, priority: str) -> None:
        self._min_priority = priority

    # ── accessors (used by tests + UI) ────────────────────────────

    def dropped(self) -> list[NotificationPayload]:
        return list(self._dropped)

    def delivered(self) -> list[NotificationPayload]:
        return list(self._delivered)

    # ── dispatch ─────────────────────────────────────────────────

    def notify(
        self,
        *,
        title: str,
        body: str,
        channel: str,
        priority: str = "normal",
        event_id: str = "",
        deep_link: str = "",
    ) -> Optional[NotificationPayload]:
        """Build a payload, apply rules, and deliver (or drop)."""
        payload = NotificationPayload(
            title=title,
            body=body,
            channel=channel,
            priority=priority,
            event_id=event_id,
            deep_link=deep_link,
            timestamp_ms=int(time.time() * 1000),
        )
        if self._should_drop(payload):
            self._dropped.append(payload)
            return None
        if self._sink is not None:
            try:
                self._sink(payload)
            except Exception as e:  # noqa: BLE001
                logger.warning("notification sink failed: %s", e)
        self._delivered.append(payload)
        return payload

    def notify_event(self, event: dict[str, Any]) -> Optional[NotificationPayload]:
        """Render a wire event into a notification."""
        return self.notify(
            title=str(event.get("payload", {}).get("title", event.get("channel", "alert"))),
            body=str(event.get("payload", {}).get("body", "")),
            channel=str(event.get("channel", "")),
            priority=str(event.get("priority", "normal")),
            event_id=str(event.get("id", "")),
            deep_link=str(event.get("payload", {}).get("deep_link", "")),
        )

    # ── internals ────────────────────────────────────────────────

    def _should_drop(self, payload: NotificationPayload) -> bool:
        if not self._priority_meets_min(payload.priority):
            return True
        for rule in self._rules:
            if rule.matches(payload):
                return True
        return False

    def _priority_meets_min(self, priority: str) -> bool:
        order = {"low": 0, "normal": 1, "high": 2}
        return order.get(priority, 1) >= order.get(self._min_priority, 1)


__all__ = [
    "NotificationPayload",
    "NotificationSink",
    "MuteRule",
    "parse_mute_rule",
    "NotificationDispatcher",
]