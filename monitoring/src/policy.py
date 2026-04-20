from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ZonePolicy:
    zone_id: str
    cameras: list[str] = field(default_factory=list)
    allowed_event_types: list[str] = field(default_factory=list)
    risk_multiplier: float = 1.0
    min_severity: str = "LOW"
    note: str = ""


class MonitoringPolicyEngine:
    """Very small per-zone policy engine for monitoring events."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        config = config or {}
        self.zone_policies: dict[str, ZonePolicy] = {}
        for zone_id, raw in (config.get("zones") or {}).items():
            self.zone_policies[zone_id] = ZonePolicy(
                zone_id=zone_id,
                cameras=list(raw.get("cameras", []) or []),
                allowed_event_types=list(raw.get("allowed_event_types", []) or []),
                risk_multiplier=float(raw.get("risk_multiplier", 1.0)),
                min_severity=str(raw.get("min_severity", "LOW")).upper(),
                note=str(raw.get("note", "")),
            )

    @staticmethod
    def _severity_rank(severity: str | None) -> int:
        order = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
        return order.get(str(severity or "LOW").upper(), 1)

    def apply(self, event: dict[str, Any]) -> dict[str, Any]:
        zone_id = event.get("zone_id")
        if not zone_id or zone_id not in self.zone_policies:
            return event

        policy = self.zone_policies[zone_id]
        out = dict(event)
        event_type = str(out.get("event_type") or out.get("anomaly_type") or "").lower()
        severity = str(out.get("severity") or out.get("risk_level") or "LOW").upper()

        if (
            policy.allowed_event_types
            and event_type
            and event_type not in policy.allowed_event_types
        ):
            out["suppressed"] = True
            out["policy_reason"] = (
                f"event_type {event_type} not allowed in zone {zone_id}"
            )
            return out

        multiplier = policy.risk_multiplier
        score = out.get("suspicion_score")
        if isinstance(score, (int, float)):
            out["suspicion_score"] = min(1.0, max(0.0, float(score) * multiplier))

        if self._severity_rank(severity) < self._severity_rank(policy.min_severity):
            out["suppressed"] = True
            out["policy_reason"] = (
                f"severity {severity} below minimum {policy.min_severity}"
            )

        out["policy_zone"] = zone_id
        out["policy_note"] = policy.note
        return out
