from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from app.agents.assistant import PersonalAssistantAgent
from app.agents.communications import HeraldAgent
from app.agents.dataengineer import ArchivistAgent
from app.agents.developer import DeveloperAgent
from app.agents.finance import FinanceAgent
from app.agents.homeguardian import HomeGuardianAgent
from app.agents.moral import ConscienceAgent
from app.agents.negotiation import NegotiationAgent
from app.agents.news import NewsAgent
from app.agents.productivity import ConductorAgent
from app.agents.researcher import ResearcherAgent
from app.agents.reviewer import ReviewerAgent
from app.agents.scientist import PolymathAgent
from app.agents.security import SecurityAgent
from app.agents.sysadmin import SysadminAgent
from app.core.agency import SwarmManager
from app.core.audit import AuditEvent, get_action_logger
from app.core.botsignal import BotSignal
from app.core.models import IncomingRequest, SignalPayload, ToolTrace
from app.core.runtime import AgentRuntime
from app.core.security import get_security_guard
from app.core.ratelimit import get_rate_limiter
from app.minichat.minichat import System1Router
from app.settings.config import Config
from app.tools.agencytool import AgencyDelegationTool
from app.tools.browsertool import BrowserOperationTool
from app.tools.camerasnapshottool import CameraSnapshotTool
from app.tools.filetool import AdvancedFileOperationTool
from app.tools.finance import FinanceOperationTool
from app.tools.gittool import GitOperationTool
from app.tools.imagegentool import ImageGenerationTool
from app.tools.internetinteltool import InternetIntelTool
from app.tools.kgtool import KnowledgeGraphTool
from app.tools.messagingtool import PlatformMessagingTool
from app.tools.deliverfiletool import DeliverFileTool
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
from app.tools.mail import MailTool
from app.tools.workflowtool import WorkflowTool
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
from app.tools.computeruse import ComputerUseTool
from app.tools.mobiletool import MobileDeviceTool
from app.tools.desktoptool import DesktopControlTool
from app.tools.screenreadertool import ScreenReaderTool
from app.tools.sandbox import SandboxExecTool
from app.tools.google_calendar import GoogleCalendarTool
from app.tools.translation import TranslationTool
from app.tools.maps_geocoding import MapsGeocodingTool
from app.tools.free_apis import FreeInformationAPIs
from app.tools.document_parser import PDFReaderTool, DocxReaderTool, ExcelReaderTool
from app.tools.document_generator import PDFGeneratorTool, DocxGeneratorTool, ExcelGeneratorTool, CSVGeneratorTool, HTMLGeneratorTool
from app.tools.data_visualization import ChartGeneratorTool, TableVisualizerTool
from app.tools.health_tracker import HealthTrackerTool
from app.tools.outlook_calendar import OutlookCalendarTool
from app.tools.monitoring_tool import MonitoringTool
from app.tools.database_connector import DatabaseConnector, RESTAPIConnector
from app.tools.email_drafter import EmailDrafterTool
from app.tools.meeting_notes import MeetingNotesTool
from app.tools.academic_research import ArxivSearchTool, SemanticScholarTool
from app.tools.shopping_tool import ShoppingTool
from app.tools.learning_system import LearningSystemTool
from app.tools.trip_planner import TripPlannerTool
from app.tools.memorytool import MemoryTool
from app.tools.autonomytool import AutonomyTool
from app.tools.governancetool import GovernanceTool
from app.tools.edgetool import EdgeDeviceTool
from app.tools.elevatedtool import ElevatedModeTool
from app.tools.exectool import ExecTool
from app.tools.docker_exec_tool import DockerExecTool
from app.tools.pathchtool import ApplyPatchTool
from app.tools.writetool import WriteTodosTool

logger = logging.getLogger(__name__)


class MessageOrchestrator:
    """Receives requests from any platform and delegates to AgentRuntime for execution."""

    def __init__(
        self, botsignal: BotSignal, output_directory: str = "workspace"
    ) -> None:
        self._botsignal = botsignal
        self._engine = System1Router()
        self._agent_runtime = AgentRuntime(workspace_dir=output_directory)
        self._agent_runtime.botsignal = botsignal
        self._agent_runtime.emit_status_messages = False
        self._brain_provider = self._agent_runtime.provider
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
            InternetIntelTool(),
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
            # Messaging & User Delivery
            PlatformMessagingTool(),
            DeliverFileTool(),
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
            # Email
            MailTool(),
            # Workflow automation
            WorkflowTool(),
            # Device automation — control like a real user
            ComputerUseTool(),
            MobileDeviceTool(),
            DesktopControlTool(),
            ScreenReaderTool(),
            # Translation & Maps
            TranslationTool(),
            MapsGeocodingTool(),
            # Free Information APIs (Wikipedia, weather, search, crypto, etc.)
            FreeInformationAPIs(),
            # Shell exec — Docker-sandboxed by default.  Reachable
            # from chat via the ``sandbox_exec`` tool name; the tool
            # itself refuses host execution unless
            # ``Config.ALLOW_HOST_SHELL_EXECUTION`` is True AND the
            # caller passes ``force_host=True``.  See
            # ``app.tools.sandbox.SandboxExecTool``.
            SandboxExecTool(workspace_dir=output_directory),
            # Document parsing (PDF, DOCX, Excel)
            PDFReaderTool(),
            DocxReaderTool(),
            ExcelReaderTool(),
            # Health tracking
            HealthTrackerTool(workspace_dir=output_directory),
            # Document generation (PDF, DOCX, Excel, CSV, HTML)
            PDFGeneratorTool(),
            DocxGeneratorTool(),
            ExcelGeneratorTool(),
            CSVGeneratorTool(),
            HTMLGeneratorTool(),
            # Data visualization (charts, plots)
            ChartGeneratorTool(),
            TableVisualizerTool(),
            # Real-time monitoring
            MonitoringTool(workspace_dir=output_directory),
            # Database connectors (SQLite, MySQL, PostgreSQL)
            DatabaseConnector(),
            RESTAPIConnector(),
            # Email drafting with style learning
            EmailDrafterTool(workspace_dir=output_directory),
            # Meeting notes
            MeetingNotesTool(workspace_dir=output_directory),
            # Academic research
            ArxivSearchTool(),
            SemanticScholarTool(),
            # Shopping and deal finder
            ShoppingTool(workspace_dir=output_directory),
            # Learning system
            LearningSystemTool(workspace_dir=output_directory),
            # Trip planning
            TripPlannerTool(),
            # Unregistered tools — wire them up
            MemoryTool(),
            AutonomyTool(),
            GovernanceTool(),
            EdgeDeviceTool(),
            ElevatedModeTool(),
            ExecTool(),
            DockerExecTool(),
            ApplyPatchTool(),
            WriteTodosTool(),
        ]

        # Load skill plugin tools — make skills executable, not just advisory
        try:
            from app.core.skill_registry import SkillRegistry
            sr = SkillRegistry()
            plugin_tools = sr.load_plugin_tools()
            if plugin_tools:
                tools.extend(plugin_tools)
                logger.info("Loaded %d skill plugin tools", len(plugin_tools))
        except Exception as exc:
            logger.debug("Skill plugin tools load failed: %s", exc)

        # Optional tools: register only if their runtime deps are satisfied
        if Config.NOTION_API_KEY:
            try:
                tools.append(NotionTool(api_key=Config.NOTION_API_KEY))
            except Exception as exc:
                logger.warning("NotionTool skipped — init failed: %s", exc)

        # Outlook calendar — gated behind Azure env vars
        try:
            from app.settings.config import Config as _Cfg
            azure_client = getattr(_Cfg, "AZURE_CLIENT_ID", "")
            if azure_client:
                tools.append(OutlookCalendarTool(
                    tenant_id=getattr(_Cfg, "AZURE_TENANT_ID", ""),
                    client_id=azure_client,
                    client_secret=getattr(_Cfg, "AZURE_CLIENT_SECRET", ""),
                ))
        except Exception:
            pass

        try:
            tools.append(ObsidianOperationTool())
        except Exception as exc:
            logger.warning("ObsidianOperationTool skipped — %s", exc)

        try:
            tools.append(SpotifyOperationTool())
        except ValueError as exc:
            logger.warning("SpotifyOperationTool skipped — %s", exc)

        # Optional xAI vision tool: skip when no API key is configured.
        try:
            tools.append(XAIImageUnderstandTool())
        except Exception as exc:
            logger.warning("XAIImageUnderstandTool skipped — %s", exc)

        for tool in tools:
            self._agent_runtime.register_tool(tool)
            get_action_logger().record(
                AuditEvent(
                    kind="tool",
                    action="register",
                    actor="orchestrator",
                    success=True,
                    metadata={"tool": tool.get_name()},
                )
            )

        self._git_tool = self._agent_runtime.tools.get("git_ops")
        self._file_tool = self._agent_runtime.tools.get("file_operations")
        self._web_search_tool = self._agent_runtime.tools.get("web_ops")
        self._web_fetch_tool = self._agent_runtime.tools.get("web_fetch_ops")
        self._vt_tool = self._agent_runtime.tools.get("virustotal_scanner")
        self._xai_image_tool = self._agent_runtime.tools.get("xai_image_understand")

        # Register specialized Agents into the SwarmManager
        self._swarm_manager.register_agent(FinanceAgent())
        get_action_logger().record(
            AuditEvent(
                kind="agent",
                action="register",
                actor="orchestrator",
                success=True,
                metadata={"agent": "FinanceAgent"},
            )
        )
        self._swarm_manager.register_agent(ResearcherAgent())
        get_action_logger().record(
            AuditEvent(
                kind="agent",
                action="register",
                actor="orchestrator",
                success=True,
                metadata={"agent": "ResearcherAgent"},
            )
        )
        self._swarm_manager.register_agent(SecurityAgent())
        get_action_logger().record(
            AuditEvent(
                kind="agent",
                action="register",
                actor="orchestrator",
                success=True,
                metadata={"agent": "SecurityAgent"},
            )
        )
        self._swarm_manager.register_agent(ReviewerAgent())
        get_action_logger().record(
            AuditEvent(
                kind="agent",
                action="register",
                actor="orchestrator",
                success=True,
                metadata={"agent": "ReviewerAgent"},
            )
        )
        self._swarm_manager.register_agent(SysadminAgent())
        get_action_logger().record(
            AuditEvent(
                kind="agent",
                action="register",
                actor="orchestrator",
                success=True,
                metadata={"agent": "SysadminAgent"},
            )
        )
        self._swarm_manager.register_agent(DeveloperAgent())
        get_action_logger().record(
            AuditEvent(
                kind="agent",
                action="register",
                actor="orchestrator",
                success=True,
                metadata={"agent": "DeveloperAgent"},
            )
        )
        self._swarm_manager.register_agent(PersonalAssistantAgent())
        get_action_logger().record(
            AuditEvent(
                kind="agent",
                action="register",
                actor="orchestrator",
                success=True,
                metadata={"agent": "PersonalAssistantAgent"},
            )
        )
        self._swarm_manager.register_agent(NewsAgent())
        get_action_logger().record(
            AuditEvent(
                kind="agent",
                action="register",
                actor="orchestrator",
                success=True,
                metadata={"agent": "NewsAgent"},
            )
        )
        self._swarm_manager.register_agent(HomeGuardianAgent())
        get_action_logger().record(
            AuditEvent(
                kind="agent",
                action="register",
                actor="orchestrator",
                success=True,
                metadata={"agent": "HomeGuardianAgent"},
            )
        )
        self._swarm_manager.register_agent(HeraldAgent())
        get_action_logger().record(
            AuditEvent(
                kind="agent",
                action="register",
                actor="orchestrator",
                success=True,
                metadata={"agent": "HeraldAgent"},
            )
        )
        self._swarm_manager.register_agent(PolymathAgent())
        get_action_logger().record(
            AuditEvent(
                kind="agent",
                action="register",
                actor="orchestrator",
                success=True,
                metadata={"agent": "PolymathAgent"},
            )
        )
        self._swarm_manager.register_agent(ConductorAgent())
        get_action_logger().record(
            AuditEvent(
                kind="agent",
                action="register",
                actor="orchestrator",
                success=True,
                metadata={"agent": "ConductorAgent"},
            )
        )
        self._swarm_manager.register_agent(ArchivistAgent())
        get_action_logger().record(
            AuditEvent(
                kind="agent",
                action="register",
                actor="orchestrator",
                success=True,
                metadata={"agent": "ArchivistAgent"},
            )
        )
        self._swarm_manager.register_agent(ConscienceAgent())
        self._swarm_manager.register_agent(NegotiationAgent())
        get_action_logger().record(
            AuditEvent(
                kind="agent",
                action="register",
                actor="orchestrator",
                success=True,
                metadata={"agent": "ConscienceAgent"},
            )
        )

        # Give the main runtime the ability to spawn the swarm
        self._agent_runtime.register_tool(AgencyDelegationTool(self._swarm_manager))

        # Wire CommandGateway — slash-command dispatcher
        try:
            from app.core.commands import CommandGateway
            self._command_gateway = CommandGateway(self)
        except Exception as exc:
            logger.debug("CommandGateway init failed: %s", exc)
            self._command_gateway = None

        # Wire HeartbeatRunner — periodic session check
        try:
            from app.core.heartbeat import HeartbeatRunner
            self._heartbeat_runner = HeartbeatRunner(workspace_dir=output_directory)
        except Exception as exc:
            logger.debug("HeartbeatRunner init failed: %s", exc)
            self._heartbeat_runner = None

    def _tool_by_name(self, name: str) -> Any | None:
        return self._agent_runtime.tools.get(name)

    def _direct_tool(self, attr_name: str, runtime_name: str) -> Any | None:
        tool = getattr(self, attr_name, None)
        if tool is not None:
            return tool
        return self._tool_by_name(runtime_name)

    @staticmethod
    def _result_success(result: Any) -> bool:
        if isinstance(result, dict):
            return result.get("success") is not False
        return True

    async def _send_direct_payload(
        self,
        request: IncomingRequest,
        source_kind: str,
        text: str,
        tool_traces: list[Any],
        file_path: str | None = None,
    ) -> None:
        await self._botsignal.send(
            request.reply_target,
            SignalPayload(
                text=text,
                file_path=file_path,
                source_kind=source_kind,
                tool_traces=tool_traces,
            ),
        )

    async def _handle_escalated_prompt(
        self, request: IncomingRequest, source_kind: str, mini_response: str
    ) -> bool:
        provider: Any = (
            getattr(self, "_brain_provider", None) or self._agent_runtime.provider
        )
        provider_name = (
            provider.__class__.__name__.lower().replace("client", "")
            if provider
            else "llm_provider"
        )

        if provider is None:
            await self._botsignal.send_text(
                request.reply_target,
                mini_response,
                source_kind=source_kind,
                tool_traces=[
                    ToolTrace(
                        tool_name=provider_name,
                        action="chat_completion_resilient",
                        success=False,
                        detail="Provider unavailable",
                    )
                ],
            )
            return True

        from app.core.session import SessionManager
        session_manager = SessionManager(str(self._agent_runtime.workspace_dir))
        session_id = request.conversation_id or f"{request.platform}_{request.user_id}"

        # Load session history
        history = session_manager.load_session(session_id)
        user_msg = {"role": "user", "content": request.text}
        messages = history + [user_msg]
        session_manager.append_message(session_id, user_msg)
        session_manager.prune_session(session_id)

        try:
            resilient_func = getattr(provider, "chat_completion_resilient", None)
            if callable(resilient_func):
                _func: Any = resilient_func
                result = await _func(
                    messages=messages,
                    preferred_models=[self._agent_runtime.model_name],
                    free_only_guard=True,
                )
            else:
                result = await provider.chat_completion(
                    model=self._agent_runtime.model_name,
                    messages=messages,
                )
        except Exception as exc:
            result = {"success": False, "error": str(exc)}

        if not result.get("success"):
            # Resilient fallback across all configured providers
            from app.core.model_router import AutoModelRouter
            from app.provider.factory import create_provider
            
            fallbacks = AutoModelRouter.get_available_models("agent")
            for f_prov_name, f_model_name in fallbacks:
                try:
                    f_prov = create_provider(f_prov_name)
                    f_res = await f_prov.chat_completion(model=f_model_name, messages=messages)
                    if f_res.get("success"):
                        result = f_res
                        provider_name = f_prov_name
                        break
                except Exception:
                    continue

        if result.get("success"):
            content = result.get("content") or result.get("output") or mini_response
            
            # Save assistant reply to memory/session
            if content:
                session_manager.append_message(session_id, {"role": "assistant", "content": content})
                session_manager.prune_session(session_id)

            await self._botsignal.send_text(
                request.reply_target,
                content,
                source_kind=source_kind,
                tool_traces=[
                    ToolTrace(
                        tool_name=provider_name,
                        action="chat_completion_resilient",
                        success=True,
                        detail=str(result.get("model_used") or "") or None,
                    )
                ],
            )
            return True

        await self._botsignal.send_text(
            request.reply_target,
            mini_response,
            source_kind=source_kind,
            tool_traces=[
                ToolTrace(
                    tool_name=provider_name,
                    action="chat_completion_resilient",
                    success=False,
                    detail=str(result.get("error") or "Unknown error"),
                )
            ],
        )
        return True

    def _format_tool_result(
        self,
        tool_name: str,
        action: str,
        result: Any,
        source_kind: str,
        summary: str,
        success_label: str,
    ) -> str:
        lines: list[str] = [summary]
        if isinstance(result, dict):
            if result.get("success") is False:
                return f"{success_label}: {result.get('error', 'unknown error')}"

            if tool_name == "git_ops":
                branch = result.get("branch") or result.get("output") or ""
                status = result.get("status") or ""
                last_commit = result.get("last_commit") or ""
                commits = result.get("commits") or []
                if branch:
                    lines.append(f"branch: {str(branch).strip()}")
                if status:
                    lines.append(f"status: {str(status).strip()}")
                if last_commit:
                    lines.append(f"last_commit: {str(last_commit).strip()}")
                if commits:
                    lines.append("recent_commits:")
                    lines.extend(f"- {commit}" for commit in commits[:10])
                return "\n".join(lines).strip()

            if tool_name == "file_operations":
                info = result.get("info") or {}
                filepath = result.get("filepath") or info.get("path") or ""
                if filepath:
                    lines.append(f"filepath: {filepath}")
                if result.get("content") is not None:
                    content = str(result.get("content"))
                    lines.append(content[:3000])
                if result.get("tree"):
                    lines.append(str(result.get("tree")))
                if result.get("items"):
                    for item in result.get("items", [])[:20]:
                        if isinstance(item, dict):
                            lines.append(
                                f"- {item.get('name', 'untitled')} [{item.get('type', 'item')}]"
                            )
                if info:
                    lines.append(f"info: {info}")
                return "\n".join(lines).strip()

            if tool_name == "web_ops":
                output = result.get("output")
                if isinstance(output, list):
                    for item in output[:10]:
                        if isinstance(item, dict):
                            title = item.get("title") or item.get("name") or "Untitled"
                            url = item.get("url") or item.get("source_url") or ""
                            snippet = item.get("snippet") or item.get("content") or ""
                            line = f"- {title}"
                            if url:
                                line += f" {url}"
                            if snippet:
                                line += f"\n  {str(snippet)[:220]}"
                            lines.append(line)
                        else:
                            lines.append(str(item))
                    return "\n".join(lines).strip()
                if output is not None:
                    lines.append(str(output))
                return "\n".join(lines).strip()

            if tool_name == "web_fetch_ops":
                output = result.get("output")
                if isinstance(output, list):
                    for item in output[:10]:
                        if isinstance(item, dict):
                            title = item.get("title") or item.get("text") or "Untitled"
                            url = item.get("url") or ""
                            line = f"- {title}"
                            if url:
                                line += f" {url}"
                            lines.append(line)
                        else:
                            lines.append(str(item))
                    return "\n".join(lines).strip()
                if output is not None:
                    lines.append(str(output))
                return "\n".join(lines).strip()

            if tool_name == "virustotal_scanner":
                stats = result.get("stats") or {}
                lines.append(" ".join(f"{key}={value}" for key, value in stats.items()))
                if result.get("url"):
                    lines.append(f"url: {result.get('url')}")
                if result.get("domain"):
                    lines.append(f"domain: {result.get('domain')}")
                if result.get("ip_address"):
                    lines.append(f"ip_address: {result.get('ip_address')}")
                if result.get("file_hash"):
                    lines.append(f"file_hash: {result.get('file_hash')}")
                if result.get("analysis_id"):
                    lines.append(f"analysis_id: {result.get('analysis_id')}")
                return "\n".join(lines).strip()

            if tool_name == "xai_image_understand":
                if result.get("output") is not None:
                    lines.append(str(result.get("output")))
                if result.get("image_url"):
                    lines.append(f"image_url: {result.get('image_url')}")
                if result.get("model"):
                    lines.append(f"model: {result.get('model')}")
                return "\n".join(lines).strip()

        if isinstance(result, str):
            lines.append(result)
        else:
            lines.append(str(result))
        return "\n".join(lines).strip()

    async def _handle_direct_tool_prompt(
        self, request: IncomingRequest, source_kind: str
    ) -> bool:
        text = request.text.strip()
        lowered = text.lower()

        # Git routes
        if lowered.startswith("/git") or lowered.startswith("git ") or lowered == "git":
            tool = self._direct_tool("_git_tool", "git_ops")
            if tool is None:
                return False

            reply_lines: list[str] = ["Git tool operation complete."]
            traces: list[ToolTrace] = []
            branch_res = await tool.execute(operation="branch")
            traces.append(
                ToolTrace(
                    tool_name="git_ops",
                    action="branch",
                    success=self._result_success(branch_res),
                )
            )
            reply_lines.append(
                f"branch: {branch_res.get('branch') or branch_res.get('output') or ''}".strip()
            )
            status_res = await tool.execute(operation="status")
            traces.append(
                ToolTrace(
                    tool_name="git_ops",
                    action="status",
                    success=self._result_success(status_res),
                )
            )
            reply_lines.append(
                f"status: {status_res.get('status') or status_res.get('output') or ''}".strip()
            )
            log_res = await tool.execute(operation="log")
            traces.append(
                ToolTrace(
                    tool_name="git_ops",
                    action="log",
                    success=self._result_success(log_res),
                )
            )
            reply_lines.append("recent_commits:")
            reply_lines.extend(
                f"- {commit}" for commit in (log_res.get("commits") or [])[:10]
            )
            last_res = await tool.execute(operation="last_commit")
            traces.append(
                ToolTrace(
                    tool_name="git_ops",
                    action="last_commit",
                    success=self._result_success(last_res),
                )
            )
            reply_lines.append(
                f"last_commit: {last_res.get('last_commit') or last_res.get('output') or ''}".strip()
            )
            await self._send_direct_payload(
                request,
                source_kind,
                "\n".join(line for line in reply_lines if line).strip(),
                traces,
            )
            return True

        # File routes
        if lowered.startswith("file ") or lowered == "file":
            tool = self._direct_tool("_file_tool", "file_operations")
            if tool is None:
                return False

            remainder = text[4:].strip()
            if not remainder:
                return False

            if remainder.startswith("test all functionality"):
                traces: list[ToolTrace] = []
                reply_lines: list[str] = ["File tool operation complete."]
                base_dir = getattr(tool, "base_directory", None) or Path.cwd()
                temp_file = (
                    base_dir / f"raven_file_test_{request.reply_target.chat_id}.txt"
                )

                write_res = await tool.execute(
                    operation="write",
                    filepath=str(temp_file),
                    content="RAVEN file test\n",
                    create_dirs=True,
                )
                traces.append(
                    ToolTrace(
                        tool_name="file_operations",
                        action="write",
                        success=self._result_success(write_res),
                    )
                )
                if write_res.get("success"):
                    reply_lines.append("write: ok")

                append_res = await tool.execute(
                    operation="append",
                    filepath=str(temp_file),
                    content="append\n",
                    create_dirs=True,
                )
                traces.append(
                    ToolTrace(
                        tool_name="file_operations",
                        action="append",
                        success=self._result_success(append_res),
                    )
                )
                if append_res.get("success"):
                    reply_lines.append("append: ok")

                read_res = await tool.execute(operation="read", filepath=str(temp_file))
                traces.append(
                    ToolTrace(
                        tool_name="file_operations",
                        action="read",
                        success=self._result_success(read_res),
                    )
                )
                if read_res.get("success"):
                    reply_lines.append("read: ok")

                info_res = await tool.execute(operation="info", filepath=str(temp_file))
                traces.append(
                    ToolTrace(
                        tool_name="file_operations",
                        action="info",
                        success=self._result_success(info_res),
                    )
                )
                if info_res.get("success"):
                    reply_lines.append("info: ok")
                reply_lines.append(str(info_res.get("info") or ""))

                await self._send_direct_payload(
                    request,
                    source_kind,
                    "\n".join(line for line in reply_lines if line).strip(),
                    traces,
                    file_path=str(temp_file),
                )
                return True

            parts = remainder.split(maxsplit=2)
            if len(parts) < 2:
                return False
            operation = parts[0]
            filepath = parts[1]
            content = parts[2] if len(parts) > 2 else None
            result = await tool.execute(
                operation=operation, filepath=filepath, content=content
            )
            await self._send_direct_payload(
                request,
                source_kind,
                self._format_tool_result(
                    "file_operations",
                    operation,
                    result,
                    source_kind,
                    "File tool operation complete.",
                    "File tool error",
                ),
                [
                    ToolTrace(
                        tool_name="file_operations",
                        action=operation,
                        success=self._result_success(result),
                    )
                ],
                file_path=filepath
                if result.get("success") and operation == "read"
                else None,
            )
            return True

        # Web search routes
        if lowered.startswith("web search") or lowered.startswith("/web search"):
            tool = self._direct_tool("_web_search_tool", "web_ops")
            if tool is None:
                return False
            query = text.split(maxsplit=2)[2] if len(text.split(maxsplit=2)) > 2 else ""
            if not query:
                await self._botsignal.send_text(
                    request.reply_target,
                    "Usage: web search <query>",
                    source_kind=source_kind,
                )
                return True
            result = await tool.execute(operation="search", query=query)
            summary = ["Web search complete."]
            if result.get("llmContent"):
                summary.append(str(result.get("llmContent")))
            elif result.get("output") is not None:
                summary.append(str(result.get("output")))
            if isinstance(result.get("returnDisplay"), dict):
                sources = result.get("returnDisplay", {}).get("sources") or []
                if sources:
                    summary.append("")
                    summary.append("Sources:")
                    for item in sources[:5]:
                        if isinstance(item, dict):
                            title = item.get("title") or item.get("name") or "Untitled"
                            url = item.get("uri") or item.get("url") or ""
                            summary.append(f"- {title}{f' {url}' if url else ''}")
            await self._send_direct_payload(
                request,
                source_kind,
                "\n".join(line for line in summary if line is not None).strip(),
                [
                    ToolTrace(
                        tool_name="web_search",
                        action="query",
                        success=self._result_success(result),
                    )
                ],
            )
            return True

        # Web fetch routes
        if lowered.startswith("/webfetch") or lowered.startswith("web fetch"):
            tool = self._direct_tool("_web_fetch_tool", "web_fetch_ops")
            if tool is None:
                return False
            parts = text.split(maxsplit=1)
            url = parts[1].strip() if len(parts) > 1 else ""
            if not url:
                await self._botsignal.send_text(
                    request.reply_target,
                    "Usage: /webfetch <url>",
                    source_kind=source_kind,
                )
                return True
            result = await tool.execute(operation="fetch", url=url)
            lines = ["Web fetch complete."]
            if result.get("output") is not None:
                lines.append(str(result.get("output")))
            await self._send_direct_payload(
                request,
                source_kind,
                "\n".join(lines).strip(),
                [
                    ToolTrace(
                        tool_name="web_fetch",
                        action="fetch",
                        success=self._result_success(result),
                    )
                ],
            )
            return True

        # VirusTotal routes
        if lowered.startswith("virus ") or lowered.startswith("/virus"):
            tool = self._direct_tool("_vt_tool", "virustotal_scanner")
            if tool is None:
                return False
            parts = text.split(maxsplit=2)
            indicator = (
                parts[2].strip()
                if len(parts) > 2
                else (parts[1].strip() if len(parts) > 1 else "")
            )
            if not indicator:
                await self._botsignal.send_text(
                    request.reply_target,
                    "Usage: virus check <url|hash|domain|ip>",
                    source_kind=source_kind,
                )
                return True
            result = await tool.execute(operation="auto_lookup", indicator=indicator)
            lines = ["VirusTotal lookup complete."]
            stats = result.get("stats") or {}
            if stats:
                lines.append(", ".join(f"{k}={v}" for k, v in stats.items()))
            for key in ("url", "domain", "ip_address", "file_hash", "analysis_id"):
                if result.get(key):
                    lines.append(f"{key}: {result.get(key)}")
            await self._send_direct_payload(
                request,
                source_kind,
                "\n".join(lines).strip(),
                [
                    ToolTrace(
                        tool_name="virustotal_scanner",
                        action="auto_lookup",
                        success=self._result_success(result),
                    )
                ],
            )
            return True

        # xAI image understanding routes
        if lowered.startswith("image understand") or lowered.startswith(
            "/image understand"
        ):
            tool = self._direct_tool("_xai_image_tool", "xai_image_understand")
            if tool is None:
                return False
            parts = text.split(maxsplit=2)
            image_url = (
                parts[2].strip()
                if len(parts) > 2
                else (parts[1].strip() if len(parts) > 1 else "")
            )
            if not image_url:
                await self._botsignal.send_text(
                    request.reply_target,
                    "Usage: image understand <image_url>",
                    source_kind=source_kind,
                )
                return True
            result = await tool.execute(image_url=image_url)
            lines = ["Image understanding complete."]
            if result.get("output"):
                lines.append(str(result.get("output")))
            if result.get("image_url"):
                lines.append(f"image_url: {result.get('image_url')}")
            if result.get("model"):
                lines.append(f"model: {result.get('model')}")
            await self._send_direct_payload(
                request,
                source_kind,
                "\n".join(lines).strip(),
                [
                    ToolTrace(
                        tool_name="xai_image_understand",
                        action="analyze",
                        success=self._result_success(result),
                    )
                ],
            )
            return True

        # ── Phase 1 (v8) routing — TaskDecomposer ──────────────
        # `/goal <text>` — break a goal into executable tasks.
        # Bare `/goal` is treated as a usage error (handled below).
        # `/tasks` — list pending tasks for the user.
        # Both routes delegate to TaskDecomposer; failure is
        # surfaced as a chat reply (the user is asking, so they
        # should see the error rather than the loop swallowing it).
        if lowered == "/goal" or lowered.startswith("/goal "):
            goal_text = "" if lowered == "/goal" else text[len("/goal "):].strip()
            goal_text = text[len("/goal "):].strip()
            if not goal_text:
                await self._botsignal.send_text(
                    request.reply_target,
                    "Usage: /goal <description of what you want to accomplish>",
                    source_kind=source_kind,
                )
                return True
            try:
                from app.core.task_decomposer import get_task_decomposer
                decomposer = get_task_decomposer()
                tasks = decomposer.decompose_goal(goal_text)
            except Exception as exc:
                await self._botsignal.send_text(
                    request.reply_target,
                    f"TaskDecomposer failed: {exc}",
                    source_kind=source_kind,
                )
                return True
            if not tasks:
                reply = "TaskDecomposer: no tasks produced for that goal."
            else:
                lines = [f"Decomposed into {len(tasks)} task(s):", ""]
                for t in tasks:
                    lines.append(
                        f"- [{t.priority}] {t.title} (id={t.id}, "
                        f"~{t.estimated_minutes}min)"
                    )
                reply = "\n".join(lines)
            await self._botsignal.send_text(
                request.reply_target, reply, source_kind=source_kind,
            )
            return True

        if lowered == "/tasks":
            try:
                from app.core.task_decomposer import get_task_decomposer
                decomposer = get_task_decomposer()
                pending = decomposer.get_pending_tasks()
            except Exception as exc:
                await self._botsignal.send_text(
                    request.reply_target,
                    f"TaskDecomposer failed: {exc}",
                    source_kind=source_kind,
                )
                return True
            if not pending:
                reply = "No pending tasks. Try `/goal <description>` to create some."
            else:
                lines = [f"{len(pending)} pending task(s):", ""]
                for t in pending[:20]:  # cap the chat reply
                    lines.append(
                        f"- [{t.priority}] {t.title} (id={t.id}, "
                        f"~{t.estimated_minutes}min)"
                    )
                reply = "\n".join(lines)
            await self._botsignal.send_text(
                request.reply_target, reply, source_kind=source_kind,
            )
            return True

        # `/schedule` — show learned wake/sleep/work-hour patterns.
        if lowered == "/schedule":
            try:
                from app.core.schedule_learner import get_schedule_learner
                learner = get_schedule_learner()
                reply = learner.get_learning_summary()
            except Exception as exc:
                reply = f"ScheduleLearner failed: {exc}"
            await self._botsignal.send_text(
                request.reply_target, reply, source_kind=source_kind,
            )
            return True

        # ── Phase 4 (v9) routing — KnowledgeManager ─────────────
        # `/kg add <subj> <pred> <obj>` — record a triple.
        # `/kg query <name>` — list triples about a subject.
        # `/kg path <a> <b>` — find a connection between entities.
        # Bare `/kg` replies with usage.
        if lowered == "/kg" or lowered.startswith("/kg "):
            tokens = text[len("/kg"):].strip().split()
            if not tokens:
                await self._botsignal.send_text(
                    request.reply_target,
                    (
                        "Usage: /kg add <subj> <pred> <obj> | "
                        "/kg query <name> | /kg path <a> <b>"
                    ),
                    source_kind=source_kind,
                )
                return True
            op = tokens[0].lower()
            args = tokens[1:]
            try:
                from app.core.knowledge_manager import get_knowledge_manager
                mgr = get_knowledge_manager()
            except Exception as exc:
                await self._botsignal.send_text(
                    request.reply_target,
                    f"KnowledgeManager unavailable: {exc}",
                    source_kind=source_kind,
                )
                return True
            if op == "add":
                if len(args) != 3:
                    await self._botsignal.send_text(
                        request.reply_target,
                        "Usage: /kg add <subj> <pred> <obj>",
                        source_kind=source_kind,
                    )
                    return True
                fact = mgr.record_fact(*args, source="slash")
                if fact is None:
                    reply = f"Already known: {args[0]} --{args[1]}--> {args[2]}"
                else:
                    reply = (
                        f"Recorded: {fact.subject} --{fact.predicate}--> "
                        f"{fact.object} (backend={mgr.backend})"
                    )
                await self._botsignal.send_text(
                    request.reply_target, reply, source_kind=source_kind,
                )
                return True
            if op == "query":
                if len(args) != 1:
                    await self._botsignal.send_text(
                        request.reply_target,
                        "Usage: /kg query <name>",
                        source_kind=source_kind,
                    )
                    return True
                facts = mgr.query(args[0])
                if not facts:
                    reply = f"No facts about {args[0]}."
                else:
                    lines = [f"{len(facts)} fact(s) about {args[0]}:"]
                    for f in facts:
                        lines.append(
                            f"  - {f.subject} --{f.predicate}--> {f.object}"
                        )
                    reply = "\n".join(lines)
                await self._botsignal.send_text(
                    request.reply_target, reply, source_kind=source_kind,
                )
                return True
            if op == "path":
                if len(args) != 2:
                    await self._botsignal.send_text(
                        request.reply_target,
                        "Usage: /kg path <a> <b>",
                        source_kind=source_kind,
                    )
                    return True
                path = mgr.find_path(args[0], args[1])
                if path is None:
                    reply = f"No path from {args[0]} to {args[1]} within 4 hops."
                else:
                    reply = " → ".join(path)
                await self._botsignal.send_text(
                    request.reply_target, reply, source_kind=source_kind,
                )
                return True
            await self._botsignal.send_text(
                request.reply_target,
                f"Unknown /kg subcommand: {op!r}. Try add | query | path.",
                source_kind=source_kind,
            )
            return True

        # Learning summary (Phase 4 v10) — surface a one-screen
        # view of skill invocations, tool-call success rates,
        # and recent failure modes.  Pure read; no LLM call.
        if lowered == "/learned" or lowered.startswith("/learned"):
            try:
                from app.core.learning_tracker import get_learning_tracker

                tracker = get_learning_tracker()
                reply = tracker.summary().format_text()
            except Exception as exc:
                # The tracker is best-effort; a missing
                # SkillLearner or audit log must not crash the
                # reply path.  Fall back to a graceful message.
                reply = (
                    "No learning signals recorded yet "
                    f"(tracker unavailable: {exc})."
                )
            await self._botsignal.send_text(
                request.reply_target, reply, source_kind=source_kind,
            )
            return True

        # Home orchestration (Phase 4 v11) — list scenes, run
        # a scene, or set the user's presence location.
        # Subcommands: ``list``, ``run <name>``, ``here <loc>``.
        if lowered == "/scene" or lowered.startswith("/scene "):
            try:
                from app.core.home_orchestrator import get_home_orchestrator

                orchestrator_home = get_home_orchestrator()
            except Exception as exc:
                await self._botsignal.send_text(
                    request.reply_target,
                    f"HomeOrchestrator unavailable: {exc}",
                    source_kind=source_kind,
                )
                return True

            tokens = text[len("/scene"):].strip().split()
            if not tokens or tokens[0].lower() == "list":
                scenes = orchestrator_home.list_scenes()
                if not scenes:
                    reply = "No scenes defined yet."
                else:
                    lines = [f"{len(scenes)} scene(s):"]
                    for s in scenes:
                        loc = f" [{s.location}]" if s.location else ""
                        desc = f" — {s.description}" if s.description else ""
                        lines.append(f"  • {s.name}{loc} ({len(s.actions)} action(s)){desc}")
                    reply = "\n".join(lines)
            elif tokens[0].lower() == "run" and len(tokens) == 2:
                try:
                    result = await orchestrator_home.run_scene(tokens[1])
                    reply = result.format_text()
                except Exception as exc:  # noqa: BLE001 - scene exec
                    reply = f"Scene run failed: {exc}"
            elif tokens[0].lower() == "here" and len(tokens) == 2:
                orchestrator_home.set_presence(tokens[1], source="slash")
                reply = f"Presence set to: {tokens[1]}"
            else:
                reply = (
                    "Usage: /scene list | /scene run <name> | "
                    "/scene here <location>"
                )
            await self._botsignal.send_text(
                request.reply_target, reply, source_kind=source_kind,
            )
            return True

        # Cron schedule (Phase 5 v13) — list, add, remove, or
        # toggle dynamic :class:`CronEngine` jobs.  Backed by
        # the trust-skill ``CronCommand`` so the parsing is
        # shared with the standalone slash-command dispatcher.
        if lowered == "/cron" or lowered.startswith("/cron "):
            try:
                from app.core.trust.slash_commands import (
                    CronCommand,
                    SlashCommandContext,
                )
            except Exception as exc:  # noqa: BLE001 - optional
                await self._botsignal.send_text(
                    request.reply_target,
                    f"Cron slash command unavailable: {exc}",
                    source_kind=source_kind,
                )
                return True
            args = text[len("/cron"):].strip()
            reply = CronCommand().handle(args, SlashCommandContext())
            await self._botsignal.send_text(
                request.reply_target, reply, source_kind=source_kind,
            )
            return True

        # Skill invocation stats (Phase 5 v14) — render the
        # ``SkillInvoker``'s in-memory invocation history
        # (total / successes / failures / per-skill counts /
        # last 10 invocations).  Useful for operators to see
        # which skills are firing most often.
        if lowered == "/skills" or lowered.startswith("/skills "):
            try:
                from app.core.skill_invoker import get_skill_invoker
            except Exception as exc:  # noqa: BLE001 - optional
                await self._botsignal.send_text(
                    request.reply_target,
                    f"SkillInvoker unavailable: {exc}",
                    source_kind=source_kind,
                )
                return True
            invoker = get_skill_invoker()
            stats = invoker.get_invocation_stats()
            lines = ["**Skill invocations**", ""]
            lines.append(
                f"- Total: **{stats.get('total', 0)}** — "
                f"successes: **{stats.get('successes', 0)}**, "
                f"failures: **{stats.get('failures', 0)}** "
                f"({stats.get('success_rate', 0.0):.0%} success rate)"
            )
            skills_used = stats.get("skills_used") or {}
            if skills_used:
                lines.append("")
                lines.append("- Skills used:")
                for name, count in sorted(
                    skills_used.items(), key=lambda kv: -kv[1],
                ):
                    lines.append(f"  • {name}: {count}")
            recent = stats.get("recent") or []
            if recent:
                lines.append("")
                lines.append("- Recent (newest last):")
                for r in recent:
                    lines.append(
                        f"  • {r['skill']} (conf {r['confidence']:.0%}) — "
                        f"{r['query']} — "
                        f"{'OK' if r['success'] else 'FAIL'}"
                    )
            await self._botsignal.send_text(
                request.reply_target, "\n".join(lines), source_kind=source_kind,
            )
            return True

        return False

    async def _handle_internet_intel_direct(
        self, request: IncomingRequest, source_kind: str
    ) -> bool:
        """Handle explicit internet-intelligence commands without LLM usage."""
        text = request.text.strip()
        lowered = text.lower()
        prefix = None
        for candidate in ("/internet", "/reach", "internet", "reach"):
            if lowered.startswith(candidate):
                prefix = candidate
                break

        if not prefix:
            return False

        tool = self._agent_runtime.tools.get("internet_intel")
        if tool is None:
            await self._botsignal.send_text(
                request.reply_target,
                "Internet intelligence is not available right now.",
                source_kind=source_kind,
            )
            return True

        remainder = text[len(prefix) :].strip()
        if not remainder:
            operation = "report"
            argument = ""
        else:
            parts = remainder.split(maxsplit=1)
            operation = parts[0].strip().lower()
            argument = parts[1].strip() if len(parts) > 1 else ""

        if operation in {"status", "report"}:
            result = await tool.execute(operation=operation)
        elif operation in {"search", "discover"}:
            if not argument:
                await self._botsignal.send_text(
                    request.reply_target,
                    f"Usage: /internet {operation} <query>",
                    source_kind=source_kind,
                )
                return True
            result = await tool.execute(operation=operation, query=argument)
        elif operation == "read":
            if not argument:
                await self._botsignal.send_text(
                    request.reply_target,
                    "Usage: /internet read <url>",
                    source_kind=source_kind,
                )
                return True
            result = await tool.execute(operation=operation, url=argument)
        else:
            await self._botsignal.send_text(
                request.reply_target,
                "Usage: /internet status | report | search <query> | discover <query> | read <url>",
                source_kind=source_kind,
            )
            return True

        reply_lines: list[str] = []
        if isinstance(result, dict):
            if result.get("success") is False:
                reply_lines.append(
                    f"Internet intel error: {result.get('error', 'unknown error')}"
                )
            elif operation in {"status", "report"}:
                reply_lines.append(
                    str(
                        result.get("report")
                        or result.get("summary")
                        or "Internet status ready."
                    )
                )
            else:
                summary = (
                    result.get("summary")
                    or result.get("title")
                    or result.get("content")
                    or "Result ready."
                )
                reply_lines.append(str(summary))
                entries = result.get("results") or result.get("reads") or []
                if entries:
                    reply_lines.append("")
                    reply_lines.append("Top matches:")
                    for item in entries[:5]:
                        if not isinstance(item, dict):
                            continue
                        title = item.get("title") or item.get("name") or "Untitled"
                        url = item.get("url") or item.get("source_url") or ""
                        source = item.get("source") or "web"
                        snippet = item.get("snippet") or item.get("content") or ""
                        line = f"- {title} [{source}]"
                        if url:
                            line += f" {url}"
                        if snippet:
                            line += f"\n  {str(snippet)[:220]}"
                        reply_lines.append(line)
        else:
            reply_lines.append(str(result))

        await self._botsignal.send_text(
            request.reply_target,
            "\n".join(reply_lines).strip(),
            source_kind=source_kind,
        )
        return True

    async def handle(self, request: IncomingRequest) -> None:
        """
        The entrypoint for all incoming platform messages.
        System 1 (MiniEngine) attempts to resolve the query instantly (e.g. time, basic OS status, greetings).
        If it requires deep reasoning or tools, it escalates to System 2 (AgentRuntime ReAct Loop).
        """
        # ── Unified Identity Resolution ────────────────────────────────
        # Map platform-specific user ID to canonical RAVEN user for cross-platform continuity
        try:
            from app.core.user_identity import get_identity_store
            identity_store = get_identity_store()
            canonical_id = identity_store.resolve(request.platform, request.user_id)
            request.user_id = canonical_id
        except Exception:
            pass  # Fall back to raw platform user_id if identity store unavailable

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

        # Phase 0.5 — DM pairing enforcement on every channel.
        # Chat channels (telegram, discord, slack, whatsapp, signal,
        # matrix, irc) fail-closed. The web channel fails-open with a
        # banner so the dashboard still loads.
        try:
            security_guard = get_security_guard()
            paired, pair_msg = security_guard.check_dm_pairing(
                request.user_id, request.platform
            )
            if not paired:
                if request.platform == "web":
                    # Web is special — allow but attach a banner flag.
                    request.metadata = getattr(request, "metadata", {}) or {}
                    request.metadata["pairing_banner"] = pair_msg
                else:
                    await self._botsignal.send_text(
                        request.reply_target,
                        pair_msg,
                        source_kind=source_kind,
                    )
                    try:
                        from app.core.metrics import requests_blocked

                        requests_blocked.labels(reason="dm_pairing").inc()
                    except Exception:
                        pass
                    return
        except Exception as exc:
            # Never let a pairing-check failure crash the loop. Log and
            # continue (fail-open on infrastructure, not on policy).
            logger.debug("DM pairing check raised: %s", exc)

        if await self._handle_direct_tool_prompt(request, source_kind):
            return

        # Direct, low-compute internet intelligence commands.
        if await self._handle_internet_intel_direct(request, source_kind):
            return

        # System 1: Fast Reflex Check
        mini_response, escalate_to_prompt = await self._engine.route_message(
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

        # System 2: Deep provider-backed response with fallback (AgentRuntime with full tool access).
        turn_result = await self._agent_runtime.execute_turn(request)
        # Phase 0.2 — feed execution trace to SkillLearner so it can
        # actually write learned skills. Failure must be silent (warned).
        try:
            from app.core.skill_learner import (
                ExecutionTrace,
                get_skill_learner,
            )

            learner = get_skill_learner()
            tool_calls = (turn_result or {}).get("tool_calls") or []
            # Only attempt to learn if the turn actually used tools —
            # simple Q&A isn't worth a skill.
            if tool_calls and (turn_result or {}).get("success"):
                # Determine satisfaction from actual signals:
                # - all tool calls succeeded → likely satisfied
                # - some tool calls failed → less likely satisfied
                _all_tools_ok = all(tc.get("success", False) for tc in tool_calls)
                _response_len = len((turn_result or {}).get("response", ""))
                # Short responses to complex tool-heavy tasks → possible frustration
                _likely_satisfied = _all_tools_ok and _response_len > 50

                trace = ExecutionTrace(
                    interaction_id=(turn_result or {}).get("session_id", ""),
                    user_message=request.text,
                    tool_calls=tool_calls,
                    agent_used=None,
                    response=(turn_result or {}).get("response", ""),
                    success=True,
                    user_satisfied=_likely_satisfied,
                    latency_ms=(turn_result or {}).get("latency_ms", 0.0),
                )
                await learner.observe(trace)
        except Exception as exc:
            logger.debug("SkillLearner observe failed: %s", exc)

        # Phase 1 (v8) — feed every turn to ScheduleLearner so
        # the user's wake/sleep/work-hour patterns accumulate
        # passively.  ScheduleLearner is regex-based and cheap;
        # it returns an empty list for messages that match no
        # pattern, so this is a no-op for the common case.
        # Failure must be silent (warned) — never crashes the loop.
        try:
            from app.core.schedule_learner import get_schedule_learner

            learner = get_schedule_learner()
            learner.learn_from_conversation(request.text)
        except Exception as exc:
            logger.debug("ScheduleLearner learn_from_conversation failed: %s", exc)
