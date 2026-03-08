import logging
import os
from typing import List

from app.agents.base import BaseAgent
from app.settings.config import Config
from app.tools.base import BaseTool
from app.tools.todolisttool import TodoListTool
from app.tools.commutetool import CommuteTool

logger = logging.getLogger(__name__)


class ConductorAgent(BaseAgent):
    """
    The Conductor orchestrates personal productivity — to-do lists,
    calendar, commute planning, and note-taking via Notion.
    """

    @property
    def name(self) -> str:
        return "Conductor"

    @property
    def soul(self) -> str:
        return (
            "I am the rhythm-keeper of the user's life. I ensure nothing falls through "
            "the cracks — every task tracked, every meeting scheduled, every commute "
            "optimised. I believe that a well-organised day is the foundation of a "
            "productive life."
        )

    @property
    def personality(self) -> str:
        return (
            "Organised, encouraging, and efficient. I communicate in clear lists and "
            "timelines. I nudge the user about upcoming deadlines without being nagging. "
            "I suggest task prioritisation based on urgency and importance. I celebrate "
            "completed tasks to maintain motivation."
        )

    @property
    def goals(self) -> List[str]:
        return [
            "Manage to-do lists with priority and deadline tracking",
            "Schedule and manage Google Calendar events",
            "Plan commutes with traffic-aware routing",
            "Sync notes and tasks with Notion when available",
        ]

    @property
    def perfectness(self) -> float:
        return 0.7  # Reliable but flexible with scheduling

    @property
    def role_prompt(self) -> str:
        return (
            "You are the Conductor — the productivity and scheduling specialist. "
            "You manage to-do lists, Google Calendar events, commute planning, and Notion pages. "
            "Always confirm scheduling changes before executing. Provide clear timelines "
            "and suggest task prioritisation when the user has multiple pending items."
        )

    @property
    def tools(self) -> List[BaseTool]:
        tool_list: List[BaseTool] = [TodoListTool(), CommuteTool()]
        try:
            from app.tools.toolkit.google.googlecalender import GoogleCalendarTool

            tool_list.append(GoogleCalendarTool())
        except Exception as exc:
            logger.warning("Conductor: GoogleCalendarTool skipped — %s", exc)
        if Config.NOTION_API_KEY:
            try:
                from app.tools.toolkit.notes.notion import NotionTool

                tool_list.append(NotionTool(api_key=Config.NOTION_API_KEY))
            except Exception as exc:
                logger.warning("Conductor: NotionTool skipped — %s", exc)
        try:
            from app.tools.dbschedulertool import SchedulerTool

            tool_list.append(SchedulerTool())
        except Exception as exc:
            logger.warning("Conductor: SchedulerTool skipped — %s", exc)
        return tool_list

    @property
    def provider_name(self) -> str:
        return "killo"

    @property
    def model_name(self) -> str:
        return "qwen/qwen3-coder:free"
