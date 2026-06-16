"""Tests for the travel_prep + inbox_zero routines (Day 14, Phase C3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest


# -------------------------------------------------------------------
# travel_prep
# -------------------------------------------------------------------


def _make_event(title: str = "Client meeting", in_minutes: int = 60) -> Any:
    """Build a minimal CalendarEvent-like object."""
    from app.core.proactive_core.smart_nudges import CalendarEvent

    return CalendarEvent(
        id=f"evt_{title.lower().replace(' ', '_')}",
        title=title,
        starts_at=datetime.now(timezone.utc) + timedelta(minutes=in_minutes),
        location="",
        attendees=[],
    )


def _make_forecast(summary: str = "Sunny", rain_pct: int = 5) -> Any:
    from app.core.proactive_core.smart_nudges import WeatherForecast

    return WeatherForecast(
        summary=summary,
        temperature_c=20.0,
        precipitation_chance=rain_pct,
        commute_impact_min=0,
    )


def _make_plan(trip_minutes: int = 0) -> Any:
    from app.routines.travel_prep import TravelPlan

    return TravelPlan(
        event=_make_event(),
        home_location="Home",
        destination_location="Office",
        forecast=_make_forecast(),
        trip_minutes=trip_minutes,
    )


class TestTravelPlan:
    def test_plan_defaults_trip_minutes_to_zero(self) -> None:
        plan = _make_plan()
        assert plan.trip_minutes == 0

    def test_plan_carries_forecast(self) -> None:
        plan = _make_plan()
        assert plan.forecast.summary == "Sunny"


class TestComposeTravelPrep:
    @pytest.mark.asyncio
    async def test_basic_text_includes_title_and_destination(self) -> None:
        from app.routines.travel_prep import compose_travel_prep

        text, _ = await compose_travel_prep("u1", _make_plan())
        assert "Client meeting" in text
        assert "Office" in text

    @pytest.mark.asyncio
    async def test_trip_minutes_zero_omits_leave_by(self) -> None:
        from app.routines.travel_prep import compose_travel_prep

        text, _ = await compose_travel_prep("u1", _make_plan(trip_minutes=0))
        assert "leave by:" not in text

    @pytest.mark.asyncio
    async def test_trip_minutes_positive_includes_leave_by(self) -> None:
        from app.routines.travel_prep import compose_travel_prep

        text, _ = await compose_travel_prep("u1", _make_plan(trip_minutes=30))
        assert "leave by:" in text

    @pytest.mark.asyncio
    async def test_event_starts_in_past_warns(self) -> None:
        from app.routines.travel_prep import compose_travel_prep
        from app.core.proactive_core.smart_nudges import CalendarEvent

        past_event = CalendarEvent(
            id="evt_past",
            title="Old meeting",
            starts_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            location="",
            attendees=[],
        )
        plan = _make_plan(trip_minutes=30)
        plan = plan.__class__(
            event=past_event,
            home_location=plan.home_location,
            destination_location=plan.destination_location,
            forecast=plan.forecast,
            trip_minutes=30,
        )
        text, _ = await compose_travel_prep("u1", plan)
        assert "rescheduling" in text

    @pytest.mark.asyncio
    async def test_returns_tuple_with_forecast(self) -> None:
        from app.routines.travel_prep import compose_travel_prep

        text, forecast = await compose_travel_prep("u1", _make_plan())
        assert forecast is not None
        assert forecast.summary == "Sunny"


class TestSendTravelPrep:
    @pytest.mark.asyncio
    async def test_no_context_returns_false(self, monkeypatch: Any) -> None:
        from app.routines.travel_prep import send_travel_prep
        from app.core.proactive_core import reset_registry

        reset_registry()
        result = await send_travel_prep("u1", _make_plan())
        assert result is False


# -------------------------------------------------------------------
# inbox_zero
# -------------------------------------------------------------------


def _make_msg(
    sender: str = "Alice <alice@example.com>",
    subject: str = "Hello",
    hours_ago: float = 1.0,
    important: bool = False,
    unread: bool = True,
    tags: tuple[str, ...] = (),
) -> Any:
    from app.routines.inbox_zero import InboxMessage

    return InboxMessage(
        id=f"msg_{hash((sender, subject)) & 0xFFFF:04x}",
        sender=sender,
        subject=subject,
        received_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        important=important,
        unread=unread,
        tags=tags,
    )


class TestInboxMessage:
    def test_sender_domain_with_angle_addr(self) -> None:
        msg = _make_msg(sender="Bob <bob@corp.io>")
        assert msg.sender_domain == "corp.io"

    def test_sender_domain_with_bare_address(self) -> None:
        msg = _make_msg(sender="charlie@personal.com")
        assert msg.sender_domain == "personal.com"

    def test_sender_domain_with_display_only(self) -> None:
        msg = _make_msg(sender="Digest")
        assert msg.sender_domain == "digest"


class TestComposeInboxDigest:
    def test_empty_messages_returns_zero_digest(self) -> None:
        from app.routines.inbox_zero import compose_inbox_digest

        digest = compose_inbox_digest([])
        assert digest.total == 0
        assert digest.needs_reply == ()
        assert digest.important == ()

    def test_total_counts_all_messages(self) -> None:
        from app.routines.inbox_zero import compose_inbox_digest

        msgs = [_make_msg() for _ in range(3)]
        digest = compose_inbox_digest(msgs)
        assert digest.total == 3

    def test_needs_reply_sorted_by_received(self) -> None:
        from app.routines.inbox_zero import compose_inbox_digest

        older = _make_msg(subject="Older", hours_ago=5, tags=("needs_reply",))
        newer = _make_msg(subject="Newer", hours_ago=1, tags=("needs_reply",))
        digest = compose_inbox_digest([older, newer])
        assert [m.subject for m in digest.needs_reply] == ["Older", "Newer"]

    def test_important_counted_separately(self) -> None:
        from app.routines.inbox_zero import compose_inbox_digest

        msgs = [
            _make_msg(important=True, tags=("needs_reply",)),
            _make_msg(important=True, tags=()),
            _make_msg(important=False),
        ]
        digest = compose_inbox_digest(msgs)
        assert len(digest.needs_reply) == 1
        assert len(digest.important) == 1

    def test_domain_breakdown(self) -> None:
        from app.routines.inbox_zero import compose_inbox_digest

        msgs = [
            _make_msg(sender="a@x.com"),
            _make_msg(sender="b@x.com"),
            _make_msg(sender="c@y.com"),
        ]
        digest = compose_inbox_digest(msgs)
        assert digest.by_domain == {"x.com": 2, "y.com": 1}

    def test_text_mentions_top_senders(self) -> None:
        from app.routines.inbox_zero import compose_inbox_digest

        msgs = [_make_msg(sender=f"u{i}@x.com") for i in range(5)]
        msgs += [_make_msg(sender="other@y.com")]
        digest = compose_inbox_digest(msgs)
        assert "x.com=5" in digest.text

    def test_text_includes_needs_reply_section(self) -> None:
        from app.routines.inbox_zero import compose_inbox_digest

        msgs = [_make_msg(tags=("needs_reply",), subject="URGENT")]
        digest = compose_inbox_digest(msgs)
        assert "Reply queue:" in digest.text
        assert "URGENT" in digest.text

    def test_top_n_limits_queues(self) -> None:
        from app.routines.inbox_zero import compose_inbox_digest

        msgs = [_make_msg(subject=f"subj_{i}", tags=("needs_reply",)) for i in range(10)]
        digest = compose_inbox_digest(msgs, top_n=3)
        assert len(digest.needs_reply) == 10
        # Text shows at most 3 in the reply queue
        body_lines = digest.text.splitlines()
        reply_section = [line for line in body_lines if line.strip().startswith("•")]
        assert len(reply_section) <= 3

    def test_age_hours_populated_when_zero(self) -> None:
        from app.routines.inbox_zero import compose_inbox_digest

        msg = _make_msg(hours_ago=2)
        assert msg.age_hours == 0.0  # not yet
        compose_inbox_digest([msg])
        assert msg.age_hours > 0.0


class TestSendInboxZero:
    @pytest.mark.asyncio
    async def test_no_context_returns_false(self, monkeypatch: Any) -> None:
        from app.routines.inbox_zero import send_inbox_zero
        from app.core.proactive_core import reset_registry

        reset_registry()
        result = await send_inbox_zero("u1", [])
        assert result is False
