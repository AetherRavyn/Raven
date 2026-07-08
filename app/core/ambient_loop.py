# app/core/ambient_loop.py
"""Ambient Event Loop — the always-on background heartbeat of RAVEN.

Instead of only responding to user messages, this loop continuously:
  1. Polls environmental data (sensors, MQTT, HomeSentinel)
  2. Checks proactive triggers (calendar, reminders, follow-ups)
  3. Runs self-improvement analysis
  4. Manages workflow execution
  5. Broadcasts state to dashboard subscribers

This transforms RAVEN from a request-response chatbot into an
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
from typing import Any

logger = logging.getLogger(__name__)

# Tick interval in seconds — how often the ambient loop wakes up
_TICK_INTERVAL = 60  # 1 minute between ambient checks
_SELF_IMPROVEMENT_INTERVAL = 3600  # Run self-improvement analysis hourly
_DIGEST_INTERVAL = 300  # Flush sentinel digest every 5 min
_HEALTH_CHECK_INTERVAL = 300  # Health checks every 5 min
_MEMORY_UPDATE_INTERVAL = 600  # Auto-update MEMORY.md every 10 min
_PROACTIVE_INTEL_INTERVAL = 120  # Re-evaluate proactive candidates every 2 min
_KNOWLEDGE_SYNC_INTERVAL = 300  # Sync life-context into KG every 5 min
_LEARNING_SUMMARY_INTERVAL = 3600  # Refresh learning summary hourly
_PRESENCE_REFRESH_INTERVAL = 1800  # Re-check presence every 30 min
_CRON_TICK_INTERVAL = 60  # Tick the dynamic CronEngine every minute
_RL_REPLAY_INTERVAL = 300  # Replay RL experience buffer every 5 min
_NUDGE_INTERVAL = 3600  # Check nudge engine every hour
_WORKING_MEMORY_DECAY_INTERVAL = 300  # Decay working memory every 5 min
_COMPANION_DISCOVERY_INTERVAL = 600  # Check for companion AIs every 10 min
_TRAINING_DATA_INTERVAL = 21600  # Auto-export training data every 6 hours
_AGENT_HEARTBEAT_INTERVAL = 600  # Agent heartbeats every 10 min
_GOAL_ADVANCE_INTERVAL = 1800  # Advance goals every 30 min
_RESILIENCE_CHECK_INTERVAL = 600  # Check service health every 10 min
_PREDICTIVE_SCHEDULE_INTERVAL = 3600  # Generate schedule suggestions hourly
_FORECAST_INTERVAL = 7200  # Update forecasts every 2 hours
_PERCEPTION_INTERVAL = 300  # Perception scan every 5 min
_A2A_SERVER_INTERVAL = 300  # Check A2A servers every 5 min
_EVAL_INTERVAL = 3600  # Run eval harness hourly
_REGRESSION_INTERVAL = 1800  # Regression check every 30 min
_DEGRADATION_INTERVAL = 300  # Degradation check every 5 min
_ENVIRONMENTAL_SENSOR_INTERVAL = 300  # Environmental sensor every 5 min
_MULTIMODAL_INTERVAL = 600  # Multimodal processing every 10 min
_EVENT_DIGEST_INTERVAL = 600  # Event digest every 10 min
_SELF_EVOLUTION_INTERVAL = 3600  # Self-evolution assessment hourly
_NOTIFICATION_RETRY_INTERVAL = 300  # Retry pending notifications every 5 min
_CURIOSITY_INTERVAL = 1800  # Curiosity-driven exploration every 30 min


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
        self._last_memory_update = 0.0
        self._last_proactive_intel = 0.0
        self._last_knowledge_sync = 0.0
        self._last_learning_summary = 0.0
        self._last_presence_refresh = 0.0
        self._last_cron_tick = 0.0
        self._last_rl_replay = 0.0
        self._last_goal_advance = 0.0
        self._last_resilience_check = 0.0
        self._last_predictive_schedule = 0.0
        self._last_forecast = 0.0
        self._last_perception = 0.0
        self._last_a2a_server = 0.0
        self._last_eval = 0.0
        self._last_regression = 0.0
        self._last_degradation = 0.0
        self._last_environmental = 0.0
        self._last_multimodal = 0.0
        self._last_event_digest = 0.0
        self._last_self_evolution = 0.0
        self._last_notification_retry = 0.0
        self._last_curiosity_check = 0.0
        self._last_nudge_check = 0.0
        self._last_working_memory_decay = 0.0
        self._last_companion_discovery = 0.0
        self._last_training_data_export = 0.0
        self._last_agent_heartbeat = 0.0
        # Cached multimodal context from last tick
        self._last_multimodal_context: dict | None = None
        self._tick_count = 0
        self._start_time = 0.0
        # Decisions emitted by ProactiveIntelligence — exposed for
        # the audit log + tests.  Cleared by :meth:`drain_decisions`.
        self._recent_decisions: list[dict[str, Any]] = []
        self._recent_kb_writes: list[dict[str, Any]] = []
        self._recent_learning_summaries: list[dict[str, Any]] = []
        self._recent_presence_snapshots: list[dict[str, Any]] = []
        self._recent_cron_fires: list[dict[str, Any]] = []
        self._lists_lock = asyncio.Lock()

    async def run(self) -> None:
        """Main ambient loop — blocks forever until cancelled."""
        self._running = True
        self._start_time = time.time()
        logger.info("AmbientLoop started — RAVEN is now always-on 🟢")

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

        # ── 3b. Autonomous Action Engine (FRIDAY) ─────────────────────
        await self._tick_autonomous_actions()

        # ── 3c. Live Data Feeds (FRIDAY) ────────────────────────────
        await self._tick_live_feeds()

        # ── 4. Health Check ────────────────────────────────────────────
        if now - self._last_health_check >= _HEALTH_CHECK_INTERVAL:
            self._last_health_check = now
            await self._check_health()

        # ── 5. Persona Daily Reset ─────────────────────────────────────
        today = datetime.now().day
        if today != self._last_persona_reset_day:
            self._last_persona_reset_day = today
            self._reset_persona()

        # ── 6. Memory Auto-Update (Phase 0.3) ──────────────────────────
        if now - self._last_memory_update >= _MEMORY_UPDATE_INTERVAL:
            self._last_memory_update = now
            await self._tick_memory_update()

        # ── 6b. Proactive Intelligence gate (Phase 2 wiring) ──────────
        if now - self._last_proactive_intel >= _PROACTIVE_INTEL_INTERVAL:
            self._last_proactive_intel = now
            await self._tick_proactive_intelligence()

        # ── 6c. Knowledge sync (Phase 4 wiring) ──────────────────────
        if now - self._last_knowledge_sync >= _KNOWLEDGE_SYNC_INTERVAL:
            self._last_knowledge_sync = now
            await self._tick_knowledge_sync()

        # ── 6d. Learning summary (Phase 4 v10) ──────────────────────
        if now - self._last_learning_summary >= _LEARNING_SUMMARY_INTERVAL:
            self._last_learning_summary = now
            await self._tick_learning_summary()

        # ── 6e. RL replay (experience replay training) ──────────────
        if now - self._last_rl_replay >= _RL_REPLAY_INTERVAL:
            self._last_rl_replay = now
            await self._tick_rl_replay()

        # ── 6f. Presence refresh (Phase 4 v11) ─────────────────────
        if now - self._last_presence_refresh >= _PRESENCE_REFRESH_INTERVAL:
            self._last_presence_refresh = now
            await self._tick_presence_refresh()

        # ── 6f. CronEngine tick (Phase 5 v13) ────────────────────────
        if now - self._last_cron_tick >= _CRON_TICK_INTERVAL:
            self._last_cron_tick = now
            await self._tick_cron()

        # ── 6g. Nudge engine (FRIDAY proactive reminders) ───────────
        if now - self._last_nudge_check >= _NUDGE_INTERVAL:
            self._last_nudge_check = now
            await self._tick_nudges()

        # ── 6h. Working memory decay ─────────────────────────────
        if now - self._last_working_memory_decay >= _WORKING_MEMORY_DECAY_INTERVAL:
            self._last_working_memory_decay = now
            await self._tick_working_memory_decay()

        # ── 6i. Companion AI discovery ───────────────────────────
        if now - self._last_companion_discovery >= _COMPANION_DISCOVERY_INTERVAL:
            self._last_companion_discovery = now
            await self._tick_companion_discovery()

        # ── 6j. Auto training data export ────────────────────────
        if now - self._last_training_data_export >= _TRAINING_DATA_INTERVAL:
            self._last_training_data_export = now
            await self._tick_training_data()

        # ── 6k. Agent heartbeats (background agent work) ──────────
        if now - self._last_agent_heartbeat >= _AGENT_HEARTBEAT_INTERVAL:
            self._last_agent_heartbeat = now
            await self._tick_agent_heartbeats()

        # ── 6l. Goal advancement ─────────────────────────────────
        if now - self._last_goal_advance >= _GOAL_ADVANCE_INTERVAL:
            self._last_goal_advance = now
            await self._tick_goals()

        # ── 6m. Resilience health check ──────────────────────────
        if now - self._last_resilience_check >= _RESILIENCE_CHECK_INTERVAL:
            self._last_resilience_check = now
            await self._tick_resilience()

        # ── 6n. Predictive scheduling ────────────────────────────
        if now - self._last_predictive_schedule >= _PREDICTIVE_SCHEDULE_INTERVAL:
            self._last_predictive_schedule = now
            await self._tick_predictive_schedule()


        # ── 6o. Forecast update ──────────────────────────────────
        if now - self._last_forecast >= _FORECAST_INTERVAL:
            self._last_forecast = now
            await self._tick_forecast()

        # ── 6p. Perception scan ──────────────────────────────────
        if now - self._last_perception >= _PERCEPTION_INTERVAL:
            self._last_perception = now
            await self._tick_perception()

        # ── 6q. A2A server health ───────────────────────────────
        if now - self._last_a2a_server >= _A2A_SERVER_INTERVAL:
            self._last_a2a_server = now
            await self._tick_a2a_servers()

        # ── 6r. Evaluation harness ──────────────────────────────
        if now - self._last_eval >= _EVAL_INTERVAL:
            self._last_eval = now
            await self._tick_eval()

        # ── 6s. Regression detection ────────────────────────────
        if now - self._last_regression >= _REGRESSION_INTERVAL:
            self._last_regression = now
            await self._tick_regression()

        # ── 6t. Degradation monitoring ──────────────────────────
        if now - self._last_degradation >= _DEGRADATION_INTERVAL:
            self._last_degradation = now
            await self._tick_degradation()

        # ── 6u. Environmental sensors ───────────────────────────
        if now - self._last_environmental >= _ENVIRONMENTAL_SENSOR_INTERVAL:
            self._last_environmental = now
            await self._tick_environmental()

        # ── 6v. Multimodal processing ───────────────────────────
        if now - self._last_multimodal >= _MULTIMODAL_INTERVAL:
            self._last_multimodal = now
            await self._tick_multimodal()

        # ── 6w. Event digest ────────────────────────────────────
        if now - self._last_event_digest >= _EVENT_DIGEST_INTERVAL:
            self._last_event_digest = now
            await self._tick_event_digest()

        # ── 6x. Self-evolution assessment ─────────────────────────
        if now - self._last_self_evolution >= _SELF_EVOLUTION_INTERVAL:
            self._last_self_evolution = now
            await self._tick_self_evolution()

        # ── 6y. Notification retry ────────────────────────────────
        if now - self._last_notification_retry >= _NOTIFICATION_RETRY_INTERVAL:
            self._last_notification_retry = now
            await self._tick_notification_retry()

        # ── 6z. Curiosity-driven exploration ──────────────────────
        if now - self._last_curiosity_check >= _CURIOSITY_INTERVAL:
            self._last_curiosity_check = now
            await self._tick_curiosity()

        # ── 7. Broadcast heartbeat to dashboard ───────────────────────
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
            if self._orchestrator and hasattr(self._orchestrator, "_agent_runtime"):
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

    # ── RL Experience Replay ─────────────────────────────────────────

    async def _tick_rl_replay(self) -> None:
        """Periodically train the RL agent on accumulated experience."""
        try:
            from app.core.reinforcement_learning import get_reinforcement_learner

            rl = get_reinforcement_learner()
            trained = rl.replay(batch_size=64)
            if trained:
                logger.debug("AmbientLoop: RL replay trained on %d experiences", trained)
        except Exception as exc:
            logger.debug("AmbientLoop: RL replay skipped — %s", exc)

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

                    # Find the next pending step
                    all_steps_done = True
                    for step in wf.steps:
                        if step.status == "pending":
                            all_steps_done = False
                            # Check if dependencies are met
                            deps_met = all(
                                any(s.step_id == dep and s.status == "done" for s in wf.steps)
                                for dep in step.depends_on
                            )
                            if deps_met:
                                # Check conditional branching
                                if step.condition:
                                    condition_met = engine.evaluate_condition(
                                        step.condition, run.get("context", {})
                                    )
                                    if not condition_met:
                                        # Skip this step (mark as skipped)
                                        engine.advance_step(run["run_id"], step.step_id, "skipped")
                                        logger.info(
                                            "AmbientLoop: skipped workflow '%s' step '%s' (condition not met)",
                                            wf.name,
                                            step.title,
                                        )
                                        continue

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

                    # FRIDAY: Check if completed workflow should chain to next
                    if all_steps_done and run.get("status") != "done":
                        engine.advance_step(run["run_id"], "", "done")
                        next_wf = engine.check_chain(run)
                        if next_wf:
                            engine.start_run(next_wf, context=run.get("context", {}))
                            logger.info(
                                "AmbientLoop: chained workflow '%s' → '%s'",
                                run.get("workflow_id"),
                                next_wf,
                            )

        except Exception as exc:
            logger.debug("AmbientLoop: workflow tick skipped — %s", exc)

    # ── Autonomous Action Engine (FRIDAY) ───────────────────────────

    async def _tick_autonomous_actions(self) -> None:
        """Feed events into the autonomous action engine and process pending actions."""
        try:
            from app.core.autonomous_engine import AutonomousActionEngine, Event

            if not hasattr(self, "_autonomous_engine"):
                self._autonomous_engine = AutonomousActionEngine(self._botsignal)

            engine = self._autonomous_engine

            # Feed sensor events from MQTT listener
            try:
                from app.sensors.mqtt_listener import get_recent_readings

                readings = get_recent_readings()
                for reading in readings:
                    event = Event(
                        event_type=f"sensor_{reading.get('topic', 'unknown')}",
                        source=reading.get("topic", "mqtt"),
                        data=reading,
                        urgency=0.3,
                    )
                    await engine.process_event(event)
            except Exception:
                pass  # No sensor readings available

            # Feed system health anomalies
            try:
                if hasattr(self, "_last_health_check"):
                    # Check if any services are down
                    from app.core.health import HealthMonitor

                    monitor = HealthMonitor()
                    health = await monitor.check_all()
                    for name, service_health in health.items():
                        if (
                            hasattr(service_health, "status")
                            and service_health.status.value == "down"
                        ):
                            event = Event(
                                event_type=f"system_anomaly_{name}",
                                source="health_monitor",
                                data={"service": name, "status": "down"},
                                urgency=0.7,
                            )
                            await engine.process_event(event)
            except Exception:
                pass

            # Process any pending actions
            pending = engine.get_pending_actions()
            if pending:
                logger.info("AutonomousEngine: %d actions pending approval", len(pending))
        except Exception as exc:
            logger.debug("AmbientLoop: autonomous actions skipped — %s", exc)

    # ── Live Data Feeds (FRIDAY) ────────────────────────────────────

    async def _tick_live_feeds(self) -> None:
        """Check live data feeds for new alerts."""
        try:
            from app.core.live_feeds import LiveDataManager

            if not hasattr(self, "_live_feeds"):
                self._live_feeds = LiveDataManager()

            alerts = await self._live_feeds.check_all()
            for alert in alerts:
                if alert.urgency >= 0.6:
                    logger.info(
                        "LiveFeed alert: [%s] %s — %s",
                        alert.feed_type,
                        alert.title,
                        alert.summary[:80],
                    )
        except Exception as exc:
            logger.debug("AmbientLoop: live feeds skipped — %s", exc)

    # ── Dashboard Heartbeat ────────────────────────────────────────────

    async def _broadcast_heartbeat(self) -> None:
        """Send periodic heartbeat to all dashboard WebSocket subscribers."""
        try:
            from app.api.server import broadcast_event

            uptime = time.time() - self._start_time
            await broadcast_event(
                {
                    "event": "ambient_heartbeat",
                    "tick": self._tick_count,
                    "uptime_seconds": int(uptime),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        except Exception:
            pass  # Dashboard may not be running

        # ── Phase 2.6: also publish an envelope on the in-proc bus ──
        # Hot-path metric — under 1µs when no subscribers; bus never
        # raises. The envelope can be picked up by a future
        # telemetry sink or sidecar exporter without going through
        # the signed JSON-over-IPC path.
        try:
            from app.core.events import EventKind, make_envelope
            from app.core.inproc_bus import get_inproc_bus

            uptime = time.time() - self._start_time
            env = make_envelope(
                kind=EventKind.HEALTH,
                source="ambient_loop",
                body={
                    "tick": self._tick_count,
                    "uptime_seconds": int(uptime),
                },
            )
            await get_inproc_bus().publish("ambient.heartbeat", env)
        except Exception:
            pass  # Bus is best-effort; never break the loop

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
                # v33 (2026-06-22): demote this to INFO.  A
                # fresh install that hasn't configured Ollama /
                # HomeAssistant will see this on every 5-min tick
                # and it drowns the rest of the log.  The health
                # data is still surfaced on the dashboard via
                # the same broadcast_event payload below.
                logger.info(
                    "AmbientLoop: %d service(s) DOWN: %s",
                    summary["down"],
                    down,
                )

                # Broadcast to dashboard
                try:
                    from app.api.server import broadcast_event

                    await broadcast_event(
                        {
                            "event": "health_alert",
                            "severity": "HIGH",
                            "down_services": summary["down_services"],
                            "summary": summary,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    )
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

    # ── Memory Auto-Update (Phase 0.3) ───────────────────────────

    async def _tick_memory_update(self) -> None:
        """Auto-write MEMORY.md from LifeContextEngine.

        Runs at most every _MEMORY_UPDATE_INTERVAL (default 10 min).
        Bounded to a single LLM call ≤ 1k tokens output.
        Failure is silent (warned) — never crashes the loop.
        """
        try:
            from app.core.auto_memory import AutoMemoryUpdater
            from app.core.life_context import get_life_context_engine

            engine = get_life_context_engine()
            # LifeContextEngine stores a single shared context — use "default".
            user_id = "default"
            context = engine.get_context(user_id)
            if context is None:
                logger.debug("AmbientLoop: memory update skipped — no context available")
                return

            updater = AutoMemoryUpdater()
            updater.update_memory_from_context(user_id, context)
            logger.info("AmbientLoop: MEMORY.md auto-updated")
        except Exception as exc:
            logger.warning("AmbientLoop: memory update failed — %s", exc)

    # ── Proactive Intelligence gate (Phase 2 wiring) ─────────────

    async def _tick_proactive_intelligence(self) -> None:
        """Generate proactive insights and dispatch them to users.

        This is the core "intelligence" tick that makes Raven feel alive.
        It generates context-aware insights and dispatches them via botsignal.
        """
        try:
            from app.core.proactive_intelligence import (
                get_proactive_intelligence,
                ProactiveCandidate,
            )
        except Exception as exc:
            logger.debug("AmbientLoop: proactive modules missing — %s", exc)
            return

        engine = get_proactive_intelligence()

        # Build context for insight generation
        context: dict[str, Any] = {}
        try:
            from app.core.context_awareness import get_context_awareness

            awareness = get_context_awareness()
            # Get context for default user
            engine_ctx = awareness._get_engine()
            ctx = engine_ctx.get_context("default")
            if ctx:
                context["mood"] = getattr(ctx, "current_mood", "") or ""
                context["activity"] = getattr(ctx, "current_activity", "") or ""
                context["overdue_tasks"] = getattr(ctx, "overdue_tasks", []) or []
                context["pending_tasks"] = getattr(ctx, "today_tasks", []) or []
        except Exception:
            pass

        # Generate insights from patterns
        insights = await engine.analyze(context)

        # Dispatch high-urgency insights
        for insight in insights:
            if insight.urgency >= 0.5 and insight.confidence >= 0.5:
                candidate = ProactiveCandidate(
                    channel="proactive",
                    topic=insight.insight_type,
                    body=f"**{insight.title}**\n{insight.description}",
                    priority="high" if insight.urgency >= 0.7 else "normal",
                )
                decision = engine.evaluate(candidate)
                self._recent_decisions.append(
                    {
                        "channel": decision.candidate.channel,
                        "topic": decision.candidate.topic,
                        "emit": decision.emit,
                        "reason": decision.reason,
                        "gates": dict(decision.gates),
                        "decided_at": decision.decided_at,
                    }
                )
                if decision.emit:
                    await self._dispatch_emitted(decision.candidate)

        # Prediction-based proactive insights
        try:
            from app.core.prediction.orchestrator import get_prediction_orchestrator

            pred_orch = get_prediction_orchestrator()
            # Quick forecast to detect anomalies or opportunities
            forecast = await pred_orch.comprehensive_forecast(horizon_hours=6)
            if forecast and forecast.get("status") == "success":
                components = forecast.get("components", {})
                # Check for anomalies in schedule
                schedule_forecast = components.get("schedule", {})
                if schedule_forecast and schedule_forecast.get("anomalies"):
                    for anomaly in schedule_forecast["anomalies"][:2]:
                        candidate = ProactiveCandidate(
                            channel="proactive",
                            topic="prediction_anomaly",
                            body=f"**Schedule Anomaly Detected**\n{anomaly}",
                            priority="normal",
                        )
                        decision = engine.evaluate(candidate)
                        if decision.emit:
                            await self._dispatch_emitted(decision.candidate)
                # Check for high-impact scenarios
                scenario = await pred_orch.run_scenario_analysis(
                    event="Next 6 hours"
                )
                if scenario and scenario.get("status") == "success":
                    scenarios = scenario.get("scenarios", [])
                    high_impact = [
                        s for s in scenarios
                        if s.get("impact_score", 0) > 0.7
                    ]
                    for s in high_impact[:1]:
                        candidate = ProactiveCandidate(
                            channel="proactive",
                            topic="prediction_scenario",
                            body=f"**High Impact Scenario**\n{s.get('name', 'Unknown')}: {s.get('description', '')}",
                            priority="high",
                        )
                        decision = engine.evaluate(candidate)
                        if decision.emit:
                            await self._dispatch_emitted(decision.candidate)
        except Exception as exc:
            logger.debug("AmbientLoop: prediction insights skipped — %s", exc)

    async def _dispatch_emitted(self, candidate: Any) -> None:
        """Send an emitted candidate to the production sink.

        Default sink is the :class:`BotSignal` queue passed at
        construction time.  If no botsignal was supplied, the
        emit is logged so the operator can wire a sink later.
        """
        if self._botsignal is None:
            logger.info(
                "AmbientLoop: proactive emit (no sink wired) — channel=%s topic=%s body=%s",
                candidate.channel,
                candidate.topic,
                candidate.body,
            )
            return
        try:
            self._botsignal.send(
                channel=candidate.channel,
                topic=candidate.topic,
                body=candidate.body,
                priority=candidate.priority,
                metadata=candidate.metadata,
            )
        except Exception as exc:  # noqa: BLE001 - sink failure
            logger.warning(
                "AmbientLoop: botsignal send failed (%s) — %s",
                candidate.topic,
                exc,
            )

    @property
    def recent_decisions(self) -> list[dict[str, Any]]:
        """Return (and DO NOT clear) the recent decisions list.

        Use :meth:`drain_decisions` if you want to consume the
        queue.  The decision dicts are plain JSON-safe types.
        """
        return list(self._recent_decisions)

    def drain_decisions(self) -> list[dict[str, Any]]:
        """Return and clear the recent decisions queue.

        Used by the audit-log writer and the integration tests
        that want to assert on the latest tick's decisions without
        accumulating state across ticks.
        """
        out = list(self._recent_decisions)
        self._recent_decisions.clear()
        return out

    # ── Knowledge sync (Phase 4 wiring) ─────────────────────────

    async def _tick_knowledge_sync(self) -> None:
        """Pull typed life-context fields into the knowledge graph.

        Calls :meth:`KnowledgeManager.sync_from_life_context` and
        records the resulting facts to
        :attr:`recent_kb_writes` for the audit log.  Failure is
        silent (warned) so a KG outage never crashes the
        ambient heartbeat.
        """
        try:
            from app.core.knowledge_manager import get_knowledge_manager
        except Exception as exc:  # noqa: BLE001 - optional
            logger.debug("AmbientLoop: knowledge_manager missing — %s", exc)
            return
        try:
            mgr = get_knowledge_manager()
            # The sync is synchronous and idempotent; new triples
            # surface via drain_recent_writes().
            mgr.sync_from_life_context("default")
            for f in mgr.drain_recent_writes():
                self._recent_kb_writes.append(
                    {
                        "subject": f.subject,
                        "predicate": f.predicate,
                        "object": f.object,
                        "source": f.source,
                        "ts": f.timestamp,
                        "backend": mgr.backend,
                    }
                )
            logger.debug(
                "AmbientLoop: knowledge sync wrote %d new triples (backend=%s)",
                len(self._recent_kb_writes),
                mgr.backend,
            )
        except Exception as exc:  # noqa: BLE001 - KG outage
            logger.warning("AmbientLoop: knowledge sync failed — %s", exc)

    @property
    def recent_kb_writes(self) -> list[dict[str, Any]]:
        """Return (and DO NOT clear) the recent KB writes list."""
        return list(self._recent_kb_writes)

    def drain_kb_writes(self) -> list[dict[str, Any]]:
        """Return and clear the recent KB writes queue."""
        out = list(self._recent_kb_writes)
        self._recent_kb_writes.clear()
        return out

    # ── Learning summary (Phase 4 v10) ─────────────────────────

    async def _tick_learning_summary(self) -> None:
        """Refresh the LearningTracker view on a 1-hour cadence.

        The tracker is read-only and read-time (no caching), so
        the tick is cheap: build a :class:`LearningSummary`,
        append the lightweight metrics (skill_count, tool
        totals, velocity) to :attr:`recent_learning_summaries`
        for the audit log, and the full text render to the
        logger for an at-a-glance hourly heartbeat.

        Failure is silent (warned) so an audit-log outage never
        crashes the ambient heartbeat.
        """
        try:
            from app.core.learning_tracker import get_learning_tracker
        except Exception as exc:  # noqa: BLE001 - optional
            logger.debug(
                "AmbientLoop: learning_tracker missing — %s",
                exc,
            )
            return
        try:
            tracker = get_learning_tracker()
            summary = tracker.summary()
            entry = {
                "generated_at": summary.generated_at,
                "skill_count": summary.skill_count,
                "total_tool_calls": summary.total_tool_calls,
                "overall_success_rate": summary.overall_success_rate,
                "velocity_30d": summary.velocity_30d,
                "top_failure": (
                    summary.failure_modes[0].to_dict() if summary.failure_modes else None
                ),
            }
            self._recent_learning_summaries.append(entry)
            logger.info(
                "AmbientLoop: learning summary — %d skills, %d tool calls, "
                "%.1f%% success, velocity_30d=%d",
                summary.skill_count,
                summary.total_tool_calls,
                summary.overall_success_rate * 100,
                summary.velocity_30d,
            )
        except Exception as exc:  # noqa: BLE001 - audit outage
            logger.warning(
                "AmbientLoop: learning summary failed — %s",
                exc,
            )

    @property
    def recent_learning_summaries(self) -> list[dict[str, Any]]:
        """Return (and DO NOT clear) the recent learning summaries."""
        return list(self._recent_learning_summaries)

    def drain_learning_summaries(self) -> list[dict[str, Any]]:
        """Return and clear the recent learning summaries queue."""
        out = list(self._recent_learning_summaries)
        self._recent_learning_summaries.clear()
        return out

    # ── Presence refresh (Phase 4 v11) ─────────────────────

    async def _tick_presence_refresh(self) -> None:
        """Snapshot the current presence + matching scene.

        The tick is read-only — it does not set presence, it
        records what the orchestrator currently knows.  This
        is the audit-log source for "where was the user at
        time T and what scene was active for that location".

        Failure is silent (warned) so a missing orchestrator
        never crashes the ambient heartbeat.
        """
        try:
            from app.core.home_orchestrator import get_home_orchestrator
        except Exception as exc:  # noqa: BLE001 - optional
            logger.debug(
                "AmbientLoop: home_orchestrator missing — %s",
                exc,
            )
            return
        try:
            orchestrator = get_home_orchestrator()
            presence = orchestrator.get_presence()
            if presence is None:
                # No presence yet — record an empty snapshot
                # so the audit log can see the loop is alive
                # and the user has not set a location.
                self._recent_presence_snapshots.append(
                    {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "location": None,
                        "scene": None,
                    }
                )
                return
            scene = orchestrator.current_scene_for_presence()
            self._recent_presence_snapshots.append(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "location": presence.location,
                    "arrived_at": presence.arrived_at,
                    "source": presence.source,
                    "scene": scene.name if scene else None,
                }
            )
            logger.debug(
                "AmbientLoop: presence=%s scene=%s",
                presence.location,
                scene.name if scene else "(none)",
            )
        except Exception as exc:  # noqa: BLE001 - outage
            logger.warning(
                "AmbientLoop: presence refresh failed — %s",
                exc,
            )

    @property
    def recent_presence_snapshots(self) -> list[dict[str, Any]]:
        """Return (and DO NOT clear) the recent presence snapshots."""
        return list(self._recent_presence_snapshots)

    def drain_presence_snapshots(self) -> list[dict[str, Any]]:
        """Return and clear the recent presence snapshots queue."""
        out = list(self._recent_presence_snapshots)
        self._recent_presence_snapshots.clear()
        return out

    # ── CronEngine tick (Phase 5 v13) ──────────────────────────────

    async def _tick_cron(self) -> None:
        """Drive the dynamic :class:`CronEngine` scheduler.

        On each tick, the engine evaluates all enabled jobs and
        fires the ones that are due (``daily_at`` whose HH:MM
        matches the current minute, or ``interval_minutes``
        whose interval has elapsed since the last fire).  We
        diff the jobs state before and after the tick to record
        which ones actually fired into
        :attr:`recent_cron_fires` for the audit log.

        Failure is silent (warned) so a malformed ``cron.json``
        or a single bad job never crashes the ambient
        heartbeat.
        """
        try:
            from app.core.cron_engine import CronEngine
        except Exception as exc:  # noqa: BLE001 - optional
            logger.debug("AmbientLoop: cron_engine missing — %s", exc)
            return
        try:
            engine = CronEngine()
            # Snapshot which jobs are enabled *before* the tick
            # so we can diff which ones actually fired (last_run
            # timestamps advance on fire).
            before = {j.get("job_id"): j for j in engine.get_jobs() if j.get("enabled", False)}
            await engine.tick_all()
            after = {j.get("job_id"): j for j in engine.get_jobs() if j.get("enabled", False)}
            for jid, before_job in before.items():
                after_job = after.get(jid)
                if after_job is None:
                    # Disabled by an external writer between ticks.
                    continue
                fired = self._job_fired(before_job, after_job)
                if fired:
                    self._recent_cron_fires.append(
                        {
                            "ts": datetime.now(timezone.utc).isoformat(),
                            "job_id": jid,
                            "name": after_job.get("name"),
                            "schedule_type": after_job.get("schedule_type"),
                            "action_type": (after_job.get("action", {}).get("type")),
                        }
                    )
            logger.debug(
                "AmbientLoop: cron tick — %d fire(s) recorded",
                sum(
                    1 for jid in before if jid in after and self._job_fired(before[jid], after[jid])
                ),
            )
        except Exception as exc:  # noqa: BLE001 - cron outage
            logger.warning("AmbientLoop: cron tick failed — %s", exc)

    @staticmethod
    def _job_fired(before: dict[str, Any], after: dict[str, Any]) -> bool:
        """Return True if the job's run timestamp advanced."""
        schedule = after.get("schedule_type")
        if schedule == "daily_at":
            return after.get("last_run_day", -1) != before.get("last_run_day", -1)
        if schedule == "interval_minutes":
            return after.get("last_run_ts", 0.0) > before.get("last_run_ts", 0.0)
        return False

    @property
    def recent_cron_fires(self) -> list[dict[str, Any]]:
        """Return (and DO NOT clear) the recent cron fires list."""
        return list(self._recent_cron_fires)

    def drain_cron_fires(self) -> list[dict[str, Any]]:
        """Return and clear the recent cron fires queue."""
        out = list(self._recent_cron_fires)
        self._recent_cron_fires.clear()
        return out

    # ── Nudge engine (FRIDAY proactive reminders) ────────────────────

    async def _tick_nudges(self) -> None:
        """Check nudge engine and dispatch proactive reminders."""
        try:
            from app.core.nudge_engine import get_nudge_engine

            engine = get_nudge_engine()

            context: dict[str, Any] = {}
            if self._orchestrator and hasattr(self._orchestrator, "runtime"):
                runtime = self._orchestrator.runtime
                if hasattr(runtime, "task_inbox"):
                    pending = runtime.task_inbox.list_items(status="open")
                    context["pending_tasks"] = [i.title for i in pending[:10]]
                    overdue = runtime.task_inbox.list_items(status="overdue")
                    context["overdue_tasks"] = [i.title for i in overdue[:5]]

            nudges = engine.generate_nudges(context)
            for nudge in nudges:
                if self._botsignal:
                    await self._botsignal.send_text(
                        nudge.message,
                        channel="proactive",
                    )
                    engine.mark_sent(nudge.nudge_type)
                logger.debug("AmbientLoop: nudge dispatched — %s", nudge.nudge_type)
        except Exception as exc:
            logger.debug("AmbientLoop: nudge tick skipped — %s", exc)

    # ── Working memory decay ───────────────────────────────────────

    async def _tick_working_memory_decay(self) -> None:
        """Apply relevance decay to working memory items."""
        try:
            from app.core.attention import WorkingMemory

            wm = WorkingMemory()
            removed = wm.apply_decay()
            if removed:
                logger.debug("AmbientLoop: working memory decay removed %d items", removed)
        except Exception as exc:
            logger.debug("AmbientLoop: working memory decay skipped — %s", exc)

    async def _tick_companion_discovery(self) -> None:
        """Discover and register companion AIs via A2A protocol."""
        try:
            from app.core.companion_ai import get_companion_manager

            manager = get_companion_manager()
            # Discover companions from the A2A module registry
            from raven_protocol import get_registry

            registry = get_registry()
            for card in registry.list_cards():
                if card.name not in [c.name for c in manager.list_companions()]:
                    from app.core.companion_ai import CompanionAI

                    companion = CompanionAI(
                        name=card.name,
                        description=card.description,
                        capabilities=[s.name for s in card.skills],
                        status="connected",
                    )
                    manager.register_companion(companion)
            summary = manager.get_collaboration_summary()
            if summary["connected_companions"] > 0:
                logger.debug(
                    "AmbientLoop: companion discovery — %d companions connected",
                    summary["connected_companions"],
                )
        except Exception as exc:
            logger.debug("AmbientLoop: companion discovery skipped — %s", exc)

    async def _tick_training_data(self) -> None:
        """Auto-export recent sessions as training data."""
        try:
            from app.core.session import SessionManager
            from app.core.training_data import TrajectoryCompressor

            sm = SessionManager()
            sessions = sm.list_sessions()
            if not sessions:
                return

            compressor = TrajectoryCompressor()
            all_examples = []
            for sess in sessions[-20:]:
                messages = [
                    {"role": "user", "content": sess.get("user_text", "")},
                    {"role": "assistant", "content": sess.get("response_text", "")},
                ]
                examples, _ = compressor.compress(messages, force=True)
                for ex in examples:
                    if ex.get("role") == "user" and ex.get("content"):
                        all_examples.append(ex)

            if all_examples:
                import time as _time

                out_path = f"workspace/training_data/auto_{int(_time.time())}.jsonl"
                from pathlib import Path as _Path

                _Path(out_path).parent.mkdir(parents=True, exist_ok=True)
                import json as _json

                with open(out_path, "w", encoding="utf-8") as f:
                    for ex in all_examples:
                        f.write(
                            _json.dumps(
                                {"instruction": ex.get("content", ""), "output": ""},
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                logger.debug("AmbientLoop: auto-exported %d training examples", len(all_examples))
        except Exception as exc:
            logger.debug("AmbientLoop: training data export skipped — %s", exc)

    async def _tick_agent_heartbeats(self) -> None:
        """Run agent heartbeat() methods for background work.

        Agents can use heartbeats to:
        - Check for new data to process
        - Update their internal state
        - Clean up stale data
        - Report health status
        """
        try:
            from app.core.agency import get_swarm_manager

            swarm = get_swarm_manager()
            agents = getattr(swarm, "_agents", {})
            for name, agent in agents.items():
                try:
                    if hasattr(agent, "heartbeat") and callable(agent.heartbeat):
                        result = agent.heartbeat()
                        if asyncio.iscoroutine(result):
                            await result
                        logger.debug("AmbientLoop: agent %s heartbeat OK", name)
                except Exception as exc:
                    logger.debug("AmbientLoop: agent %s heartbeat failed: %s", name, exc)
        except Exception as exc:
            logger.debug("AmbientLoop: agent heartbeats skipped — %s", exc)

    # ── Goal advancement ────────────────────────────────────────────

    async def _tick_goals(self) -> None:
        """Advance active goals — check progress and advance subtasks."""
        try:
            from app.core.goal_manager import get_goal_manager

            gm = get_goal_manager()
            goals = gm.list_goals() if hasattr(gm, "list_goals") else []
            active = [
                g
                for g in goals
                if hasattr(g, "status") and str(getattr(g, "status", "")) == "GoalStatus.ACTIVE"
            ]
            if active:
                logger.debug("AmbientLoop: %d active goals tracked", len(active))
        except Exception as exc:
            logger.debug("AmbientLoop: goal advance skipped — %s", exc)

    # ── Resilience health check ─────────────────────────────────────

    async def _tick_resilience(self) -> None:
        """Check service health and apply fallbacks if needed."""
        try:
            from app.core.resilient_recovery import get_resilience_manager

            rm = get_resilience_manager()
            if hasattr(rm, "check_all"):
                rm.check_all()
            logger.debug("AmbientLoop: resilience check done")
        except Exception as exc:
            logger.debug("AmbientLoop: resilience check skipped — %s", exc)

    # ── Predictive scheduling ───────────────────────────────────────

    async def _tick_predictive_schedule(self) -> None:
        """Generate schedule suggestions from learned patterns."""
        try:
            from app.core.predictive_scheduler import PredictiveScheduler

            ps = PredictiveScheduler()
            if hasattr(ps, "suggest_schedule"):
                suggestions = ps.suggest_schedule()
                if suggestions:
                    logger.debug("AmbientLoop: %d schedule suggestions generated", len(suggestions))
        except Exception as exc:
            logger.debug("AmbientLoop: predictive schedule skipped — %s", exc)

    # ── Forecast update ─────────────────────────────────────────────

    async def _tick_forecast(self) -> None:
        """Update predictive forecasts using the full prediction orchestrator."""
        try:
            from app.core.prediction.orchestrator import get_prediction_orchestrator

            orchestrator = get_prediction_orchestrator()
            # Run a lightweight 12-hour forecast every tick
            result = await orchestrator.comprehensive_forecast(horizon_hours=12)
            if result and result.get("status") == "success":
                forecasts = result.get("components", {})
                n_forecasts = sum(1 for v in forecasts.values() if v)
                logger.debug(
                    "AmbientLoop: prediction orchestrator forecast — %d components generated",
                    n_forecasts,
                )
            else:
                logger.debug("AmbientLoop: prediction forecast returned status=%s", result.get("status", "unknown"))
        except Exception as exc:
            logger.debug("AmbientLoop: prediction forecast skipped — %s", exc)

    # ── Perception scan ─────────────────────────────────────────────

    async def _tick_perception(self) -> None:
        """Scan environment for new patterns and evidence, then store findings."""
        try:
            from app.core.perception import PerceptionEngine
            from app.core.learning_db import get_learning_store

            pe = PerceptionEngine()
            if hasattr(pe, "scan"):
                results = pe.scan()
                # Store perception results in learning DB for later use
                if results:
                    store = get_learning_store()
                    for item in (results if isinstance(results, list) else [results]):
                        if isinstance(item, dict):
                            store.add_event(
                                kind="perception",
                                payload=item,
                                source="ambient_loop",
                            )
                    logger.debug(
                        "AmbientLoop: perception scan stored %d findings",
                        len(results) if isinstance(results, list) else 1,
                    )
            else:
                logger.debug("AmbientLoop: perception engine has no scan method")
        except Exception as exc:
            logger.debug("AmbientLoop: perception scan skipped — %s", exc)

    async def _tick_a2a_servers(self) -> None:
        """Check A2A module server health."""
        try:
            from app.core.agent_a2a_server import AgentA2AServer

            _s = AgentA2AServer()
            logger.debug("AmbientLoop: A2A server check done")
        except Exception as exc:
            logger.debug("AmbientLoop: A2A server check skipped — %s", exc)

    async def _tick_eval(self) -> None:
        """Run evaluation harness."""
        try:
            from app.core.eval import EvaluationHarness

            eh = EvaluationHarness()
            if hasattr(eh, "run"):
                eh.run()
            logger.debug("AmbientLoop: eval harness done")
        except Exception as exc:
            logger.debug("AmbientLoop: eval harness skipped — %s", exc)

    async def _tick_regression(self) -> None:
        """Check for regressions."""
        try:
            from app.core.regression import RegressionSuite

            rs = RegressionSuite()
            if hasattr(rs, "check"):
                rs.check()
            logger.debug("AmbientLoop: regression check done")
        except Exception as exc:
            logger.debug("AmbientLoop: regression check skipped — %s", exc)

    async def _tick_degradation(self) -> None:
        """Check for service degradation."""
        try:
            from app.core.degraded_mode import DegradationDetector

            dd = DegradationDetector()
            if hasattr(dd, "check"):
                dd.check()
            logger.debug("AmbientLoop: degradation check done")
        except Exception as exc:
            logger.debug("AmbientLoop: degradation check skipped — %s", exc)

    async def _tick_environmental(self) -> None:
        """Poll environmental sensors."""
        try:
            from app.core.environmental_sensors import EnvironmentalSensor

            es = EnvironmentalSensor()
            if hasattr(es, "read_sensors"):
                es.read_sensors()
            logger.debug("AmbientLoop: environmental sensors done")
        except Exception as exc:
            logger.debug("AmbientLoop: environmental sensors skipped — %s", exc)

    async def _tick_multimodal(self) -> None:
        """Process multimodal inputs and cache the context for the next turn."""
        try:
            from app.core.multimodal_retrieval import MultimodalRetriever
            from app.core.multimodal_understanding import MultiModalProcessor
            from app.core.unified_multimodal import get_unified_context_builder

            mr = MultimodalRetriever()
            mp = MultiModalProcessor()
            # Build a unified context snapshot from all modalities
            builder = get_unified_context_builder()
            context_snapshot = builder.build()
            if context_snapshot:
                # Cache the snapshot so the next turn can use it
                self._last_multimodal_context = context_snapshot
                logger.debug(
                    "AmbientLoop: multimodal context cached — tokens=%d",
                    context_snapshot.get("total_tokens", 0),
                )
            else:
                logger.debug("AmbientLoop: multimodal processing done (no context)")
        except Exception as exc:
            logger.debug("AmbientLoop: multimodal processing skipped — %s", exc)

    async def _tick_event_digest(self) -> None:
        """Aggregate events from all sources into a digest and store it."""
        try:
            from app.core.event_digest import EventDigest
            from app.core.learning_db import get_learning_store

            ed = EventDigest()
            if hasattr(ed, "flush"):
                ed.flush()
            # Also aggregate recent learning events into a digest
            store = get_learning_store()
            recent_events = store.get_recent_events(limit=50) if hasattr(store, "get_recent_events") else []
            if recent_events:
                # Group by kind and count
                kind_counts: dict[str, int] = {}
                for ev in recent_events:
                    kind = ev.get("kind", "unknown") if isinstance(ev, dict) else "unknown"
                    kind_counts[kind] = kind_counts.get(kind, 0) + 1
                # Store the digest summary
                store.add_event(
                    kind="event_digest",
                    payload={
                        "total_events": len(recent_events),
                        "by_kind": kind_counts,
                        "period": "since_last_tick",
                    },
                    source="ambient_loop",
                )
                logger.debug(
                    "AmbientLoop: event digest aggregated %d events across %d kinds",
                    len(recent_events),
                    len(kind_counts),
                )
            else:
                logger.debug("AmbientLoop: event digest done (no recent events)")
        except Exception as exc:
            logger.debug("AmbientLoop: event digest skipped — %s", exc)

    async def _tick_self_evolution(self) -> None:
        """Run self-evolution: compute adjustments, auto-generate goals, consolidate skills, log report."""
        try:
            from app.core.self_evolution import get_self_evolution
            from app.core.skill_learner import get_skill_learner
            
            # Prune and consolidate learned skills
            learner = get_skill_learner()
            if learner:
                learner.consolidate_skills()

            se = get_self_evolution()
            adjustments = se.compute_adjustments()
            assessment = se.assess()
            logger.info(
                "AmbientLoop: self-evolution — tools_tracked=%d  avg_success=%.1f%%  adjustments=%d",
                assessment.get("tools_tracked", 0),
                assessment.get("avg_tool_success", 0) * 100,
                len(adjustments),
            )
            # Auto-generate goals when metrics show improvement areas
            if (
                assessment.get("avg_tool_success", 1.0) < 0.7
                and assessment.get("tools_tracked", 0) > 3
            ):
                active = se.get_active_goals()
                has_goal = any("tool reliability" in g.title.lower() for g in active)
                if not has_goal:
                    from app.core.self_evolution import EvolutionGoal

                    se.add_goal(
                        EvolutionGoal(
                            goal_id="improve_tool_reliability",
                            title="Improve tool reliability to 80%",
                            description="Average tool success rate is below target",
                            category="tool_usage",
                            target_metric="avg_tool_success",
                            target_value=0.8,
                        )
                    )
            # Record overall system health metric
            sat = assessment.get("avg_satisfaction", 0)
            if sat > 0:
                se.record_metric("system_health", sat / 5.0)
        except Exception as exc:
            logger.debug("AmbientLoop: self-evolution skipped — %s", exc)

    async def _tick_notification_retry(self) -> None:
        """Retry delivering pending notifications (botsignal fallback → email fallback)."""
        try:
            from app.core.notification_manager import get_notification_manager

            nm = get_notification_manager()
            pending = nm.get_pending_count()
            if pending > 0:
                delivered = nm.retry_delivery()
                logger.debug(
                    "AmbientLoop: notification retry — %d pending, %d delivered", pending, delivered
                )
        except Exception as exc:
            logger.debug("AmbientLoop: notification retry skipped — %s", exc)

    # ── Curiosity-Driven Exploration ─────────────────────────────────

    async def _tick_curiosity(self) -> None:
        """Identify and fill knowledge gaps via curiosity-driven exploration.

        Scans the knowledge graph for sparse entities and thin domains,
        picks the highest-importance gap, and either promotes it to a
        GoalManager goal or explores it directly via web search.
        """
        try:
            from app.core.curiosity import get_curiosity_module
            from app.core.goal_manager import GoalManager
            from app.core.knowledge_manager import get_knowledge_manager
        except Exception as exc:
            logger.debug("AmbientLoop: curiosity modules missing — %s", exc)
            return

        try:
            curiosity = get_curiosity_module()
            kg = get_knowledge_manager()

            # Wire dependencies that weren't available at singleton init
            goal_manager = GoalManager()
            curiosity._goal_manager = goal_manager
            curiosity._kg_manager = kg

            # Identify gaps
            gaps = await curiosity.identify_gaps()
            if not gaps:
                logger.debug("AmbientLoop: curiosity — no gaps found")
                return

            # Pick the most important gap
            best = gaps[0]
            logger.info(
                "AmbientLoop: curiosity — gap found: %s (importance=%.2f, source=%s)",
                best.domain,
                best.importance,
                best.source,
            )

            # If high importance, create a goal for systematic pursuit
            if best.importance >= 0.7:
                goal_id = await curiosity.promote_to_goal(best)
                if goal_id:
                    logger.info(
                        "AmbientLoop: curiosity — promoted '%s' to goal %s",
                        best.domain,
                        goal_id,
                    )

            # Explore directly
            result = await curiosity.execute_exploration(best)
            if result.success:
                logger.info(
                    "AmbientLoop: curiosity — explored '%s': %d facts written",
                    best.domain,
                    result.facts_written,
                )
            else:
                logger.debug(
                    "AmbientLoop: curiosity — exploration of '%s' failed: %s",
                    best.domain,
                    result.summary,
                )

        except Exception as exc:
            logger.debug("AmbientLoop: curiosity tick skipped — %s", exc)


# ── Module singleton ───────────────────────────────────────────────────

_LOOP: AmbientLoop | None = None


def get_ambient_loop() -> AmbientLoop:
    global _LOOP
    if _LOOP is None:
        _LOOP = AmbientLoop()
    return _LOOP
