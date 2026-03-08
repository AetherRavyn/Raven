# app/core/scheduler.py
"""SARAS task scheduler — wraps APScheduler with SQLite persistence.

Usage:
    scheduler = get_scheduler()
    await scheduler.start()          # call once at bot startup
    scheduler.add_reminder(
        reminder_id="my_id",
        user_id="123",
        platform="telegram",
        chat_id="456",
        message="Your meeting starts now!",
        run_at=datetime(2026, 3, 2, 9, 0, tzinfo=timezone.utc),
    )
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

logger = logging.getLogger(__name__)

_INSTANCE: SarasScheduler | None = None


class SarasScheduler:
    def __init__(self, db_url: str = "sqlite:///workspace/scheduler.db") -> None:
        jobstores = {"default": SQLAlchemyJobStore(url=db_url)}
        self._scheduler = AsyncIOScheduler(jobstores=jobstores)
        self._botsignal = None  # injected after bot startup

    def set_botsignal(self, botsignal) -> None:
        self._botsignal = botsignal

    async def start(self) -> None:
        self._scheduler.start()
        logger.info(
            "SarasScheduler started. Pending jobs: %d", len(self._scheduler.get_jobs())
        )

    async def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)

    def add_reminder(
        self,
        reminder_id: str,
        user_id: str,
        platform: str,
        chat_id: str,
        message: str,
        run_at: datetime | None,
        repeat_cron: str | None = None,  # e.g. "0 8 * * *" for 8am daily
    ) -> str:
        """Schedule a one-shot or recurring reminder. Returns job_id."""
        from app.core.models import ReplyTarget, SignalPayload

        async def _fire():
            if self._botsignal:
                target = ReplyTarget(platform=platform, chat_id=chat_id)
                payload = SignalPayload(text=f"\u23f0 Reminder: {message}")
                await self._botsignal.send(target, payload)
            else:
                logger.warning(
                    "SarasScheduler: botsignal not set, cannot send reminder"
                )

        if repeat_cron:
            parts = repeat_cron.split()
            if len(parts) == 5:
                minute, hour, day, month, day_of_week = parts
                self._scheduler.add_job(
                    _fire,
                    trigger="cron",
                    id=reminder_id,
                    minute=minute,
                    hour=hour,
                    day=day,
                    month=month,
                    day_of_week=day_of_week,
                    replace_existing=True,
                )
        else:
            self._scheduler.add_job(
                _fire,
                trigger="date",
                run_date=run_at,
                id=reminder_id,
                replace_existing=True,
            )

        logger.info(
            "Reminder scheduled: id=%s at=%s", reminder_id, run_at or repeat_cron
        )
        return reminder_id

    def cancel_reminder(self, reminder_id: str) -> bool:
        try:
            self._scheduler.remove_job(reminder_id)
            return True
        except Exception:
            return False

    def list_reminders(self) -> list[dict]:
        jobs = self._scheduler.get_jobs()
        return [{"id": j.id, "next_run": str(j.next_run_time)} for j in jobs]


def get_scheduler() -> SarasScheduler:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = SarasScheduler()
    return _INSTANCE
