"""Tests for the Phase C2 Anticipation Engine modules.

Four modules are covered:

* :mod:`app.core.proactive_core.follow_up` — commitments tracker
* :mod:`app.core.proactive_core.anomaly`    — deviation detection
* :mod:`app.core.proactive_core.anticipation` — habit prediction
* :mod:`app.core.proactive_core.smart_nudges` — calendar/weather/email/task
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


from app.core.proactive_core import (
    AnticipationEngine,
    Anomaly,
    AnomalyDetector,
    AnomalySeverity,
    CalendarEvent,
    CommitmentKind,
    EmailSummary,
    FollowUpTracker,
    HabitTracker,
    InMemoryCommitmentStore,
    InMemoryObservationStore,
    ObservationKind,
    PatternKind,
    SignalKind,
    TaskSummary,
    Urgency,
    WeatherForecast,
    anomaly_to_signal,
    calendar_prep_signal,
    commitment_to_signal,
    email_urgent_signal,
    generate_signals,
    habit_to_signal,
    task_priority_signal,
    weather_signal,
)
from app.core.proactive_core.follow_up import (
    Commitment as FollowUpCommitment,
)
from app.core.proactive_core.follow_up import (
    CommitmentStatus as FollowUpStatus,
)


# ---------------------------------------------------------------------------
# follow_up
# ---------------------------------------------------------------------------


class TestFollowUp:
    def test_add_commitment_returns_record(self) -> None:
        t = FollowUpTracker()
        c = t.add_commitment("u1", "review the PR", due_at=datetime.now(timezone.utc))
        assert isinstance(c, FollowUpCommitment)
        assert c.status == FollowUpStatus.PENDING
        assert t.list_pending("u1") == [c]

    def test_mark_done(self) -> None:
        t = FollowUpTracker()
        c = t.add_commitment("u1", "x")
        assert t.mark_done(c.id) is True
        rec = t.store.get(c.id)
        assert rec is not None and rec.status == FollowUpStatus.DONE

    def test_mark_dropped(self) -> None:
        t = FollowUpTracker()
        c = t.add_commitment("u1", "x")
        assert t.mark_dropped(c.id) is True
        rec = t.store.get(c.id)
        assert rec is not None and rec.status == FollowUpStatus.DROPPED

    def test_snooze(self) -> None:
        t = FollowUpTracker()
        c = t.add_commitment("u1", "x")
        later = datetime.now(timezone.utc) + timedelta(hours=2)
        assert t.snooze(c.id, later) is True
        rec = t.store.get(c.id)
        assert rec is not None and rec.snoozed_until == later
        assert rec.status == FollowUpStatus.SNOOZED

    def test_list_due_soon(self) -> None:
        t = FollowUpTracker()
        now = datetime.now(timezone.utc)
        soon = t.add_commitment("u1", "soon", due_at=now + timedelta(minutes=2))
        later = t.add_commitment("u1", "later", due_at=now + timedelta(hours=2))
        result = t.list_due_soon("u1", lead_time_s=600.0, now=now)
        assert soon in result
        assert later not in result

    def test_list_overdue(self) -> None:
        t = FollowUpTracker()
        now = datetime.now(timezone.utc)
        past = t.add_commitment("u1", "old", due_at=now - timedelta(hours=1))
        future = t.add_commitment("u1", "new", due_at=now + timedelta(hours=1))
        result = t.list_overdue("u1", now=now)
        assert past in result
        assert future not in result

    def test_expire_overdue(self) -> None:
        t = FollowUpTracker()
        now = datetime.now(timezone.utc)
        ancient = t.add_commitment("u1", "ancient", due_at=now - timedelta(hours=2))
        result = t.expire_overdue("u1", grace_period_s=3600.0, now=now)
        assert ancient in result
        rec = t.store.get(ancient.id)
        assert rec is not None and rec.status == FollowUpStatus.EXPIRED

    def test_commitment_is_due_soon_respects_lead(self) -> None:
        now = datetime.now(timezone.utc)
        c = FollowUpCommitment(
            id="x",
            user_id="u1",
            kind=CommitmentKind.REMINDER,
            text="y",
            created_at=now,
            due_at=now + timedelta(minutes=3),
        )
        assert c.is_due_soon(600.0, now) is True
        assert c.is_due_soon(60.0, now) is False

    def test_store_dedup(self) -> None:
        store = InMemoryCommitmentStore()
        now = datetime.now(timezone.utc)
        c1 = FollowUpCommitment(
            id="same", user_id="u1", kind=CommitmentKind.REMINDER, text="x", created_at=now
        )
        c2 = FollowUpCommitment(
            id="same",
            user_id="u1",
            kind=CommitmentKind.REMINDER,
            text="x",
            created_at=now,
            status=FollowUpStatus.DONE,
        )
        store.add(c1)
        store.update(c2)
        rec = store.get("same")
        assert rec is not None and rec.status == FollowUpStatus.DONE

    def test_commitment_to_signal_overdue(self) -> None:
        now = datetime.now(timezone.utc)
        c = FollowUpCommitment(
            id="c1",
            user_id="u1",
            kind=CommitmentKind.PROMISE,
            text="do the thing",
            created_at=now - timedelta(hours=5),
            due_at=now - timedelta(hours=1),
        )
        s = commitment_to_signal(c)
        assert s is not None
        assert s.urgency == Urgency.HIGH
        assert s.kind == SignalKind.FOLLOW_UP

    def test_commitment_to_signal_done_returns_none(self) -> None:
        now = datetime.now(timezone.utc)
        c = FollowUpCommitment(
            id="c1",
            user_id="u1",
            kind=CommitmentKind.PROMISE,
            text="do the thing",
            created_at=now,
            status=FollowUpStatus.DONE,
        )
        assert commitment_to_signal(c) is None


# ---------------------------------------------------------------------------
# anomaly
# ---------------------------------------------------------------------------


class TestAnomaly:
    def test_observe_work_hours_triggers_when_50pct_above(self) -> None:
        store = InMemoryObservationStore()
        detector = AnomalyDetector(store=store)
        # Seed baseline
        for _ in range(5):
            detector.observe("u1", ObservationKind.WORK_HOURS, 8.0)
        # 2.5x spike → HIGH severity.
        result = detector.observe("u1", ObservationKind.WORK_HOURS, 20.0)
        assert len(result) == 1
        a = result[0]
        assert isinstance(a, Anomaly)
        assert a.severity == AnomalySeverity.HIGH
        assert "break" in a.message.lower()

    def test_observe_work_hours_no_anomaly_when_close(self) -> None:
        store = InMemoryObservationStore()
        detector = AnomalyDetector(store=store)
        for _ in range(5):
            detector.observe("u1", ObservationKind.WORK_HOURS, 8.0)
        result = detector.observe("u1", ObservationKind.WORK_HOURS, 8.5)
        assert result == []

    def test_email_latency_important_over_3_days(self) -> None:
        store = InMemoryObservationStore()
        detector = AnomalyDetector(store=store)
        # 4 days → LOW (<5)
        result = detector.observe(
            "u1",
            ObservationKind.EMAIL_REPLY_LATENCY_S,
            4 * 86400,
            important=True,
        )
        assert len(result) == 1
        assert result[0].severity == AnomalySeverity.LOW

    def test_email_latency_unimportant_is_silent(self) -> None:
        store = InMemoryObservationStore()
        detector = AnomalyDetector(store=store)
        result = detector.observe("u1", ObservationKind.EMAIL_REPLY_LATENCY_S, 10 * 86400)
        assert result == []

    def test_spending_spike_threshold(self) -> None:
        store = InMemoryObservationStore()
        detector = AnomalyDetector(store=store)
        # Need 3+ history points before the spike check fires.
        for v in (100, 110, 90):
            detector.observe("u1", ObservationKind.SPENDING_USD, v)
        # 1.75x → MEDIUM
        result = detector.observe("u1", ObservationKind.SPENDING_USD, 175)
        assert len(result) == 1
        assert result[0].severity == AnomalySeverity.MEDIUM

    def test_spending_no_anomaly_with_too_little_history(self) -> None:
        store = InMemoryObservationStore()
        detector = AnomalyDetector(store=store)
        detector.observe("u1", ObservationKind.SPENDING_USD, 100)
        result = detector.observe("u1", ObservationKind.SPENDING_USD, 500)
        assert result == []

    def test_anomaly_to_signal_uses_kind(self) -> None:
        a = Anomaly(
            id="anom-1",
            user_id="u1",
            kind=ObservationKind.WORK_HOURS,
            severity=AnomalySeverity.HIGH,
            message="x",
            observed_value=14,
            baseline=8,
            recorded_at=datetime.now(timezone.utc),
        )
        s = anomaly_to_signal(a)
        assert s.kind == SignalKind.ANOMALY
        assert s.urgency == Urgency.HIGH

    def test_detect_all_dedupes(self) -> None:
        store = InMemoryObservationStore()
        detector = AnomalyDetector(store=store)
        for _ in range(5):
            detector.observe("u1", ObservationKind.WORK_HOURS, 8.0)
        # Same spike, twice.
        detector.observe("u1", ObservationKind.WORK_HOURS, 14.0)
        detector.observe("u1", ObservationKind.WORK_HOURS, 14.0)
        result = detector.detect_all("u1", ObservationKind.WORK_HOURS)
        # Two observations, each producing one anomaly with the
        # same message → after dedup one remains.
        assert len(result) == 1


# ---------------------------------------------------------------------------
# anticipation
# ---------------------------------------------------------------------------


class TestAnticipation:
    def test_record_fire_increments_occurrences(self) -> None:
        tracker = HabitTracker()
        now = datetime.now(timezone.utc)
        h = tracker.record_fire("u1", "check email", now)
        assert h.occurrences == 1
        h = tracker.record_fire("u1", "check email", now)
        assert h.occurrences == 2

    def test_below_min_support_is_not_eligible(self) -> None:
        tracker = HabitTracker()
        tracker.record_fire("u1", "x")
        assert tracker.eligible("u1") == []

    def test_above_min_support_is_eligible(self) -> None:
        tracker = HabitTracker()
        for _ in range(3):
            tracker.record_fire("u1", "x")
        assert len(tracker.eligible("u1")) == 1

    def test_trigger_time_averaged(self) -> None:
        tracker = HabitTracker()
        # 3 fires at 8:00, 9:00, 10:00 → average 9:00.
        base = datetime(2024, 6, 12, 8, 0, tzinfo=timezone.utc)
        for i in range(3):
            tracker.record_fire("u1", "x", base.replace(hour=8 + i))
        h = tracker.eligible("u1")[0]
        assert h.trigger_hour == 9
        assert h.trigger_minute == 0

    def test_predict_for_user_returns_today_or_tomorrow(self) -> None:
        tracker = HabitTracker()
        # 3 fires at 9:00
        for _ in range(3):
            tracker.record_fire("u1", "x", datetime(2024, 6, 10, 9, 0, tzinfo=timezone.utc))
        engine = AnticipationEngine(tracker)
        now = datetime(2024, 6, 12, 6, 0, tzinfo=timezone.utc)
        preds = engine.predict_for_user("u1", now)
        assert len(preds) == 1
        # Predicted for 9:00 today.
        assert preds[0].predicted_for.hour == 9
        assert preds[0].confidence > 0.5

    def test_habit_to_signal(self) -> None:
        from app.core.proactive_core.anticipation import Habit

        h = Habit(
            id="hab-1",
            user_id="u1",
            name="check email",
            kind=PatternKind.TIME_OF_DAY,
            occurrences=5,
        )
        s = habit_to_signal(h, datetime.now(timezone.utc))
        assert s.kind == SignalKind.FORECAST
        assert "check email" in s.body

    def test_generate_signals_combines_sources(self) -> None:
        tracker = HabitTracker()
        for _ in range(3):
            tracker.record_fire(
                "u1",
                "check email",
                datetime(2024, 6, 12, 9, 0, tzinfo=timezone.utc),
            )
        engine = AnticipationEngine(tracker)
        follow_up = FollowUpTracker()
        now = datetime(2024, 6, 12, 8, 58, tzinfo=timezone.utc)
        follow_up.add_commitment("u1", "review PR", due_at=now + timedelta(minutes=5))
        signals = generate_signals(
            user_id="u1",
            follow_up=follow_up,
            anomalies=[],
            anticipation=engine,
            now=now,
        )
        # We should get at least the commitment and the forecast.
        kinds = {s.kind for s in signals}
        assert SignalKind.FOLLOW_UP in kinds
        assert SignalKind.FORECAST in kinds

    def test_generate_signals_dedupes(self) -> None:
        # Two identical anomalies with the same id → only one signal.
        tracker = HabitTracker()
        engine = AnticipationEngine(tracker)
        from app.core.proactive_core.anomaly import Anomaly, ObservationKind

        a = Anomaly(
            id="anom-dup",
            user_id="u1",
            kind=ObservationKind.WORK_HOURS,
            severity=AnomalySeverity.LOW,
            message="x",
            observed_value=10,
            baseline=8,
            recorded_at=datetime.now(timezone.utc),
        )
        result = generate_signals(
            user_id="u1",
            follow_up=FollowUpTracker(),
            anomalies=[a, a],
            anticipation=engine,
            now=datetime.now(timezone.utc),
        )
        ids = [s.id for s in result]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# smart_nudges
# ---------------------------------------------------------------------------


class TestSmartNudges:
    def test_calendar_prep_fires_in_window(self) -> None:
        event = CalendarEvent(
            id="evt-1",
            title="Design review",
            starts_at=datetime.now(timezone.utc) + timedelta(minutes=3),
            location="Room 42",
            attendees=["alice", "bob"],
        )
        s = calendar_prep_signal("u1", event)
        assert s is not None
        assert s.kind == SignalKind.CALENDAR_PREP
        assert "Design review" in s.body

    def test_calendar_prep_silent_outside_window(self) -> None:
        event = CalendarEvent(
            id="evt-1",
            title="Far away",
            starts_at=datetime.now(timezone.utc) + timedelta(hours=4),
        )
        assert calendar_prep_signal("u1", event) is None

    def test_calendar_prep_silent_for_past_event(self) -> None:
        event = CalendarEvent(
            id="evt-1",
            title="Old",
            starts_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        assert calendar_prep_signal("u1", event) is None

    def test_weather_signal_rain(self) -> None:
        f = WeatherForecast(
            summary="Heavy rain",
            temperature_c=12.0,
            precipitation_chance=0.8,
            commute_impact_min=15,
        )
        s = weather_signal("u1", f)
        assert s is not None
        assert "rain" in s.body.lower() or "leave" in s.body.lower()

    def test_weather_signal_clear_stays_silent(self) -> None:
        f = WeatherForecast(
            summary="Sunny",
            temperature_c=22.0,
            precipitation_chance=0.05,
            commute_impact_min=0,
        )
        assert weather_signal("u1", f) is None

    def test_weather_signal_extreme_cold(self) -> None:
        f = WeatherForecast(
            summary="Cold",
            temperature_c=-5.0,
            precipitation_chance=0.0,
            commute_impact_min=0,
        )
        s = weather_signal("u1", f)
        assert s is not None

    def test_task_priority_overdue(self) -> None:
        t = TaskSummary(
            id="t1",
            title="Old thing",
            due_at=datetime.now(timezone.utc) - timedelta(hours=1),
            priority="normal",
            is_overdue=True,
        )
        s = task_priority_signal("u1", t)
        assert s is not None
        assert s.urgency == Urgency.HIGH

    def test_task_priority_stale(self) -> None:
        t = TaskSummary(
            id="t1",
            title="Old",
            due_at=None,
            priority="normal",
            age_days=10,
        )
        s = task_priority_signal("u1", t)
        assert s is not None
        assert s.urgency == Urgency.LOW

    def test_task_priority_fresh_low_silent(self) -> None:
        t = TaskSummary(
            id="t1",
            title="New",
            due_at=None,
            priority="low",
            age_days=1,
        )
        assert task_priority_signal("u1", t) is None

    def test_email_urgent_fresh_important(self) -> None:
        e = EmailSummary(
            id="e1",
            subject="URGENT",
            sender="boss",
            is_important=True,
            age_hours=1,
        )
        s = email_urgent_signal("u1", e)
        assert s is not None
        assert s.urgency == Urgency.HIGH

    def test_email_unimportant_silent(self) -> None:
        e = EmailSummary(
            id="e1",
            subject="x",
            sender="y",
            is_important=False,
            age_hours=1,
        )
        assert email_urgent_signal("u1", e) is None

    def test_email_old_important_silent(self) -> None:
        # Older important emails are handled by the anomaly
        # detector, not the smart nudge.
        e = EmailSummary(
            id="e1",
            subject="x",
            sender="y",
            is_important=True,
            age_hours=48,
        )
        assert email_urgent_signal("u1", e) is None
