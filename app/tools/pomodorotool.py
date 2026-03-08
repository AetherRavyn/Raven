# app/tools/pomodorotool.py
"""PomodoroTool — focus timer with work/break cycles."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class PomodoroTool(BaseTool):
    """Pomodoro focus timer with work/break cycles. Track productivity sessions."""

    def __init__(self, state_file: str = "workspace/pomodoro_state.json"):
        self.state_file = Path(state_file)
        self._state = {"sessions_completed": 0, "total_focus_minutes": 0}
        self._load_state()
        self._running = False

    def _load_state(self) -> None:
        if self.state_file.exists():
            import json

            try:
                self._state = json.loads(self.state_file.read_text())
            except Exception:
                pass

    def _save_state(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        import json

        self.state_file.write_text(json.dumps(self._state, indent=2))

    def get_name(self) -> str:
        return "pomodoro"

    def get_description(self) -> str:
        return (
            "Pomodoro focus timer: start a work session (default 25 min), "
            "take a break (5 min), track completed sessions, get statistics. "
            "Helps maintain focus with timed work/break cycles."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Operation to perform",
                    required=True,
                    enum=["start", "stop", "status", "stats", "reset"],
                ),
                ToolParameter(
                    name="work_minutes",
                    type="integer",
                    description="Work duration in minutes (default: 25)",
                    required=False,
                ),
                ToolParameter(
                    name="break_minutes",
                    type="integer",
                    description="Break duration in minutes (default: 5)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        operation = kwargs.get("operation", "status")
        work_minutes = kwargs.get("work_minutes", 25)
        break_minutes = kwargs.get("break_minutes", 5)

        try:
            if operation == "start":
                if self._running:
                    return {
                        "success": False,
                        "error": "Pomodoro already running. Use 'stop' to end.",
                    }

                self._running = True
                return {
                    "success": True,
                    "message": f"🍅 Pomodoro started! Focus for {work_minutes} minutes...",
                    "work_minutes": work_minutes,
                    "break_minutes": break_minutes,
                    "note": "In production, this would run async and send notifications. Use 'status' to check.",
                }

            if operation == "stop":
                if not self._running:
                    return {"success": False, "error": "No Pomodoro running."}
                self._running = False
                self._state["sessions_completed"] += 1
                self._state["total_focus_minutes"] += work_minutes
                self._save_state()
                return {
                    "success": True,
                    "message": f"⏹ Pomodoro stopped. Great focus session!",
                    "sessions_today": self._state["sessions_completed"],
                    "total_focus_today_minutes": self._state["total_focus_minutes"],
                }

            if operation == "status":
                return {
                    "success": True,
                    "running": self._running,
                    "sessions_completed": self._state["sessions_completed"],
                    "total_focus_minutes": self._state["total_focus_minutes"],
                    "message": "🍅 Pomodoro active"
                    if self._running
                    else "💤 Pomodoro idle",
                }

            if operation == "stats":
                return {
                    "success": True,
                    "sessions_completed": self._state["sessions_completed"],
                    "total_focus_minutes": self._state["total_focus_minutes"],
                    "total_focus_hours": round(
                        self._state["total_focus_minutes"] / 60, 1
                    ),
                    "message": f"📊 You've completed {self._state['sessions_completed']} sessions ({self._state['total_focus_minutes']} min total)",
                }

            if operation == "reset":
                self._state = {"sessions_completed": 0, "total_focus_minutes": 0}
                self._save_state()
                return {
                    "success": True,
                    "message": "🔄 Pomodoro stats reset.",
                }

            return {"success": False, "error": f"Unknown operation: {operation}"}

        except Exception as exc:
            logger.exception("PomodoroTool error")
            return {"success": False, "error": str(exc)}
