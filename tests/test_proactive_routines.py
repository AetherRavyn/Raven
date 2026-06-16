"""Tests for the Phase C3 proactive routines library.

Three routines are covered:

* :func:`compose_evening_review` — end-of-day summary
* :func:`compose_weekly_digest`  — week-ahead preview
* :func:`compose_anomaly_digest`  — periodic anomaly check-in

The tests inject mocks for the optional data sources (task
ledger, commitment tracker, anomaly detector, anticipation
engine) so the routines can be exercised in isolation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.core.proactive_core import (
    AnomalyDetector,
    AnticipationEngine,
    FollowUpTracker,
    InMemoryObservationStore,
    ObservationKind,
    register_proactive_core,
    reset_registry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_anomaly_store() -> InMemoryObservationStore:
    store = InMemoryObservationStore()
    det = AnomalyDetector(store=store)
    for _ in range(5):
        det.observe("u1", ObservationKind.WORK_HOURS, 8.0)
    # Big spike → HIGH anomaly
    det.observe("u1", ObservationKind.WORK_HOURS, 20.0)
    return store


# ---------------------------------------------------------------------------
# Evening review
# ---------------------------------------------------------------------------


class TestEveningReview:
    @pytest.mark.asyncio
    async def test_compose_basic_shape(self) -> None:
        from app.routines.evening_review import compose_evening_review

        text = await compose_evening_review("u1")
        assert "End-of-day check-in" in text
        assert "open task" in text

    @pytest.mark.asyncio
    async def test_works_with_empty_ledger(self) -> None:
        from app.routines.evening_review import compose_evening_review

        # Bad factory → ledger throws → routine still produces text.
        def bad_ledger() -> Any:
            raise RuntimeError("boom")

        text = await compose_evening_review("u1", task_ledger_factory=bad_ledger)
        assert "End-of-day" in text

    @pytest.mark.asyncio
    async def test_legacy_path_uses_replytarget(self) -> None:
        # Pure smoke: exercise the function with a mock
        # task_ledger_factory that returns an empty ledger.
        from app.routines.evening_review import compose_evening_review

        class _StubLedger:
            def list_tasks(self, status: str | None = None) -> list[dict[str, Any]]:
                return []

        text = await compose_evening_review(
            "u1",
            task_ledger_factory=lambda: _StubLedger(),  # type: ignore[arg-type,return-value]
        )
        assert "0 open task" in text

    @pytest.mark.asyncio
    async def test_send_via_engine_returns_true_when_registered(self) -> None:
        from app.routines.evening_review import _send_via_engine

        class _StubBotSignal:
            def __init__(self) -> None:
                self.sent: list[Any] = []

            async def send(self, target: Any, payload: Any) -> None:
                self.sent.append((target, payload))

        reset_registry()
        bs = _StubBotSignal()
        register_proactive_core(
            botsignal=bs,  # type: ignore[arg-type]
            raw_users="telegram:u1:c1",  # type: ignore[arg-type]
        )
        try:
            handled = await _send_via_engine("u1", "telegram", "c1")
            assert handled is True
            # Routine text is non-empty.
            assert len(bs.sent) == 1
        finally:
            reset_registry()

    @pytest.mark.asyncio
    async def test_send_via_engine_returns_false_when_not_registered(self) -> None:
        from app.routines.evening_review import _send_via_engine

        reset_registry()
        handled = await _send_via_engine("ghost", "telegram", "c1")
        assert handled is False


# ---------------------------------------------------------------------------
# Weekly digest
# ---------------------------------------------------------------------------


class TestWeeklyDigest:
    @pytest.mark.asyncio
    async def test_compose_no_data(self) -> None:
        from app.routines.weekly_digest import compose_weekly_digest

        text = await compose_weekly_digest("u1")
        assert "Week ahead" in text
        # No commitments / anomalies / predictions means only
        # the header + open-task line.
        assert "Open tasks" in text

    @pytest.mark.asyncio
    async def test_compose_with_commitments(self) -> None:
        from app.routines.weekly_digest import compose_weekly_digest

        tracker = FollowUpTracker()
        now = datetime.now(timezone.utc)
        tracker.add_commitment("u1", "do thing", due_at=now + timedelta(days=2))
        text = await compose_weekly_digest("u1", commitment_tracker=tracker, now=now)
        assert "1 commitment" in text

    @pytest.mark.asyncio
    async def test_compose_with_anomalies(self) -> None:
        from app.routines.weekly_digest import compose_weekly_digest

        _seed_anomaly_store()
        det = AnomalyDetector()
        now = datetime.now(timezone.utc)
        text = await compose_weekly_digest("u1", anomaly_detector=det, now=now)
        # Anomalies were seeded so we should mention shifts.
        assert "pattern shift" in text

    @pytest.mark.asyncio
    async def test_compose_with_predictions(self) -> None:
        from app.core.proactive_core import HabitTracker
        from app.routines.weekly_digest import compose_weekly_digest

        h_tracker = HabitTracker()
        for _ in range(3):
            h_tracker.record_fire("u1", "check email")
        engine = AnticipationEngine(h_tracker)
        text = await compose_weekly_digest("u1", anticipation_engine=engine)
        assert "Predicted habits" in text
        assert "check email" in text

    @pytest.mark.asyncio
    async def test_send_via_engine_returns_true_when_registered(self) -> None:
        from app.routines.weekly_digest import _send_via_engine

        class _StubBotSignal:
            def __init__(self) -> None:
                self.sent: list[Any] = []

            async def send(self, target: Any, payload: Any) -> None:
                self.sent.append((target, payload))

        reset_registry()
        bs = _StubBotSignal()
        register_proactive_core(
            botsignal=bs,  # type: ignore[arg-type]
            raw_users="telegram:u1:c1",  # type: ignore[arg-type]
        )
        try:
            handled = await _send_via_engine("u1", "telegram", "c1")
            assert handled is True
            assert bs.sent
        finally:
            reset_registry()


# ---------------------------------------------------------------------------
# Anomaly digest
# ---------------------------------------------------------------------------


class TestAnomalyDigest:
    @pytest.mark.asyncio
    async def test_no_detector(self) -> None:
        from app.routines.anomaly_digest import compose_anomaly_digest

        text, anomalies = await compose_anomaly_digest("u1", detector=None)
        assert "No anomaly detector" in text
        assert anomalies == []

    @pytest.mark.asyncio
    async def test_empty_when_no_anomalies(self) -> None:
        from app.routines.anomaly_digest import compose_anomaly_digest

        det = AnomalyDetector()
        text, anomalies = await compose_anomaly_digest("u1", detector=det)
        assert "No anomalies" in text
        assert anomalies == []

    @pytest.mark.asyncio
    async def test_reports_anomalies(self) -> None:
        from app.routines.anomaly_digest import compose_anomaly_digest

        # Seed the store the detector will read from.
        store = _seed_anomaly_store()
        det = AnomalyDetector(store=store)
        text, anomalies = await compose_anomaly_digest(
            "u1", detector=det, window=timedelta(days=14)
        )
        assert anomalies, "expected anomalies from seeded store"
        assert "pattern shift" in text.lower()

    @pytest.mark.asyncio
    async def test_send_via_engine_returns_true_even_with_no_anomalies(self) -> None:
        from app.routines.anomaly_digest import _send_via_engine

        class _StubBotSignal:
            def __init__(self) -> None:
                self.sent: list[Any] = []

            async def send(self, target: Any, payload: Any) -> None:
                self.sent.append((target, payload))

        reset_registry()
        bs = _StubBotSignal()
        register_proactive_core(
            botsignal=bs,  # type: ignore[arg-type]
            raw_users="telegram:u1:c1",  # type: ignore[arg-type]
        )
        try:
            handled = await _send_via_engine("u1", "telegram", "c1")
            # Engine path is reachable (no detector on engine,
            # so no anomalies → nothing sent, but handled=True).
            assert handled is True
            assert bs.sent == []
        finally:
            reset_registry()

    @pytest.mark.asyncio
    async def test_send_via_engine_sends_anomalies(self) -> None:
        from app.routines.anomaly_digest import _send_via_engine

        class _StubBotSignal:
            def __init__(self) -> None:
                self.sent: list[Any] = []

            async def send(self, target: Any, payload: Any) -> None:
                self.sent.append((target, payload))

        reset_registry()
        bs = _StubBotSignal()
        register_proactive_core(
            botsignal=bs,  # type: ignore[arg-type]
            raw_users="telegram:u1:c1",  # type: ignore[arg-type]
        )
        try:
            ctx = __import__("app.core.proactive_core", fromlist=["get_context"]).get_context("u1")
            # Attach a detector with seeded data.
            ctx.engine.anomaly_detector = AnomalyDetector(_seed_anomaly_store())
            handled = await _send_via_engine("u1", "telegram", "c1")
            assert handled is True
            assert bs.sent
        finally:
            reset_registry()

    @pytest.mark.asyncio
    async def test_send_via_engine_no_context_returns_false(self) -> None:
        from app.routines.anomaly_digest import _send_via_engine

        reset_registry()
        handled = await _send_via_engine("ghost", "telegram", "c1")
        assert handled is False
