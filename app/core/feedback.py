from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FeedbackEvent:
    user_id: str
    item_type: str
    item_id: str
    reward: float
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class FeedbackStore:
    """Persistent feedback/reward store for routing and memory improvements."""

    def __init__(self, workspace_dir: str | None = None) -> None:
        from app.settings.config import Config
        from app.settings.config import Config
        from app.settings.config import Config
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path(Config.MEMORY_ROOT) if workspace_dir else Path(Config.MEMORY_ROOT)
        self.feedback_file = self.workspace_dir / "feedback.jsonl"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def add_feedback(
        self,
        user_id: str,
        item_type: str,
        item_id: str,
        reward: float,
        *,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> FeedbackEvent:
        event = FeedbackEvent(
            user_id=user_id,
            item_type=item_type,
            item_id=item_id,
            reward=reward,
            reason=reason,
            metadata=metadata or {},
        )
        with self.feedback_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(event), ensure_ascii=True) + "\n")
        return event

    def list_feedback(self, user_id: str | None = None) -> list[dict[str, Any]]:
        if not self.feedback_file.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in self.feedback_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            if user_id and raw.get("user_id") != user_id:
                continue
            events.append(raw)
        return events

    def score(self, item_type: str, item_id: str, user_id: str | None = None) -> float:
        rewards = [
            float(event.get("reward", 0.0))
            for event in self.list_feedback(user_id=user_id)
            if event.get("item_type") == item_type and event.get("item_id") == item_id
        ]
        if not rewards:
            return 0.0
        return sum(rewards) / len(rewards)

    def summary(self, user_id: str | None = None) -> dict[str, Any]:
        events = self.list_feedback(user_id=user_id)
        if not events:
            return {"count": 0, "average_reward": 0.0, "positive": 0, "negative": 0}
        rewards = [float(event.get("reward", 0.0)) for event in events]
        return {
            "count": len(events),
            "average_reward": round(sum(rewards) / len(rewards), 3),
            "positive": sum(1 for r in rewards if r > 0),
            "negative": sum(1 for r in rewards if r < 0),
        }
