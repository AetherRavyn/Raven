# app/core/sentinel_bridge.py
"""Bridge between HomeSentinel monitoring system and RAVEN core.

Subscribes to HomeSentinel's Redis-backed MessageBus and translates
security/monitoring events into RAVEN IncomingRequests or direct
user notifications.

Architecture:
    HomeSentinel (camera/sensors) → Redis pub/sub → SentinelBridge → RAVEN Orchestrator
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict

logger = logging.getLogger(__name__)

# ── Severity thresholds ────────────────────────────────────────────────
SEVERITY_LEVELS = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
IMMEDIATE_NOTIFY_THRESHOLD = 2  # HIGH and above get instant notification
DIGEST_BATCH_SIZE = 10
DIGEST_INTERVAL_SECONDS = 300  # 5 minutes


class SentinelEvent:
    """Normalized event from HomeSentinel."""

    __slots__ = (
        "event_type",
        "severity",
        "source",
        "message",
        "timestamp",
        "metadata",
        "raw",
    )

    def __init__(
        self,
        event_type: str,
        severity: str = "LOW",
        source: str = "sentinel",
        message: str = "",
        metadata: Dict[str, Any] | None = None,
        raw: Dict[str, Any] | None = None,
    ) -> None:
        self.event_type = event_type
        self.severity = severity.upper()
        self.source = source
        self.message = message
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.metadata = metadata or {}
        self.raw = raw or {}

    @property
    def severity_level(self) -> int:
        return SEVERITY_LEVELS.get(self.severity, 0)

    @property
    def is_critical(self) -> bool:
        return self.severity_level >= IMMEDIATE_NOTIFY_THRESHOLD

    def to_alert_text(self) -> str:
        """Format as a user-readable alert."""
        icon = {
            "CRITICAL": "🚨",
            "HIGH": "⚠️",
            "MEDIUM": "📋",
            "LOW": "ℹ️",
        }.get(self.severity, "📋")
        return (
            f"{icon} **[{self.severity}] {self.event_type}**\n"
            f"{self.message}\n"
            f"Source: {self.source} | {self.timestamp}"
        )


class SentinelBridge:
    """
    Bridges HomeSentinel events to RAVEN.

    - Critical/High events → immediate notification to all registered platforms
    - Low/Medium events → batched into periodic digest
    - All events → logged to workspace/sentinel_events.jsonl for history
    """

    def __init__(
        self,
        botsignal=None,
        orchestrator=None,
        workspace_dir: str = "workspace/memory",
    ) -> None:
        self._botsignal = botsignal
        self._orchestrator = orchestrator
        self._workspace_dir = workspace_dir

        # Digest buffer for low-priority events
        self._digest_buffer: Deque[SentinelEvent] = deque(maxlen=100)

        # Notification targets: list of (platform, chat_id) tuples
        self._notify_targets: list[tuple[str, str]] = []

        # Event log file
        self._event_log_path = f"{workspace_dir}/sentinel_events.jsonl"

        # Event bus (in-process)
        self._message_bus = None
        self._running = False

    def add_notify_target(self, platform: str, chat_id: str) -> None:
        """Register a platform/chat for receiving security alerts."""
        self._notify_targets.append((platform, chat_id))

    def start(self, redis_url: str | None = None) -> None:
        """Start listening to HomeSentinel events.

        Operates in passive mode — accepts direct event injection
        via inject_event() and inject_detection(). Redis pub/sub
        integration is handled by the monitoring subsystem if available.
        """
        self._running = True
        logger.info("SentinelBridge started in passive mode")

    def stop(self) -> None:
        """Stop listening."""
        self._running = False
        if self._message_bus:
            try:
                self._message_bus.stop()
            except Exception:
                pass

    # ── Redis Callbacks ────────────────────────────────────────────────

    def _on_sentinel_event(self, payload: Dict[str, Any]) -> None:
        """Handle raw events from HomeSentinel 'events' channel."""
        try:
            event = SentinelEvent(
                event_type=payload.get("type", payload.get("event_type", "unknown")),
                severity=payload.get("severity", payload.get("level", "LOW")),
                source=payload.get("source", payload.get("camera_id", "sentinel")),
                message=payload.get("message", payload.get("description", "")),
                metadata=payload.get("metadata", {}),
                raw=payload,
            )
            self._process_event(event)
        except Exception as exc:
            logger.error("SentinelBridge: error processing event — %s", exc)

    def _on_detection_event(self, payload: Dict[str, Any]) -> None:
        """Handle YOLO/ReID detection events from 'detections' channel."""
        try:
            # Detection events are typically person/vehicle sightings
            objects = payload.get("objects", [])
            camera = payload.get("camera_id", "unknown")
            suspicion = payload.get("suspicion_score", 0.0)

            severity = "LOW"
            if suspicion > 0.7:
                severity = "HIGH"
            elif suspicion > 0.4:
                severity = "MEDIUM"

            obj_summary = ", ".join(
                f"{o.get('label', 'object')} ({o.get('confidence', 0):.0%})"
                for o in objects[:5]
            )

            event = SentinelEvent(
                event_type="detection",
                severity=severity,
                source=f"camera:{camera}",
                message=f"Detected: {obj_summary}. Suspicion: {suspicion:.0%}",
                metadata={"objects": objects, "suspicion_score": suspicion},
                raw=payload,
            )
            self._process_event(event)
        except Exception as exc:
            logger.error("SentinelBridge: error processing detection — %s", exc)

    # ── Event Processing ───────────────────────────────────────────────

    def _process_event(self, event: SentinelEvent) -> None:
        """Route event based on severity."""
        # Always log
        self._log_event(event)

        if event.is_critical:
            # Immediate notification
            self._notify_immediate(event)
        else:
            # Buffer for digest
            self._digest_buffer.append(event)

    def _log_event(self, event: SentinelEvent) -> None:
        """Append event to JSONL log file."""
        try:
            entry = {
                "type": event.event_type,
                "severity": event.severity,
                "source": event.source,
                "message": event.message,
                "timestamp": event.timestamp,
                "metadata": event.metadata,
            }
            with open(self._event_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as exc:
            logger.debug("SentinelBridge: event log write failed — %s", exc)

    def _notify_immediate(self, event: SentinelEvent) -> None:
        """Send immediate alert to all registered platforms."""
        if not self._botsignal or not self._notify_targets:
            logger.warning(
                "SentinelBridge: critical event but no notification targets: %s",
                event.message,
            )
            return

        alert_text = event.to_alert_text()

        # We're called from a sync Redis callback thread — schedule async send
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                for platform, chat_id in self._notify_targets:
                    asyncio.run_coroutine_threadsafe(
                        self._send_alert(platform, chat_id, alert_text), loop
                    )
            else:
                logger.warning(
                    "SentinelBridge: no running event loop for async notification"
                )
        except Exception as exc:
            logger.error("SentinelBridge: failed to schedule notification — %s", exc)

    async def _send_alert(self, platform: str, chat_id: str, text: str) -> None:
        """Send alert via BotSignal."""
        from app.core.models import ReplyTarget, SignalPayload

        try:
            target = ReplyTarget(platform=platform, chat_id=chat_id)
            payload = SignalPayload(text=text, source_kind="sentinel_alert")
            await self._botsignal.send(target, payload)
            logger.info("SentinelBridge: alert sent to %s:%s", platform, chat_id)
        except Exception as exc:
            logger.error("SentinelBridge: failed to send alert — %s", exc)

    # ── Digest ─────────────────────────────────────────────────────────

    async def flush_digest(self) -> str | None:
        """Compile buffered low-priority events into a digest message. Returns the digest text."""
        if not self._digest_buffer:
            return None

        events = list(self._digest_buffer)
        self._digest_buffer.clear()

        lines = [f"📊 **Sentinel Digest** ({len(events)} events)\n"]

        # Group by type
        by_type: Dict[str, list] = {}
        for ev in events:
            by_type.setdefault(ev.event_type, []).append(ev)

        for event_type, group in by_type.items():
            lines.append(f"**{event_type}** ({len(group)}x)")
            for ev in group[:3]:  # Show first 3
                lines.append(f"  • {ev.message[:100]}")
            if len(group) > 3:
                lines.append(f"  ... and {len(group) - 3} more")

        digest_text = "\n".join(lines)

        # Send digest to all targets
        if self._botsignal and self._notify_targets:
            for platform, chat_id in self._notify_targets:
                await self._send_alert(platform, chat_id, digest_text)

        return digest_text

    # ── Direct Event Injection (for non-Redis setups) ──────────────────

    def inject_event(
        self,
        event_type: str,
        message: str,
        severity: str = "LOW",
        source: str = "manual",
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        """Manually inject an event (useful for MQTT or direct sensor input)."""
        event = SentinelEvent(
            event_type=event_type,
            severity=severity,
            source=source,
            message=message,
            metadata=metadata,
        )
        self._process_event(event)


# ── Module-level singleton ─────────────────────────────────────────────

_BRIDGE: SentinelBridge | None = None


def get_sentinel_bridge() -> SentinelBridge:
    global _BRIDGE
    if _BRIDGE is None:
        _BRIDGE = SentinelBridge()
    return _BRIDGE
