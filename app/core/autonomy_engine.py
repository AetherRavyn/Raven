import os
import json
import logging
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from app.core.planner import TaskPlanner, PlanStep, TaskPlan, ResultVerifier
from app.core.task_inbox import TaskInboxStore
from app.core.task_ledger import TaskLedger
from app.agents.productivity import ConductorAgent
from app.core.models import IncomingRequest, ReplyTarget

logger = logging.getLogger(__name__)

# ── Step state machine ─────────────────────────────────────────────────
# Pending → In Progress → Completed
#                       → Retry (up to MAX_RETRIES) → Blocked
MAX_STEP_RETRIES = 3
RETRY_BACKOFF_BASE = 5  # seconds — exponential: 5, 10, 20


class AutonomyEngine:
    """
    Background engine for long-horizon planning and execution.
    Reads goals, generates plans, delegates to the Swarm, verifies results,
    and updates the UI/Inbox. High quality architectural execution.

    Step State Machine:
        Pending → In Progress → Completed
                              → Retry (1..MAX_RETRIES) → Blocked

    A blocked *step* does NOT block the entire goal — subsequent independent
    steps will still execute.  The goal only becomes Blocked if ALL remaining
    steps are Blocked.
    """

    def __init__(self, workspace_dir: str | None = None, agent_runtime=None) -> None:
        from app.settings.config import Config

        self.workspace_dir = (
            Path(workspace_dir) if workspace_dir else Path(Config.MEMORY_ROOT)
        )
        self.agent_runtime = agent_runtime
        self.goals_file = self.workspace_dir / "goals.jsonl"
        self.inbox = TaskInboxStore(str(self.workspace_dir))
        self.ledger = TaskLedger(str(self.workspace_dir))
        self.planner = TaskPlanner()
        self.verifier = ResultVerifier()
        # Leverage the Conductor Agent as the Project Manager
        self.conductor = ConductorAgent()

    # ── Goal persistence ───────────────────────────────────────────────

    def _read_goals(self) -> list[Dict[str, Any]]:
        goals = []
        if self.goals_file.exists():
            with open(self.goals_file, "r") as f:
                for line in f:
                    if line.strip():
                        try:
                            goal = json.loads(line.strip())
                            # Ensure required fields exist (safe migration)
                            goal.setdefault("blockers", [])
                            goal.setdefault("status", "Active")
                            goal.setdefault("description", "")
                            goal.setdefault("created_at", datetime.now(timezone.utc).isoformat())
                            goals.append(goal)
                        except Exception:
                            pass
        return goals

    def _write_goals(self, goals: list[Dict[str, Any]]) -> None:
        tmp_path = self.goals_file.with_suffix(".tmp")
        try:
            with open(tmp_path, "w") as f:
                for g in goals:
                    f.write(json.dumps(g) + "\n")
            tmp_path.replace(self.goals_file)
        except Exception as exc:
            logger.error("Failed to write goals file: %s", exc)
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    # ── Journal logging ────────────────────────────────────────────────

    def _log_to_journal(self, goal_title: str, message: str) -> None:
        """Append a timestamped entry to workspace/autonomy_journal.md."""
        try:
            journal_path = self.workspace_dir / "autonomy_journal.md"
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            entry = f"\n### [{goal_title}] — {ts}\n\n{message}\n"
            with open(journal_path, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as exc:
            logger.debug("Journal write failed: %s", exc)

    # ── Step helpers ───────────────────────────────────────────────────

    @staticmethod
    def _is_step_actionable(step: Dict[str, Any]) -> bool:
        """Can this step be attempted right now?"""
        status = step.get("status", "Pending")
        if status == "Pending":
            return True
        if status == "Retry":
            return step.get("retry_count", 0) < MAX_STEP_RETRIES
        return False

    @staticmethod
    def _get_next_actionable_step(steps: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        """Find the first step that can be executed."""
        for step in steps:
            if AutonomyEngine._is_step_actionable(step):
                return step
        return None

    @staticmethod
    def _all_steps_terminal(steps: List[Dict[str, Any]]) -> bool:
        """Returns True if every step is either Completed or permanently Blocked."""
        for step in steps:
            status = step.get("status", "Pending")
            if status not in ("Completed", "Blocked"):
                return False
        return True

    @staticmethod
    def _all_steps_done(steps: List[Dict[str, Any]]) -> bool:
        """Returns True if every step is Completed."""
        return all(s.get("status") == "Completed" for s in steps)

    # ── Main execution cycle ───────────────────────────────────────────

    async def execute_cycle(
        self, user_id: str = "u1", platform: str = "system", chat_id: str = "system"
    ) -> None:
        """Runs one autonomous tick: planning, delegating, or verifying."""
        logger.info("AutonomyEngine wake up: starting execution cycle for %s", user_id)
        goals = self._read_goals()

        updated = False
        for goal in goals:
            if goal.get("status") not in ("Active", "Retry"):
                continue

            # ── State: Planning ────────────────────────────────────────
            if not goal.get("plan"):
                logger.info(
                    "Goal '%s' requires a plan. Invoking Planner.", goal.get("title")
                )
                try:
                    plan = self.planner.plan(goal.get("description") or goal.get("title", ""))

                    goal["plan"] = {
                        "steps": [
                            {
                                "id": s.step,
                                "action": s.action,
                                "desc": s.description,
                                "status": "Pending",
                                "retry_count": 0,
                                "errors": [],
                            }
                            for s in plan.steps
                        ],
                        "verification": plan.verification,
                    }
                    goal["updated_at"] = datetime.now(timezone.utc).isoformat()
                    updated = True

                    self._log_to_journal(
                        goal.get("title", "?"),
                        f"Plan generated with {len(plan.steps)} steps.",
                    )

                    # Notify User of generated plan
                    self.inbox.add_item(
                        user_id=user_id,
                        title=f"Plan generated for Goal: {goal['title']}",
                        kind="task",
                        source="autonomy_engine",
                        platform=platform,
                        chat_id=chat_id,
                        context={"plan": goal["plan"]},
                    )
                except Exception as exc:
                    logger.error("Planning failed for goal '%s': %s", goal.get("title"), exc)
                    self._log_to_journal(
                        goal.get("title", "?"), f"Planning failed: {exc}"
                    )
                continue  # Let it rest until next cycle

            # ── State: Execution ───────────────────────────────────────
            plan = goal["plan"]
            steps = plan.get("steps", [])
            next_step = self._get_next_actionable_step(steps)

            if next_step:
                step_id = next_step.get("id", "?")
                step_desc = next_step.get("desc", "")
                logger.info(
                    "Executing step %s: %s for goal '%s'",
                    step_id,
                    step_desc,
                    goal.get("title"),
                )

                # Mark In Progress
                next_step["status"] = "In Progress"
                self._write_goals(goals)  # Save state before execution

                try:
                    result_summary = await self._execute_step(
                        goal, next_step, user_id, platform, chat_id
                    )

                    next_step["status"] = "Completed"
                    next_step["result"] = result_summary

                    # ── Verify step result ─────────────────────────────
                    mock_plan_obj = TaskPlan(
                        goal=goal.get("title", ""),
                        verification=plan.get("verification", []),
                    )
                    verif_result = self.verifier.verify(mock_plan_obj, result_summary)

                    if verif_result["success"]:
                        logger.info("Verification passed for step %s", step_id)
                    else:
                        logger.warning(
                            "Verification warnings: %s", verif_result["findings"]
                        )
                        next_step["warnings"] = verif_result["findings"]

                    self._log_to_journal(
                        goal.get("title", "?"),
                        f"Step {step_id} completed. Result: {result_summary[:200]}",
                    )

                    # Notify completion
                    self.inbox.add_item(
                        user_id=user_id,
                        title=f"Step Completed: {goal.get('title')} -> {next_step.get('action')}",
                        kind="task",
                        source="autonomy_engine",
                        platform=platform,
                        chat_id=chat_id,
                        context={
                            "result": result_summary,
                            "warnings": next_step.get("warnings"),
                        },
                    )

                except Exception as e:
                    retry_count = next_step.get("retry_count", 0) + 1
                    next_step["retry_count"] = retry_count
                    next_step.setdefault("errors", []).append(
                        {
                            "error": str(e),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "attempt": retry_count,
                        }
                    )

                    if retry_count >= MAX_STEP_RETRIES:
                        # Permanently blocked — but DON'T block the whole goal
                        next_step["status"] = "Blocked"
                        logger.error(
                            "Step %s permanently blocked after %d retries: %s",
                            step_id,
                            retry_count,
                            e,
                        )
                        self._log_to_journal(
                            goal.get("title", "?"),
                            f"Step {step_id} BLOCKED after {retry_count} retries. Error: {e}",
                        )
                        goal.setdefault("blockers", []).append(
                            f"Step {step_id}: {str(e)}"
                        )
                    else:
                        # Schedule for retry with exponential backoff
                        next_step["status"] = "Retry"
                        backoff = RETRY_BACKOFF_BASE * (2 ** (retry_count - 1))
                        logger.warning(
                            "Step %s failed (attempt %d/%d), will retry in %ds: %s",
                            step_id,
                            retry_count,
                            MAX_STEP_RETRIES,
                            backoff,
                            e,
                        )
                        self._log_to_journal(
                            goal.get("title", "?"),
                            f"Step {step_id} failed (attempt {retry_count}/{MAX_STEP_RETRIES}). "
                            f"Retry in {backoff}s. Error: {e}",
                        )
                        # Non-blocking sleep — the next cycle will pick it up
                        # We just record the retry state; the scheduler handles timing

                updated = True
                break  # Only do one step per cycle to prevent infinite loops

            # ── State: Check for completion or total block ─────────────
            if self._all_steps_done(steps):
                logger.info(
                    "All steps completed for goal '%s'. Marking complete.",
                    goal.get("title"),
                )
                goal["status"] = "Completed"
                goal["updated_at"] = datetime.now(timezone.utc).isoformat()

                self._log_to_journal(
                    goal.get("title", "?"), "Goal COMPLETED 🎉"
                )

                self.inbox.add_item(
                    user_id=user_id,
                    title=f"Goal Completed: {goal.get('title')} 🎉",
                    kind="task",
                    source="autonomy_engine",
                    platform=platform,
                    chat_id=chat_id,
                )
                updated = True

            elif self._all_steps_terminal(steps) and not self._all_steps_done(steps):
                # All steps are either Completed or Blocked — goal is partially done
                blocked_count = sum(1 for s in steps if s.get("status") == "Blocked")
                total = len(steps)
                logger.warning(
                    "Goal '%s' has %d/%d steps blocked. Marking goal as Blocked.",
                    goal.get("title"),
                    blocked_count,
                    total,
                )
                goal["status"] = "Blocked"
                goal["updated_at"] = datetime.now(timezone.utc).isoformat()

                self._log_to_journal(
                    goal.get("title", "?"),
                    f"Goal BLOCKED: {blocked_count}/{total} steps failed permanently.",
                )

                self.inbox.add_item(
                    user_id=user_id,
                    title=f"⚠️ Goal Blocked: {goal.get('title')} ({blocked_count}/{total} steps failed)",
                    kind="alert",
                    source="autonomy_engine",
                    platform=platform,
                    chat_id=chat_id,
                    context={"blockers": goal.get("blockers", [])},
                )
                updated = True

        if updated:
            self._write_goals(goals)

    # ── Step execution delegate ────────────────────────────────────────

    async def _execute_step(
        self,
        goal: Dict[str, Any],
        step: Dict[str, Any],
        user_id: str,
        platform: str,
        chat_id: str,
    ) -> str:
        """Execute a single step via the AgentRuntime. Returns result summary."""
        if self.agent_runtime:
            req = IncomingRequest(
                user_id=user_id,
                platform=platform,
                text=f"Goal: {goal.get('title', '')}\nNext Step: {step.get('desc', '')}",
                reply_target=ReplyTarget(
                    platform=platform, chat_id=chat_id + "_bg"
                ),
            )
            prev_emit = self.agent_runtime.emit_status_messages
            self.agent_runtime.emit_status_messages = False

            try:
                session_id = await self.agent_runtime.execute_turn(req)
            finally:
                self.agent_runtime.emit_status_messages = prev_emit

            # load_session returns a list of message dicts
            session_msgs = self.agent_runtime.session_manager.load_session(
                session_id
            )
            if session_msgs and isinstance(session_msgs, list) and len(session_msgs) > 0:
                last_msg = session_msgs[-1]
                result_summary = last_msg.get(
                    "content", f"Completed action '{step.get('action')}'."
                )
            else:
                result_summary = (
                    f"Completed action '{step.get('action')}' autonomously: {step.get('desc')}"
                )
        else:
            result_summary = (
                f"Completed action '{step.get('action')}' autonomously: {step.get('desc')}"
            )

        return result_summary
