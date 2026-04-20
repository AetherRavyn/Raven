# app/core/ambient_loop.py
"""Ambient Event Loop — the always-on background heartbeat of SARAS.

Instead of only responding to user messages, this loop continuously:
  1. Polls environmental data (sensors, MQTT, HomeSentinel)
  2. Checks proactive triggers (calendar, reminders, follow-ups)
  3. Runs self-improvement analysis
  4. Manages workflow execution
  5. Broadcasts state to dashboard subscribers

This transforms SARAS from a request-response chatbot into an
ambient intelligence system that acts on its own when appropriate.

Lifecycle:
  Start via `await ambient_loop.run()` — runs until cancelled.
  Uses asyncio.sleep between ticks for low CPU overhead.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Tick interval in seconds — how often the ambient loop wakes up
_TICK_INTERVAL = 60  # 1 minute between ambient checks
_SELF_IMPROVEMENT_INTERVAL = 3600  # Run self-improvement analysis hourly
_DIGEST_INTERVAL = 300  # Flush sentinel digest every 5 min
_HEALTH_CHECK_INTERVAL = 300  # Health checks every 5 min


class AmbientLoop:
    """Always-on background loop for proactive intelligence."""

    def __init__(
        self,
        orchestrator=None,
        botsignal=None,
        workspace_dir: str | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._botsignal = botsignal
        self._running = False

        # Timing trackers
        self._last_self_improvement = 0.0
        self._last_digest_flush = 0.0
        self._last_health_check = 0.0
        self._last_persona_reset_day = -1
        self._tick_count = 0
        self._start_time = 0.0

    async def run(self) -> None:
        """Main ambient loop — blocks forever until cancelled."""
        self._running = True
        self._start_time = time.time()
        logger.info("AmbientLoop started — SARAS is now always-on 🟢")

        while self._running:
            try:
                await self._tick()
                self._tick_count += 1
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("AmbientLoop tick error: %s", exc)

            await asyncio.sleep(_TICK_INTERVAL)

        logger.info("AmbientLoop stopped")

    def stop(self) -> None:
        self._running = False

    # ── Tick ───────────────────────────────────────────────────────────

    async def _tick(self) -> None:
        """Single ambient tick — check all proactive systems."""
        now = time.time()

        # ── 1. Sentinel Digest Flush ───────────────────────────────────
        if now - self._last_digest_flush >= _DIGEST_INTERVAL:
            self._last_digest_flush = now
            await self._flush_sentinel_digest()

        # ── 2. Self-Improvement Analysis ───────────────────────────────
        if now - self._last_self_improvement >= _SELF_IMPROVEMENT_INTERVAL:
            self._last_self_improvement = now
            await self._run_self_improvement()

        # ── 3. Workflow Engine Tick ────────────────────────────────────
        await self._tick_workflows()

        # ── 4. Health Check ────────────────────────────────────────────
        if now - self._last_health_check >= _HEALTH_CHECK_INTERVAL:
            self._last_health_check = now
            await self._check_health()

        # ── 5. Persona Daily Reset ─────────────────────────────────────
        today = datetime.now().day
        if today != self._last_persona_reset_day:
            self._last_persona_reset_day = today
            self._reset_persona()

        # ── 6. Broadcast heartbeat to dashboard ───────────────────────
        await self._broadcast_heartbeat()

    # ── Sentinel ───────────────────────────────────────────────────────

    async def _flush_sentinel_digest(self) -> None:
        """Flush buffered sentinel events to users."""
        try:
            from app.core.sentinel_bridge import get_sentinel_bridge
            bridge = get_sentinel_bridge()
            digest = await bridge.flush_digest()
            if digest:
                logger.debug("AmbientLoop: flushed sentinel digest (%d chars)", len(digest))
        except Exception as exc:
            logger.debug("AmbientLoop: sentinel digest flush skipped — %s", exc)

    # ── Self-Improvement ───────────────────────────────────────────────

    async def _run_self_improvement(self) -> None:
        """Run periodic self-analysis and log recommendations."""
        try:
            from app.core.self_improvement import get_feedback_tracker

            tracker = get_feedback_tracker()
            report = tracker.get_routing_recommendations()

            if report["recommendations"]:
                logger.info(
                    "Self-Improvement: %d recommendations found",
                    len(report["recommendations"]),
                )
                for rec in report["recommendations"]:
                    logger.info("  → [%s] %s", rec["type"], rec["suggestion"])

                # Save report to workspace
                from app.settings.config import Config
                from pathlib import Path
                import json

                report_path = Path(Config.MEMORY_ROOT) / "self_improvement" / "latest_report.json"
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report["generated_at"] = datetime.now(timezone.utc).isoformat()
                report_path.write_text(
                    json.dumps(report, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

            # Check for unregistered tools
            if self._orchestrator and hasattr(self._orchestrator, '_agent_runtime'):
                registered = list(self._orchestrator._agent_runtime.tools.keys())
                discovered = tracker.discover_unregistered_tools(registered)
                if discovered:
                    logger.info(
                        "Self-Improvement: found %d unregistered tool classes: %s",
                        len(discovered),
                        [d["class"] for d in discovered],
                    )

        except Exception as exc:
            logger.debug("AmbientLoop: self-improvement skipped — %s", exc)

    # ── Workflow Engine ────────────────────────────────────────────────

    async def _tick_workflows(self) -> None:
        """Check for pending workflow runs and advance them."""
        try:
            from app.core.workflow_engine import WorkflowEngine

            engine = WorkflowEngine()
            runs = engine.list_runs()

            for run in runs:
                if run.get("status") == "running":
                    wf = engine.load_workflow(run["workflow_id"])
                    if not wf:
                        continue

                    current = run.get("current_step")
                    # Find the next pending step
                    for step in wf.steps:
                        if step.status == "pending":
                            # Check if dependencies are met
                            deps_met = all(
                                any(
                                    s.step_id == dep and s.status == "done"
                                    for s in wf.steps
                                )
                                for dep in step.depends_on
                            )
                            if deps_met:
                                logger.info(
                                    "AmbientLoop: advancing workflow '%s' step '%s'",
                                    wf.name,
                                    step.title,
                                )
                                # Mark step as in-progress
                                engine.advance_step(
                                    run["run_id"],
                                    step.step_id,
                                    "in_progress",
                                )
                                break
        except Exception as exc:
            logger.debug("AmbientLoop: workflow tick skipped — %s", exc)

    # ── Dashboard Heartbeat ────────────────────────────────────────────

    async def _broadcast_heartbeat(self) -> None:
        """Send periodic heartbeat to all dashboard WebSocket subscribers."""
        try:
            from app.web.server import broadcast_event

            uptime = time.time() - self._start_time
            await broadcast_event({
                "event": "ambient_heartbeat",
                "tick": self._tick_count,
                "uptime_seconds": int(uptime),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass  # Dashboard may not be running

    # ── Health Check ───────────────────────────────────────────────────

    async def _check_health(self) -> None:
        """Run dependency health checks and broadcast results."""
        try:
            from app.core.health import get_health_monitor

            monitor = get_health_monitor()
            await monitor.check_all()
            summary = monitor.get_summary()

            if summary["down"] > 0:
                down = ", ".join(summary["down_services"])
                logger.warning(
                    "AmbientLoop: %d service(s) DOWN: %s",
                    summary["down"],
                    down,
                )

                # Broadcast to dashboard
                try:
                    from app.web.server import broadcast_event
                    await broadcast_event({
                        "event": "health_alert",
                        "severity": "HIGH",
                        "down_services": summary["down_services"],
                        "summary": summary,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                except Exception:
                    pass
            else:
                logger.debug(
                    "AmbientLoop: health check passed (%d/%d healthy)",
                    summary["healthy"],
                    summary["total"],
                )

        except Exception as exc:
            logger.debug("AmbientLoop: health check skipped — %s", exc)

    # ── Persona Reset ──────────────────────────────────────────────────

    def _reset_persona(self) -> None:
        """Daily persona reset — restore energy and confidence."""
        try:
            from app.core.persona import get_persona_engine

            persona = get_persona_engine()
            persona.on_daily_reset()
            logger.info("AmbientLoop: persona daily reset complete")
        except Exception as exc:
            logger.debug("AmbientLoop: persona reset skipped — %s", exc)


# ── Module singleton ───────────────────────────────────────────────────

_LOOP: AmbientLoop | None = None


def get_ambient_loop() -> AmbientLoop:
    global _LOOP
    if _LOOP is None:
        _LOOP = AmbientLoop()
    return _LOOP

