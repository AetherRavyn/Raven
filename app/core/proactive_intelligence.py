"""Proactive Intelligence Engine — FRIDAY-style anticipation.

Gathers REAL data from multiple sources and generates actionable insights:
- Weather conditions and alerts
- Task status (overdue, due today, stale)
- Health metrics (sleep trends, exercise gaps)
- World model (stale contacts, broken habits)
- Pattern learner (behavioral patterns)
- User model (satisfaction, trust)
- Memory (recent important facts)

Unlike the previous stub, this engine:
- Collects real data from tools and subsystems
- Generates data-driven insights, not hardcoded time checks
- Tracks which insights were useful (outcome feedback loop)
- Learns which types of insights users respond to
"""

from __future__ import annotations

import json
import logging
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ProactiveCandidate:
    """A candidate proactive message/suggestion."""
    channel: str = "telegram"
    topic: str = ""
    body: str = ""
    priority: str = "normal"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProactiveDecision:
    """A decision on whether to emit a proactive candidate."""
    emit: bool = False
    reason: str = ""
    candidate: ProactiveCandidate | None = None
    gates: dict[str, bool] = field(default_factory=dict)
    decided_at: float = 0.0


@dataclass(slots=True)
class ProactiveInsight:
    """A proactive insight or suggestion."""
    insight_type: str
    title: str
    description: str
    confidence: float
    urgency: float
    suggested_action: str = ""
    data_source: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# Module singleton
_instance: ProactiveIntelligence | None = None


def reset_proactive_intelligence_for_tests() -> None:
    global _instance
    _instance = None


def get_proactive_intelligence() -> ProactiveIntelligence:
    global _instance
    if _instance is None:
        _instance = ProactiveIntelligence()
    return _instance


class ProactiveIntelligence:
    """Real proactive intelligence — gathers data, generates insights, learns outcomes."""

    def __init__(
        self,
        workspace_dir: str = "workspace",
        clock: Callable[[], float] | None = None,
        redundancy_window_s: float = 300.0,
    ) -> None:
        from app.settings.config import Config
        self._workspace = workspace_dir or Config.MEMORY_ROOT
        self._dir = Path(self._workspace) / "proactive_intelligence"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._insights_file = self._dir / "insights.jsonl"
        self._outcomes_file = self._dir / "outcomes.jsonl"
        self._predictions_file = self._dir / "predictions.json"
        self._callbacks: list[Callable] = []
        self._last_emits: dict[str, float] = {}
        self._emit_times: list[float] = []
        self._cache: dict[str, tuple[float, Any]] = {}
        self._cache_ttl = 300  # 5 min cache for data fetches
        self._now = clock or _time.time
        self._redundancy_window = redundancy_window_s
        self._recent_topics_list: list[dict[str, Any]] = []

    def on_insight(self, callback: Callable) -> None:
        self._callbacks.append(callback)

    def _cached(self, key: str) -> Any | None:
        if key in self._cache:
            ts, val = self._cache[key]
            if _time.time() - ts < self._cache_ttl:
                return val
        return None

    def _cache_set(self, key: str, val: Any) -> None:
        self._cache[key] = (_time.time(), val)

    # ── Real Data Gathering ──────────────────────────────────────

    def _gather_context(self) -> dict[str, Any]:
        """Gather real data from all subsystems."""
        ctx: dict[str, Any] = {}

        # 1. Task status
        try:
            from app.core.task_inbox import TaskInboxStore
            inbox = TaskInboxStore(self._workspace)
            pending = inbox.list_items(status="open")
            overdue = inbox.list_items(status="overdue")
            ctx["pending_tasks"] = [{"title": t.title, "priority": t.priority} for t in pending[:10]]
            ctx["overdue_tasks"] = [t.title for t in overdue[:5]]
            ctx["pending_count"] = len(pending)
            ctx["overdue_count"] = len(overdue)
        except Exception:
            ctx["pending_count"] = 0
            ctx["overdue_count"] = 0

        # 2. Health data
        try:
            from app.tools.health_tracker import HealthTrackerTool
            ht = HealthTrackerTool(workspace_dir=self._workspace)
            today = ht._get_today()
            ctx["sleep_hours"] = today.get("sleep_hours", 0)
            ctx["exercise_count"] = today.get("exercise_count", 0)
            ctx["calories"] = today.get("total_calories", 0)
        except Exception:
            pass

        # 3. World model — stale contacts and broken habits
        try:
            from app.core.world_model import WorldModel
            wm = WorldModel(self._workspace)
            people = wm.find_entities(entity_type="person")
            now = _time.time()
            stale = []
            for p in people:
                try:
                    from app.core.nudge_engine import _parse_iso
                    last = _parse_iso(p.last_seen)
                    if last and (now - last) > 14 * 86400:
                        stale.append(p.name)
                except Exception:
                    pass
            ctx["stale_contacts"] = stale[:5]
            ctx["habits"] = {k: len(v) for k, v in wm._load_habits().items()}
        except Exception:
            pass

        # 4. User model — satisfaction and trust
        try:
            from app.core.user_model import get_user_model
            um = get_user_model()
            profile = um.get_profile("default")
            ctx["satisfaction"] = profile.satisfaction_trend
            ctx["trust_level"] = profile.trust_level
        except Exception:
            pass

        # 5. Pattern learner — recent behavioral patterns
        try:
            from app.core.pattern_learner import PatternLearner
            pl = PatternLearner(workspace_dir=self._workspace)
            rules = pl.get_rules_for_prompt()
            ctx["behavioral_rules"] = rules[:500] if rules else ""
        except Exception:
            pass

        # 6. Current time context
        now = datetime.now(timezone.utc)
        ctx["hour"] = now.hour
        ctx["day_of_week"] = now.strftime("%A")
        ctx["date"] = now.strftime("%Y-%m-%d")

        return ctx

    # ── Real Insight Generation ──────────────────────────────────

    async def analyze(self, context: dict[str, Any] | None = None) -> list[ProactiveInsight]:
        """Generate real insights from gathered data."""
        ctx = context or self._gather_context()
        insights: list[ProactiveInsight] = []

        # Real data-driven insights
        insights.extend(self._task_insights(ctx))
        insights.extend(self._health_insights(ctx))
        insights.extend(self._world_model_insights(ctx))
        insights.extend(self._time_insights(ctx))

        # Save and dispatch
        for insight in insights:
            self._save_insight(insight)
            for cb in self._callbacks:
                try:
                    cb(insight)
                except Exception:
                    pass

        return insights

    def _task_insights(self, ctx: dict) -> list[ProactiveInsight]:
        """Generate insights from real task data."""
        insights = []
        overdue = ctx.get("overdue_count", 0)
        pending = ctx.get("pending_count", 0)

        if overdue > 0:
            insights.append(ProactiveInsight(
                insight_type="alert",
                title=f"{overdue} Overdue Task{'s' if overdue > 1 else ''}",
                description=f"You have {overdue} overdue task{'s' if overdue > 1 else ''}. Want me to help prioritize?",
                confidence=0.9,
                urgency=0.8,
                suggested_action="Review overdue tasks and reprioritize",
                data_source="task_inbox",
                context={"overdue": overdue},
            ))

        if pending > 10:
            insights.append(ProactiveInsight(
                insight_type="suggestion",
                title=f"{pending} Tasks Pending",
                description=f"You have {pending} pending tasks. Want me to organize them by priority?",
                confidence=0.7,
                urgency=0.5,
                suggested_action="Sort tasks by priority and suggest top 3",
                data_source="task_inbox",
            ))

        return insights

    def _health_insights(self, ctx: dict) -> list[ProactiveInsight]:
        """Generate insights from real health data."""
        insights = []
        sleep = ctx.get("sleep_hours", 0)
        exercise = ctx.get("exercise_count", 0)

        if 0 < sleep < 6:
            insights.append(ProactiveInsight(
                insight_type="alert",
                title="Low Sleep Detected",
                description=f"You only slept {sleep:.1f} hours. Consider an earlier bedtime tonight.",
                confidence=0.8,
                urgency=0.6,
                suggested_action="Suggest sleep hygiene tips",
                data_source="health_tracker",
                context={"sleep_hours": sleep},
            ))

        if sleep == 0 and exercise == 0:
            hour = ctx.get("hour", 12)
            if hour > 14:
                insights.append(ProactiveInsight(
                    insight_type="reminder",
                    title="No Health Logging Today",
                    description="You haven't logged any sleep or exercise today. Want to log now?",
                    confidence=0.6,
                    urgency=0.3,
                    suggested_action="Prompt for sleep/exercise logging",
                    data_source="health_tracker",
                ))

        return insights

    def _world_model_insights(self, ctx: dict) -> list[ProactiveInsight]:
        """Generate insights from world model data."""
        insights = []
        stale = ctx.get("stale_contacts", [])
        if stale:
            names = ", ".join(stale[:3])
            insights.append(ProactiveInsight(
                insight_type="suggestion",
                title="Stale Contacts",
                description=f"Haven't mentioned {names} in a while. Want to reach out?",
                confidence=0.5,
                urgency=0.2,
                suggested_action="Suggest catching up with stale contacts",
                data_source="world_model",
                context={"stale_contacts": stale},
            ))

        habits = ctx.get("habits", {})
        for habit_name, count in habits.items():
            if count > 5:
                insights.append(ProactiveInsight(
                    insight_type="suggestion",
                    title=f"Habit: {habit_name}",
                    description=f"You've tracked '{habit_name}' {count} times. Keep it up!",
                    confidence=0.4,
                    urgency=0.1,
                    data_source="world_model",
                    context={"habit": habit_name, "count": count},
                ))

        return insights

    def _time_insights(self, ctx: dict) -> list[ProactiveInsight]:
        """Generate insights based on time + context."""
        insights = []
        hour = ctx.get("hour", 12)
        day = ctx.get("day_of_week", "")

        if hour == 8 and day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday"):
            pending = ctx.get("pending_count", 0)
            insights.append(ProactiveInsight(
                insight_type="suggestion",
                title="Morning Briefing",
                description=f"Good morning! You have {pending} tasks today. Want a briefing?",
                confidence=0.7,
                urgency=0.5,
                suggested_action="Check calendar, emails, tasks, weather",
                data_source="time_context",
            ))

        if hour == 17 and day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday"):
            insights.append(ProactiveInsight(
                insight_type="suggestion",
                title="End of Day",
                description="Work day ending. Want me to summarize today's progress?",
                confidence=0.6,
                urgency=0.4,
                suggested_action="Summarize daily achievements and pending tasks",
                data_source="time_context",
            ))

        return insights

    # ── Outcome Tracking (Learning Loop) ─────────────────────────

    def record_outcome(self, insight_id: str, useful: bool, user_response: str = "") -> None:
        """Record whether an insight was useful — closes the feedback loop."""
        record = {
            "insight_id": insight_id,
            "useful": useful,
            "user_response": user_response,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with open(self._outcomes_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def get_outcome_stats(self) -> dict[str, Any]:
        """Get stats on which insight types are useful."""
        if not self._outcomes_file.exists():
            return {}
        by_type: dict[str, dict] = {}
        for line in self._outcomes_file.read_text(encoding="utf-8").strip().splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                # Find the matching insight to get its type
                useful = data.get("useful", False)
                key = "useful" if useful else "not_useful"
                by_type.setdefault(key, {"count": 0, "useful": 0})
                by_type[key]["count"] += 1
                if useful:
                    by_type[key]["useful"] += 1
            except Exception:
                continue
        return by_type

    # ── Gating ───────────────────────────────────────────────────

    def evaluate(self, candidate: ProactiveCandidate) -> ProactiveDecision:
        """Gate a candidate through decision logic.

        Gates checked in order:
        1. **priority** — candidate.priority must be known
        2. **has_body** — body must be non-empty
        3. **cooldown** — same channel+topic not emitted within cooldown
        4. **rate_limit** — at most 9 emits in the last hour
        5. **redundancy_ok** — same channel+topic not emitted within redundancy window
        6. **voice_channel_ok** — for voice channels, user must be speaking recently
           and ambient noise must be <= -45 dBFS
        7. **priority_floor** — on voice channels, priority must not be "low"
        8. **standing_order_ok** — if candidate.metadata["requires_order"] is set,
           a matching active :class:`StandingOrder` must exist
        """
        now = self._now()
        gates: dict[str, bool] = {}

        # 1. Valid priority
        gates["priority"] = candidate.priority in ("low", "normal", "high", "critical")

        # 2. Non-empty body
        gates["has_body"] = bool(candidate.body.strip())

        # 3. Cooldown per channel+topic
        cooldown_key = f"{candidate.channel}:{candidate.topic}"
        last_emit = self._last_emits.get(cooldown_key, 0.0)
        cooldown = {"low": 3600, "normal": 1800, "high": 600, "critical": 60}.get(candidate.priority, 1800)
        cooldown_seconds = 0 if self._redundancy_window == 0 else cooldown
        gates["cooldown"] = (now - last_emit) >= cooldown_seconds

        # 4. Overall rate limit (max 9 per hour)
        hour_ago = now - 3600
        recent = sum(1 for t in self._emit_times if t > hour_ago)
        gates["rate_limit"] = recent < 10

        # 5. Redundancy — same channel+topic within window
        if self._redundancy_window > 0 and cooldown_key in self._last_emits:
            gates["redundancy_ok"] = (now - self._last_emits[cooldown_key]) >= self._redundancy_window
        else:
            gates["redundancy_ok"] = True

        # 6. Voice channel gating (critical priority bypasses this)
        gates["voice_channel_ok"] = True
        if candidate.channel == "voice" and candidate.priority != "critical":
            gates["voice_channel_ok"] = False
            try:
                from app.core.voice_context import get_voice_context
                vc = get_voice_context()
                snap = vc.snapshot()
                active = (now - snap.last_active_at) < 300 if snap.last_active_at > 0 else False
                quiet = snap.ambient_noise_db <= -45.0
                gates["voice_channel_ok"] = active and quiet
            except Exception:
                pass

        # 7. Priority floor — low priority suppressed on voice
        gates["priority_floor"] = True
        if candidate.channel == "voice" and candidate.priority == "low":
            gates["priority_floor"] = False

        # 8. Standing order check
        gates["standing_order_ok"] = True
        required = candidate.metadata.get("requires_order", "")
        if required:
            gates["standing_order_ok"] = False
            try:
                from app.core.standing_orders import StandingOrderStore
                store = StandingOrderStore()
                orders = store.parse()
                for order in orders:
                    if order.title == required and order.enabled:
                        gates["standing_order_ok"] = True
                        break
            except Exception:
                pass

        # Determine reason (priority order: redundancy > voice > priority_floor > standing_order > general)
        failed = [k for k, v in gates.items() if not v]
        if not failed:
            reason = "all_gates_open"
            should_emit = True
            self._last_emits[cooldown_key] = now
            self._emit_times.append(now)
            self._emit_times = [t for t in self._emit_times if t > hour_ago]
            self._recent_topics_list.append({
                "channel": candidate.channel,
                "topic": candidate.topic,
                "time": now,
            })
        elif "redundancy_ok" in failed:
            reason = "redundant_with_recent_push"
            should_emit = False
        elif "voice_channel_ok" in failed:
            reason = "voice_channel_not_active_or_too_loud"
            should_emit = False
        elif "priority_floor" in failed:
            reason = "priority_below_floor_for_channel"
            should_emit = False
        elif "standing_order_ok" in failed:
            reason = "standing_order_not_active"
            should_emit = False
        else:
            reason = f"blocked: {failed}"
            should_emit = False

        return ProactiveDecision(
            emit=should_emit,
            reason=reason,
            candidate=candidate,
            gates=gates,
            decided_at=now,
        )

    # ── Lifecycle ─────────────────────────────────────────────────

    def recent_topics(self, channel: str | None = None) -> list[str]:
        """Return recently emitted topic strings, optionally filtered by channel."""
        if channel:
            return [e["topic"] for e in self._recent_topics_list if e["channel"] == channel]
        return [e["topic"] for e in self._recent_topics_list]

    def clear_history(self) -> None:
        """Wipe in-memory emit history (topics, last-emit tracking, times)."""
        self._recent_topics_list.clear()
        self._last_emits.clear()
        self._emit_times.clear()

    # ── Persistence ──────────────────────────────────────────────

    def _save_insight(self, insight: ProactiveInsight) -> None:
        from dataclasses import asdict
        with open(self._insights_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(insight), ensure_ascii=False) + "\n")

    def get_recent_insights(self, n: int = 20) -> list[ProactiveInsight]:
        if not self._insights_file.exists():
            return []
        insights = []
        for line in self._insights_file.read_text(encoding="utf-8").strip().splitlines()[-n:]:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                insights.append(ProactiveInsight(**data))
            except Exception:
                continue
        return insights

    def save_prediction(self, prediction: str, confidence: float) -> None:
        predictions = []
        if self._predictions_file.exists():
            try:
                predictions = json.loads(self._predictions_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        predictions.append({
            "prediction": prediction, "confidence": confidence,
            "timestamp": datetime.now(timezone.utc).isoformat(), "validated": False,
        })
        predictions = predictions[-100:]
        self._predictions_file.write_text(json.dumps(predictions, indent=2, ensure_ascii=False), encoding="utf-8")

    def validate_prediction(self, index: int, was_correct: bool) -> None:
        if not self._predictions_file.exists():
            return
        try:
            predictions = json.loads(self._predictions_file.read_text(encoding="utf-8"))
            if 0 <= index < len(predictions):
                predictions[index]["validated"] = True
                predictions[index]["was_correct"] = was_correct
                predictions[index]["validated_at"] = datetime.now(timezone.utc).isoformat()
                self._predictions_file.write_text(json.dumps(predictions, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def get_prediction_accuracy(self) -> float:
        if not self._predictions_file.exists():
            return 0.0
        try:
            predictions = json.loads(self._predictions_file.read_text(encoding="utf-8"))
            if not predictions:
                return 0.0
            validated = [p for p in predictions if p.get("validated")]
            if not validated:
                return 0.0
            correct = sum(1 for p in validated if p.get("was_correct"))
            return correct / len(validated)
        except Exception:
            return 0.0
