"""Scheduling Module — A2A-compliant scheduling and cron module.

Exposes scheduling capabilities via the Raven Protocol.
Any module can create/manage schedules without importing app/ code.
"""

from __future__ import annotations

import logging
from typing import Any

from raven_protocol import AgentCard, Skill, ModuleServer

logger = logging.getLogger(__name__)


async def handle_add_job(params: dict[str, Any]) -> dict[str, Any]:
    """Add a cron job."""
    from app.core.cron_engine import CronEngine
    engine = CronEngine()
    result = engine.add_job(
        job_id=params.get("job_id", ""),
        name=params.get("name", ""),
        description=params.get("description", ""),
        schedule_type=params.get("schedule_type", "daily_at"),
        action_description=params.get("action_description", ""),
        time_str=params.get("time"),
        interval=params.get("interval"),
        cron_expr=params.get("cron"),
    )
    return result


async def handle_list_jobs(params: dict[str, Any]) -> dict[str, Any]:
    """List all cron jobs."""
    from app.core.cron_engine import CronEngine
    engine = CronEngine()
    jobs = engine.get_jobs()
    return {"jobs": jobs, "count": len(jobs)}


async def handle_toggle_job(params: dict[str, Any]) -> dict[str, Any]:
    """Toggle a cron job on/off."""
    from app.core.cron_engine import CronEngine
    engine = CronEngine()
    success = engine.toggle_job(params.get("job_id", ""))
    return {"success": success}


async def handle_remove_job(params: dict[str, Any]) -> dict[str, Any]:
    """Remove a cron job."""
    from app.core.cron_engine import CronEngine
    engine = CronEngine()
    success = engine.remove_job(params.get("job_id", ""))
    return {"success": success}


def create_scheduling_server() -> ModuleServer:
    """Create and configure the Scheduling module server."""
    card = AgentCard(
        name="scheduling",
        description="Cron scheduling and job management",
        version="1.0.0",
        skills=[
            Skill(name="add_job", description="Add a cron job", tags=["cron", "schedule", "add"]),
            Skill(name="list_jobs", description="List all jobs", tags=["cron", "list"]),
            Skill(name="toggle_job", description="Toggle job on/off", tags=["cron", "toggle"]),
            Skill(name="remove_job", description="Remove a job", tags=["cron", "remove"]),
        ],
        transport="in-process",
    )

    server = ModuleServer(card)
    server.register_method("scheduling.add_job", handle_add_job)
    server.register_method("scheduling.list_jobs", handle_list_jobs)
    server.register_method("scheduling.toggle_job", handle_toggle_job)
    server.register_method("scheduling.remove_job", handle_remove_job)

    return server
