# app/core/cron_engine.py
"""Dynamic JSON-backed Cron Engine for RAVEN autonomous scheduling.

Supports schedule types:
  - daily_at: Run once per day at HH:MM
  - interval_minutes: Run every N minutes

All jobs are stored in ~/.raven/memory/cron.json and can be managed
dynamically from the dashboard via REST API.
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.settings.config import Config

logger = logging.getLogger(__name__)


def _cron_matches(expr: str, dt: datetime) -> bool:
    """Evaluate a 5-field cron expression against a datetime.

    Fields: minute hour day_of_month month day_of_week
    Supports: * (any), N (exact), N-M (range), N/S (step), comma-separated lists.
    """
    fields = expr.strip().split()
    if len(fields) != 5:
        return False

    minute, hour, dom, month, dow = fields
    return (
        _cron_field_matches(minute, dt.minute, 0, 59)
        and _cron_field_matches(hour, dt.hour, 0, 23)
        and _cron_field_matches(dom, dt.day, 1, 31)
        and _cron_field_matches(month, dt.month, 1, 12)
        and _cron_field_matches(dow, dt.weekday(), 0, 6)
    )


def _cron_field_matches(field: str, value: int, min_val: int, max_val: int) -> bool:
    """Check if a single cron field matches a value."""
    if field == "*":
        return True

    # Comma-separated list
    for part in field.split(","):
        part = part.strip()

        # Step: */N or N/M
        if "/" in part:
            range_part, step_str = part.split("/", 1)
            try:
                step = int(step_str)
            except ValueError:
                return False
            if step <= 0:
                return False

            if range_part == "*":
                start, end = min_val, max_val
            elif "-" in range_part:
                start_str, end_str = range_part.split("-", 1)
                start, end = int(start_str), int(end_str)
            else:
                start = int(range_part)
                end = max_val

            if start <= value <= end and (value - start) % step == 0:
                return True

        # Range: N-M
        elif "-" in part:
            start_str, end_str = part.split("-", 1)
            try:
                start, end = int(start_str), int(end_str)
            except ValueError:
                return False
            if start <= value <= end:
                return True

        # Exact value
        else:
            try:
                if int(part) == value:
                    return True
            except ValueError:
                return False

    return False


class CronEngine:
    """Dynamic cron scheduler backed by ~/.raven/memory/cron.json."""

    def __init__(self) -> None:
        memory_root = Path(Config.MEMORY_ROOT)
        memory_root.mkdir(parents=True, exist_ok=True)
        self.cron_file = memory_root / "cron.json"
        self._ensure_defaults()

    # ── Defaults ───────────────────────────────────────────────────────

    def _ensure_defaults(self) -> None:
        """Seed the cron.json with sensible defaults on first run."""
        if self.cron_file.exists():
            return

        defaults = [
            {
                "job_id": "morning_routine",
                "name": "Autonomous Morning Briefing",
                "description": "Check Gmail, Google Calendar, and run a security scan. Summarize into a briefing.",
                "schedule_type": "daily_at",
                "time": f"{Config.MORNING_BRIEFING_HOUR:02d}:{Config.MORNING_BRIEFING_MINUTE:02d}",
                "enabled": True,
                "action": {
                    "type": "spawn_goal",
                    "description": "Execute Morning Routine: Use Gmail to check unread emails, use Google Calendar to list today's meetings, and run a system security check. Summarize the findings into a briefing and send it to me.",
                    "plan_steps": [
                        {"step_id": "s1", "description": "Delegate to HeraldAgent to check unread Gmail", "status": "Pending"},
                        {"step_id": "s2", "description": "Delegate to ConductorAgent to check today's Google Calendar", "status": "Pending"},
                        {"step_id": "s3", "description": "Delegate to SecurityAgent to perform a health/security scan", "status": "Pending"},
                        {"step_id": "s4", "description": "Delegate to HeraldAgent to send a summary notification", "status": "Pending"},
                    ],
                },
                "last_run_day": -1,
            },
            {
                "job_id": "sentinel_flush",
                "name": "Sentinel Digest Flush",
                "description": "Flush buffered sentinel event logs to storage.",
                "schedule_type": "interval_minutes",
                "interval": 5,
                "enabled": True,
                "action": {"type": "system", "handler": "sentinel_flush"},
                "last_run_ts": 0,
            },
            {
                "job_id": "health_check",
                "name": "System Health Monitor",
                "description": "Ping all services and broadcast degradation alerts.",
                "schedule_type": "interval_minutes",
                "interval": 5,
                "enabled": True,
                "action": {"type": "system", "handler": "health_check"},
                "last_run_ts": 0,
            },
            {
                "job_id": "self_improvement",
                "name": "Self-Improvement Analysis",
                "description": "Analyze tool metrics and write routing recommendations.",
                "schedule_type": "interval_minutes",
                "interval": 60,
                "enabled": True,
                "action": {"type": "system", "handler": "self_improvement"},
                "last_run_ts": 0,
            },
        ]
        self._save(defaults)

    # ── Persistence ────────────────────────────────────────────────────

    def _save(self, data: List[Dict[str, Any]]) -> None:
        with open(self.cron_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def get_jobs(self) -> List[Dict[str, Any]]:
        try:
            with open(self.cron_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.error("Failed to read cron.json: %s", exc)
            return []

    # ── CRUD ───────────────────────────────────────────────────────────

    def toggle_job(self, job_id: str) -> bool:
        jobs = self.get_jobs()
        for j in jobs:
            if j.get("job_id") == job_id:
                j["enabled"] = not j.get("enabled", False)
                self._save(jobs)
                return True
        return False

    def add_job(
        self,
        job_id: str,
        name: str,
        description: str,
        schedule_type: str,
        action_description: str,
        time_str: Optional[str] = None,
        interval: Optional[int] = None,
        cron_expr: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add a new cron job dynamically.

        schedule_type: 'daily_at', 'interval_minutes', or 'cron'
        cron_expr: standard 5-field cron expression (e.g. '0 9 * * 1-5')
        """
        jobs = self.get_jobs()

        # Prevent duplicates
        if any(j.get("job_id") == job_id for j in jobs):
            return {"success": False, "error": f"Job '{job_id}' already exists"}

        new_job: Dict[str, Any] = {
            "job_id": job_id,
            "name": name,
            "description": description,
            "schedule_type": schedule_type,
            "enabled": True,
            "action": {
                "type": "spawn_goal",
                "description": action_description,
                "plan_steps": [],
            },
        }

        if schedule_type == "daily_at":
            new_job["time"] = time_str or "08:00"
            new_job["last_run_day"] = -1
        elif schedule_type == "interval_minutes":
            new_job["interval"] = interval or 30
            new_job["last_run_ts"] = 0
        elif schedule_type == "cron":
            new_job["cron"] = cron_expr or "0 * * * *"  # default: every hour
            new_job["last_run_minute"] = -1

        jobs.append(new_job)
        self._save(jobs)
        return {"success": True, "job": new_job}

    def remove_job(self, job_id: str) -> bool:
        """Remove a cron job by ID."""
        jobs = self.get_jobs()
        original_len = len(jobs)
        jobs = [j for j in jobs if j.get("job_id") != job_id]
        if len(jobs) < original_len:
            self._save(jobs)
            return True
        return False

    # ── Tick ───────────────────────────────────────────────────────────

    async def tick_all(self) -> None:
        """Called by ambient_loop every minute to check and execute cron jobs."""
        jobs = self.get_jobs()
        now = datetime.now()
        now_ts = time.time()
        modified = False

        for job in jobs:
            if not job.get("enabled", False):
                continue

            schedule = job.get("schedule_type")

            # ── daily_at ──────────────────────────────────────────────
            if schedule == "daily_at":
                time_str = job.get("time", "08:00")
                try:
                    hour, minute = map(int, time_str.split(":"))
                except Exception:
                    continue

                if now.hour == hour and now.day != job.get("last_run_day", -1):
                    logger.info("CronEngine: Triggering '%s' at %02d:%02d", job["name"], hour, minute)
                    await self._execute_action(job["action"], now)
                    job["last_run_day"] = now.day
                    modified = True

            # ── interval_minutes ──────────────────────────────────────
            elif schedule == "interval_minutes":
                interval_secs = job.get("interval", 30) * 60
                last_ts = job.get("last_run_ts", 0)

                if now_ts - last_ts >= interval_secs:
                    logger.info("CronEngine: Triggering '%s' (every %dm)", job["name"], job.get("interval"))
                    await self._execute_action(job["action"], now)
                    job["last_run_ts"] = now_ts
                    modified = True

            # ── cron (5-field standard) ──────────────────────────────
            elif schedule == "cron":
                cron_expr = job.get("cron", "")
                if cron_expr and _cron_matches(cron_expr, now):
                    minute_key = now.strftime("%Y%m%d%H%M")
                    if job.get("last_run_minute") != minute_key:
                        logger.info("CronEngine: Triggering '%s' (cron: %s)", job["name"], cron_expr)
                        await self._execute_action(job["action"], now)
                        job["last_run_minute"] = minute_key
                        modified = True

        if modified:
            self._save(jobs)

    # ── Action Executor ────────────────────────────────────────────────

    async def _execute_action(self, action: Dict[str, Any], now: datetime) -> None:
        action_type = action.get("type", "")

        if action_type == "spawn_goal":
            goals_file = Path(Config.MEMORY_ROOT) / "goals.jsonl"
            goal_entry = {
                "goal_id": f"cron_auto_{now.strftime('%Y%m%d%H%M')}",
                "title": action.get("description", "Cron Job")[:80],
                "description": action.get("description", "Cron Job"),
                "status": "Active",
                "plan": {"steps": action.get("plan_steps", [])},
                "created_at": now.isoformat(),
            }
            mode = "a" if goals_file.exists() else "w"
            with open(goals_file, mode, encoding="utf-8") as f:
                f.write(json.dumps(goal_entry) + "\n")
            logger.info("CronEngine: Goal injected into AutonomyEngine")

        elif action_type == "system":
            # System jobs are handled natively by AmbientLoop's own tick methods.
            # They are listed here purely for dashboard visibility.
            pass
