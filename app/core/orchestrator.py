from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from app.agents.assistant import PersonalAssistantAgent
from app.agents.communications import HeraldAgent
from app.agents.dataengineer import ArchivistAgent
from app.agents.developer import DeveloperAgent
from app.agents.finance import FinanceAgent
from app.agents.homeguardian import HomeGuardianAgent
from app.agents.moral import ConscienceAgent
from app.agents.news import NewsAgent
from app.agents.productivity import ConductorAgent
from app.agents.researcher import ResearcherAgent
from app.agents.reviewer import ReviewerAgent
from app.agents.scientist import PolymathAgent
from app.agents.security import SecurityAgent
from app.agents.sysadmin import SysadminAgent
from app.core.agency import SwarmManager
from app.core.botsignal import BotSignal
from app.core.models import IncomingRequest
from app.core.runtime import AgentRuntime
from app.core.security import get_security_guard
from app.core.ratelimit import get_rate_limiter
from app.minichat.minichat import MiniEngine
from app.settings.config import Config
from app.tools.agencytool import AgencyDelegationTool
from app.tools.browsertool import BrowserOperationTool
from app.tools.camerasnapshottool import CameraSnapshotTool
from app.tools.filetool import AdvancedFileOperationTool
from app.tools.finance import FinanceOperationTool
from app.tools.gittool import GitOperationTool
from app.tools.imagegentool import ImageGenerationTool
from app.tools.kgtool import KnowledgeGraphTool
from app.tools.messagingtool import PlatformMessagingTool
from app.tools.music.spotify import SpotifyOperationTool
from app.tools.network import NetworkTool
from app.tools.obsidian import ObsidianOperationTool
from app.tools.remindertool import ReminderTool
from app.tools.searxngtool import SearXNGTool
from app.tools.sensorreadtool import SensorReadTool
from app.tools.smarthometool import SmartHomeTool
from app.tools.toolkit.google.googlecalender import GoogleCalendarTool
from app.tools.toolkit.notes.notion import NotionTool
from app.tools.virustool import VirusTotalTool
from app.tools.weathertool import WeatherTool
from app.tools.webfetch import WebFetchOperationTool
from app.tools.websearch import WebOperationTool
from app.tools.wolframtool import WolframAlphaTool
from app.tools.xaiimagetool import XAIImageUnderstandTool
from app.tools.systemstatstool import SystemStatsTool
from app.tools.dockertool import DockerTool
from app.tools.cryptopricetool import CryptoPriceTool
from app.tools.rssreadertool import RSSReaderTool
from app.tools.airqualitytool import AirQualityTool
from app.tools.totpgentool import TOTPGeneratorTool
from app.tools.pomodorotool import PomodoroTool
from app.tools.todolisttool import TodoListTool
from app.tools.commutetool import CommuteTool
from app.tools.twittertool import TwitterTool
from app.tools.reddittool import RedditTool
from app.tools.youtube import YouTubeTool
from app.tools.urltool import URLMetadataTool, SSLMonitorTool
from app.tools.dbschedulertool import DatabaseQueryTool, SchedulerTool
from app.tools.financetools import (
    StockQuoteTool,
    CryptoAlertTool,
    DNSLookupTool,
    HaveIBeenPwnedTool,
    URLVirusScanTool,
    CronManagerTool,
)

logger = logging.getLogger(__name__)


class MessageOrchestrator:
    """Receives requests from any platform and delegates to AgentRuntime for execution."""

    def __init__(
        self, botsignal: BotSignal, output_directory: str = "workspace"
    ) -> None:
        self._botsignal = botsignal
        self._engine = MiniEngine()
        self._agent_runtime = AgentRuntime(workspace_dir=output_directory)
        self._swarm_manager = SwarmManager(workspace_dir=output_directory)

        # Register core tools dynamically into the AgentRuntime and SwarmManager
        tools = [
            AdvancedFileOperationTool(base_directory=output_directory),
            GitOperationTool(repo_path="."),
            KnowledgeGraphTool(),
            NetworkTool(),
            BrowserOperationTool(),
            VirusTotalTool(),
            WebOperationTool(google_api_key=Config.GEMINI_API_KEY),
            WebFetchOperationTool(google_api_key=Config.GEMINI_API_KEY),
            XAIImageUnderstandTool(),
            FinanceOperationTool(),
            WeatherTool(),
            ReminderTool(),
            # Smart home & sensors
            SmartHomeTool(),
            SensorReadTool(),
            # Image generation
            ImageGenerationTool(),
            # Camera
            CameraSnapshotTool(),
            # Math / science
            WolframAlphaTool(),
            # Private search
            SearXNGTool(),
            # Google Calendar (OAuth flow runs lazily on first use)
            GoogleCalendarTool(),
            # System monitoring
            SystemStatsTool(),
            DockerTool(),
            # Data & info
            CryptoPriceTool(),
            RSSReaderTool(),
            CommuteTool(),
            # Productivity
            PomodoroTool(),
            TodoListTool(),
            # Security
            TOTPGeneratorTool(),
            # Messaging
            PlatformMessagingTool(),
            # Social Media
            TwitterTool(),
            RedditTool(),
            # YouTube
            YouTubeTool(),
            # URL & SSL
            URLMetadataTool(),
            SSLMonitorTool(),
            # Database & Scheduler
            DatabaseQueryTool(),
            SchedulerTool(),
            # Finance & Security
            StockQuoteTool(),
            CryptoAlertTool(),
            DNSLookupTool(),
            HaveIBeenPwnedTool(),
            URLVirusScanTool(),
            # System
            CronManagerTool(),
        ]

        # Optional tools: register only if their runtime deps are satisfied
        if Config.NOTION_API_KEY:
            try:
                tools.append(NotionTool(api_key=Config.NOTION_API_KEY))
            except Exception as exc:
                logger.warning("NotionTool skipped — init failed: %s", exc)

        try:
            tools.append(ObsidianOperationTool())
        except Exception as exc:
            logger.warning("ObsidianOperationTool skipped — %s", exc)

        try:
            tools.append(SpotifyOperationTool())
        except ValueError as exc:
            logger.warning("SpotifyOperationTool skipped — %s", exc)

        for tool in tools:
            self._agent_runtime.register_tool(tool)

        # Register specialized Agents into the SwarmManager
        self._swarm_manager.register_agent(FinanceAgent())
        self._swarm_manager.register_agent(ResearcherAgent())
        self._swarm_manager.register_agent(SecurityAgent())
        self._swarm_manager.register_agent(ReviewerAgent())
        self._swarm_manager.register_agent(SysadminAgent())
        self._swarm_manager.register_agent(DeveloperAgent())
        self._swarm_manager.register_agent(PersonalAssistantAgent())
        self._swarm_manager.register_agent(NewsAgent())
        self._swarm_manager.register_agent(HomeGuardianAgent())
        self._swarm_manager.register_agent(HeraldAgent())
        self._swarm_manager.register_agent(PolymathAgent())
        self._swarm_manager.register_agent(ConductorAgent())
        self._swarm_manager.register_agent(ArchivistAgent())
        self._swarm_manager.register_agent(ConscienceAgent())

        # Give the main runtime the ability to spawn the swarm
        self._agent_runtime.register_tool(AgencyDelegationTool(self._swarm_manager))

    async def handle(self, request: IncomingRequest) -> None:
        """
        The entrypoint for all incoming platform messages.
        System 1 (MiniEngine) attempts to resolve the query instantly (e.g. time, basic OS status, greetings).
        If it requires deep reasoning or tools, it escalates to System 2 (AgentRuntime ReAct Loop).
        """
        source_kind = "command" if request.text.lstrip().startswith("/") else "prompt"

        # Prometheus: count all incoming requests
        try:
            from app.core.metrics import requests_total, requests_blocked

            requests_total.labels(
                platform=request.platform, source_kind=source_kind
            ).inc()
        except Exception:
            pass

        # Security Guard: Front-Door Prompt Injection Check
        security_guard = get_security_guard()
        is_safe, reason = security_guard.analyze_prompt(request.text)
        if not is_safe:
            try:
                from app.core.metrics import requests_blocked

                requests_blocked.labels(reason="security").inc()
            except Exception:
                pass
            await self._botsignal.send_text(
                request.reply_target,
                f"🛡️ Security Alert: {reason}",
                source_kind=source_kind,
            )
            return

        # Rate Limiter: Per-user sliding window
        rate_limiter = get_rate_limiter()
        allowed, rate_reason = rate_limiter.is_allowed(
            f"{request.platform}:{request.user_id}"
        )
        if not allowed:
            try:
                from app.core.metrics import requests_blocked

                requests_blocked.labels(reason="rate_limit").inc()
            except Exception:
                pass
            await self._botsignal.send_text(
                request.reply_target,
                f"⏱ {rate_reason}",
                source_kind=source_kind,
            )
            return

        # System 1: Fast Reflex Check
        mini_response, escalate_to_prompt = self._engine.route_message(
            request.user_id, request.text
        )

        if not escalate_to_prompt:
            # Resolved by local rules (e.g., greetings, /time, /internet)
            await self._botsignal.send_text(
                request.reply_target,
                mini_response,
                source_kind=source_kind,
            )
            return

        # System 2: Deep ReAct Loop
        await self._agent_runtime.execute_turn(request)
