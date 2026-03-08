# app/routines/morning_briefing.py
"""Morning briefing routine — fires at a configured time daily per user."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def compose_morning_briefing(user_id: str) -> str:
    """Compose a morning briefing string. Each section is best-effort."""
    sections = []
    now = datetime.now(timezone.utc)
    sections.append(f"Good morning! It's {now.strftime('%A, %B %d')}.")

    # Weather (requires OPENWEATHERMAP_API_KEY to be set)
    try:
        from app.tools.weathertool import WeatherTool

        wt = WeatherTool()
        result = await wt.execute(action="current", location="auto")
        if result.get("success"):
            sections.append(f"Weather: {result['summary']}")
    except Exception as exc:
        logger.debug("Morning briefing: weather unavailable: %s", exc)

    # News — best-effort via HackerNews tool if available
    try:
        from app.tools.news.hackernews import HackerNewsTool  # type: ignore[import]

        hn = HackerNewsTool()
        result = await hn.execute(action="top_stories", limit=3)
        if result.get("stories"):
            news_lines = "\n".join(f"• {s['title']}" for s in result["stories"][:3])
            sections.append(f"Top Stories:\n{news_lines}")
    except Exception as exc:
        logger.debug("Morning briefing: news unavailable: %s", exc)

    return "\n\n".join(sections)


def register_morning_briefing(
    scheduler,
    user_id: str,
    platform: str,
    chat_id: str,
    cron_hour: int = 8,
    cron_minute: int = 0,
) -> None:
    """Register the morning briefing cron job for a user."""
    from app.core.botsignal import get_botsignal

    async def _fire():
        text = await compose_morning_briefing(user_id)
        botsignal = get_botsignal()
        from app.core.models import ReplyTarget, SignalPayload

        target = ReplyTarget(platform=platform, chat_id=chat_id)
        payload = SignalPayload(text=text)
        await botsignal.send(target, payload)

    reminder_id = f"morning_briefing_{user_id}"
    # Override the scheduler's internal job with our custom coroutine
    scheduler._scheduler.add_job(
        _fire,
        trigger="cron",
        id=reminder_id,
        hour=cron_hour,
        minute=cron_minute,
        replace_existing=True,
    )
    logger.info(
        "Morning briefing registered for user %s at %02d:%02d UTC",
        user_id,
        cron_hour,
        cron_minute,
    )
