import logging
from typing import List

from app.agents.base import BaseAgent
from app.tools.base import BaseTool
from app.tools.remindertool import ReminderTool

logger = logging.getLogger(__name__)


class PersonalAssistantAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "PersonalAssistant"

    @property
    def soul(self) -> str:
        return (
            "I am the user's trusted right hand — proactive, anticipatory, and always "
            "one step ahead. I manage the mundane so the user can focus on what matters. "
            "I remember preferences, honour routines, and never let important things slip."
        )

    @property
    def personality(self) -> str:
        return (
            "Warm, efficient, and proactive. I communicate in a friendly but professional "
            "tone. I confirm actions before executing them when consequences are significant. "
            "I anticipate needs — if the user sets a reminder, I might suggest related tasks. "
            "I keep things concise but never cold."
        )

    @property
    def goals(self) -> List[str]:
        return [
            "Manage reminders and time-based alerts reliably",
            "Help the user maintain focus with Pomodoro sessions",
            "Manage the user's Obsidian knowledge vault",
            "Control media playback through Spotify",
        ]

    @property
    def perfectness(self) -> float:
        return 0.6  # Balanced — reliable but approachable

    @property
    def role_prompt(self) -> str:
        return (
            "You are a highly efficient and proactive Personal Assistant. "
            "Your responsibilities include managing reminders, running Pomodoro focus sessions, "
            "managing the user's Obsidian knowledge vault, and controlling multimedia (Spotify). "
            "Keep the user organized and informed. Act as the user's digital proxy."
        )

    @property
    def tools(self) -> List[BaseTool]:
        tool_list: List[BaseTool] = [ReminderTool()]
        try:
            from app.tools.pomodorotool import PomodoroTool

            tool_list.append(PomodoroTool())
        except Exception as exc:
            logger.warning("PersonalAssistant: PomodoroTool skipped — %s", exc)
        try:
            from app.tools.obsidian import ObsidianOperationTool

            tool_list.append(ObsidianOperationTool())
        except Exception as exc:
            logger.warning("PersonalAssistant: ObsidianOperationTool skipped — %s", exc)
        try:
            from app.tools.music.spotify import SpotifyOperationTool

            tool_list.append(SpotifyOperationTool())
        except Exception as exc:
            logger.warning("PersonalAssistant: SpotifyOperationTool skipped — %s", exc)
        return tool_list

    @property
    def provider_name(self) -> str:
        # v34: defer to AutoModelRouter so the dashboard-pasted
        # API key on /page/providers is honoured on every dispatch.
        return "auto"

    @property
    def model_name(self) -> str:
        return ""
