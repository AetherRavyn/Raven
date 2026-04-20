from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


@dataclass(slots=True)
class MonitoringEvent:
    event_id: str
    event_type: str
    camera_id: str
    timestamp: str
    risk_level: str = "low"
    zone_id: str | None = None
    source: str = "monitoring"
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    severity: str | None = None
    suspicion_score: float | None = None

    @classmethod
    def now(
        cls,
        *,
        event_id: str,
        event_type: str,
        camera_id: str,
        risk_level: str = "low",
        zone_id: str | None = None,
        source: str = "monitoring",
        description: str = "",
        metadata: dict[str, Any] | None = None,
        severity: str | None = None,
        suspicion_score: float | None = None,
    ) -> "MonitoringEvent":
        return cls(
            event_id=event_id,
            event_type=event_type,
            camera_id=camera_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            risk_level=risk_level,
            zone_id=zone_id,
            source=source,
            description=description,
            metadata=metadata or {},
            severity=severity,
            suspicion_score=suspicion_score,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
