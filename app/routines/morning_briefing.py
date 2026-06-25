# app/routines/morning_briefing.py
"""Morning briefing routine — fires at a configured time daily per user.

When a :class:`DeliveryAdapter` is registered for the user in the
proactive-core registry, the briefing is routed through the
engine.  Otherwise it falls back to the legacy direct-send path,
preserving the old behaviour for callers that haven't been
upgraded yet.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.core.model_router import AutoModelRouter
from app.core.proactive import ProactiveDigest, send_proactive_digest
from app.core.proactive_core import (
    ProactiveSignal,
    SignalKind,
    Urgency,
    get_context,
)
from app.settings.config import Config
from app.core.task_ledger import TaskLedger
from app.provider.factory import create_provider

logger = logging.getLogger(__name__)


async def compose_morning_briefing(user_id: str) -> str:
    """Compose a JARVIS-style morning briefing using real context and an LLM."""
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%A, %B %d")

    memory_root = Path(Config.MEMORY_ROOT)

    # 1. Fetch real context
    # Active edge nodes
    devices_path = memory_root / "state" / "devices.json"
    edge_nodes = []
    if devices_path.exists():
        try:
            with open(devices_path, "r", encoding="utf-8") as f:
                devices_data = json.load(f)
                edge_nodes = [d for d in devices_data if d.get("status") == "active"]
        except Exception as exc:
            logger.debug("Failed to read devices.json: %s", exc)

    # Task Ledger
    open_tasks_count = 0
    pending_approvals = []
    forecasts = []
    anomalies = []

    try:
        ledger = TaskLedger()
        open_tasks = ledger.list_tasks(status="open")

        for t in open_tasks:
            t_type = t.get("task_type", "")
            if t_type == "approval":
                pending_approvals.append(t.get("title", "Unknown Approval"))
            elif t_type == "forecast":
                forecasts.append(t.get("title", "Unknown Forecast"))
            elif t_type == "anomaly_response":
                anomalies.append(t.get("title", "Unknown Anomaly"))
            elif t_type in ("task", "runtime"):
                open_tasks_count += 1
    except Exception as exc:
        logger.debug("Failed to read TaskLedger: %s", exc)

    # Evidence (Internet signals)
    evidence_path = memory_root / "evidence.jsonl"
    signals = []
    if evidence_path.exists():
        try:
            with open(evidence_path, "r", encoding="utf-8") as f:
                lines = [line for line in f if line.strip()]
                for line in lines[-3:]:
                    try:
                        signals.append(json.loads(line))
                    except Exception:
                        pass
        except Exception as exc:
            logger.debug("Failed to read evidence.jsonl: %s", exc)

    # Weather
    weather_info = "Weather unavailable."
    try:
        from app.tools.weathertool import WeatherTool

        wt = WeatherTool()
        result = await wt.execute(operation="current", location="auto")
        if result.get("success"):
            weather_info = result["summary"]
    except Exception as exc:
        logger.debug("Morning briefing: weather unavailable: %s", exc)

    # 2. Build Context String
    context_lines = [
        f"Date: {date_str}",
        f"Weather: {weather_info}",
        f"Active Edge Nodes: {len(edge_nodes)}",
        f"Open Regular Tasks: {open_tasks_count}",
    ]

    if pending_approvals:
        context_lines.append(f"Pending Approvals: {', '.join(pending_approvals)}")
    else:
        context_lines.append("Pending Approvals: None")

    if forecasts:
        context_lines.append(f"Latest Forecast: {forecasts[-1]}")

    if anomalies:
        context_lines.append(f"Recent Anomalies: {', '.join(anomalies[-2:])}")

    if signals:
        signal_texts = []
        for s in signals:
            txt = s.get("title", "") or s.get("content", "") or str(s)
            if len(txt) > 100:
                txt = txt[:100] + "..."
            signal_texts.append(txt)
        context_lines.append(f"Latest Internet Signals: {', '.join(signal_texts)}")

    context_str = "\n".join(context_lines)

    # 3. LLM Synthesize
    prompt = f"""You are a highly capable Executive Operator AI (like JARVIS).
Write a concise, sci-fi style morning briefing for your user.
Synthesize the following system context into a seamless, spoken-word narrative.
Be highly professional, slightly proactive, and keep it under 3 paragraphs.
Do not use markdown headers, asterisks, or complex formatting - just plain text suitable for text-to-speech.

System Context:
{context_str}
"""
    try:
        provider_name, model_name = AutoModelRouter.get_best_model("agent")
        provider = create_provider(provider_name)
        resilient = getattr(provider, "chat_completion_resilient", None)
        messages = [{"role": "user", "content": prompt}]

        if resilient:
            result = await resilient(
                messages=messages,
                preferred_models=[
                    "big-pickle",
                    "deepseek-v4-flash-free",
                ],
                free_only_guard=True,
            )
        else:
            result = await provider.chat_completion(
                model=model_name or "default", messages=messages
            )

        if isinstance(result, dict) and result.get("success"):
            content = result.get("content", "").strip()
            if content:
                return content
    except Exception as exc:
        logger.error("LLM generation failed for morning briefing: %s", exc)

    # Fallback text if LLM fails
    fallback = (
        f"Good morning. It is {date_str}. {weather_info} "
        f"System is online with {len(edge_nodes)} active edge nodes. "
        f"You have {open_tasks_count} open tasks and {len(pending_approvals)} pending approvals."
    )
    return fallback


async def compose_daily_digest(user_id: str) -> ProactiveDigest:
    text = await compose_morning_briefing(user_id)
    # Return the full synthesized string in the title property, keeping items empty
    # so it reads smoothly without bullet points for voice synthesis.
    return ProactiveDigest(title=text, items=[], source="morning_briefing")


def _build_morning_signal(
    user_id: str, digest: ProactiveDigest
) -> ProactiveSignal:
    """Wrap a composed digest in a :class:`ProactiveSignal`.

    The morning briefing is a low-urgency routine signal.  We
    give it a high value and high confidence because we trust
    the LLM-composed text and the user has explicitly asked for
    a daily digest (so it shouldn't be treated as noise).
    """
    return ProactiveSignal(
        id=f"morning_briefing:{user_id}:{datetime.now(timezone.utc).date().isoformat()}",
        user_id=user_id,
        kind=SignalKind.ROUTINE,
        title="Morning briefing",
        body=digest.title,
        urgency=Urgency.LOW,
        value=0.95,
        confidence=0.95,
        source="morning_briefing",
        metadata={"target_id": f"morning_briefing:{user_id}"},
    )


async def _fire_via_engine(
    user_id: str, platform: str, chat_id: str
) -> bool:
    """Send the briefing through the proactive engine.

    Returns True if the engine handled the signal, False if no
    context was registered and the caller should fall back.
    """
    ctx = get_context(user_id)
    if ctx is None or ctx.adapter is None:
        return False

    digest = await compose_daily_digest(user_id)
    signal = _build_morning_signal(user_id, digest)
    decision = await ctx.adapter.dispatch(signal)
    logger.info(
        "morning_briefing: user=%s verdict=%s stage=%s reason=%s",
        user_id,
        decision.verdict.value,
        decision.stage,
        decision.reason or "-",
    )
    return True


def register_morning_briefing(
    scheduler,
    user_id: str,
    platform: str,
    chat_id: str,
    cron_hour: int = 8,
    cron_minute: int = 0,
) -> None:
    """Register the morning briefing cron job for a user.

    When ``scheduler`` is a v2 :class:`Scheduler` (from
    :mod:`app.core.scheduling`), the routine is registered via
    the new :class:`CronTrigger` and routed through the
    scheduler's fire callback.  When it's the legacy
    :class:`RavenScheduler`, falls back to the previous
    APScheduler-based registration.
    """
    from app.core.scheduling import (
        Scheduler,
    )

    if isinstance(scheduler, Scheduler):
        register_morning_briefing_v2(
            scheduler,
            user_id=user_id,
            platform=platform,
            chat_id=chat_id,
            cron_hour=cron_hour,
            cron_minute=cron_minute,
        )
        return

    from app.core.models import ReplyTarget

    async def _fire():
        # Prefer the proactive engine when registered.
        if await _fire_via_engine(user_id, platform, chat_id):
            return
        # Legacy path — direct send.
        digest = await compose_daily_digest(user_id)
        target = ReplyTarget(platform=platform, chat_id=chat_id)
        await send_proactive_digest(target, digest)

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


def register_morning_briefing_v2(
    scheduler: "Scheduler",  # noqa: F821 (forward ref under __future__ annotations)
    *,
    user_id: str,
    platform: str,
    chat_id: str,
    cron_hour: int = 8,
    cron_minute: int = 0,
    schedule_id: str | None = None,
) -> str:
    """Register the morning briefing on a v2 :class:`Scheduler`.

    The routine looks up the user in
    :func:`app.core.continuity.identity.identity_registry` so the
    scheduler knows where to deliver.  A :class:`CronTrigger`
    drives the daily cadence.
    """
    from app.core.scheduling import CronTrigger
    from app.core.models import ReplyTarget

    async def _fire(user_id_arg: str, *, triggered_at, **_: object) -> None:
        # Prefer the proactive engine when registered.
        if await _fire_via_engine(user_id_arg, platform, chat_id):
            return
        # Legacy path — direct send.
        digest = await compose_daily_digest(user_id_arg)
        target = ReplyTarget(platform=platform, chat_id=chat_id)
        await send_proactive_digest(target, digest)

    routine_id = f"morning_briefing::{user_id}"
    scheduler.routine_registry.register_fn(
        routine_id,
        _fire,
        name=f"Morning briefing for {user_id}",
        kind="morning_briefing",
    )
    sched = scheduler.add(
        routine_id,
        CronTrigger(
            expression=f"{cron_minute} {cron_hour} * * *",
        ),
        user_id=user_id,
        schedule_id=schedule_id or f"morning_briefing_{user_id}",
        metadata={"platform": platform, "chat_id": chat_id},
    )
    logger.info(
        "morning_briefing v2 registered: user=%s at %02d:%02d schedule_id=%s",
        user_id,
        cron_hour,
        cron_minute,
        sched.id,
    )
    return sched.id
