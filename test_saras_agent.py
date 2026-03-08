#!/usr/bin/env python3
"""
test_saras_agent.py — SARAS Full Stack Agent Test Harness
──────────────────────────────────────────────────────────────────────────────
Starts ALL platform connectors + Streamlit dashboard simultaneously:

  • Telegram bot        — receives messages from real Telegram users
  • Discord bot         — receives messages from real Discord users
  • Slack bot           — receives messages from real Slack users
  • Streamlit dashboard — admin UI on port 8501

All connectors funnel into the SAME TestMessageOrchestrator:

  Layer 1 → MiniEngine      (System 1)   — instant reflexes, no LLM
  Layer 2 → AgentRuntime    (System 2)   — full ReAct loop, Killo (tool-calling)
  Layer 3 → TestSwarmManager (System 2b) — 14 specialist workers, random CLI providers

Replies route back to each platform via BotSignal:
  telegram sender  → real Telegram message
  discord  sender  → real Discord message
  cli      sender  → colour-coded terminal output

Random CLI providers assigned to swarm workers at startup:
  • Gemini CLI   →  gemini -p "prompt"
  • Qwen CLI     →  qwen "prompt" -m qwen3-235b-a22b
  • OpenCode CLI →  opencode run "prompt" --model opencode/minimax-m2.5-free

Usage:
  uv run python test_saras_agent.py              # start all bots + dashboard, stream logs
  uv run python test_saras_agent.py --cli        # start all bots + dashboard + CLI REPL
  uv run python test_saras_agent.py --test       # run built-in scenario suite (CLI only)
  uv run python test_saras_agent.py "prompt"     # single-shot CLI, no bots

Debug flags (can be combined with any mode above):
  --debug                 set root logger to DEBUG (all libs visible in terminal)
  --log saras.log         write full DEBUG logs to a file
  --quiet                 suppress all terminal logs (only print output, no WARNING+)

Examples:
  uv run python test_saras_agent.py --debug
  uv run python test_saras_agent.py --cli --debug
  uv run python test_saras_agent.py --test --debug --log test_run.log
  uv run python test_saras_agent.py --log saras.log    # file=DEBUG, terminal=WARNING
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import concurrent.futures.thread as _cft
import json
import logging
import os
import random
import signal
import subprocess
import sys
import threading
import weakref
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── SARAS core ────────────────────────────────────────────────────────────────
from app.core.agency import SwarmManager, WorkerAgent
from app.core.botsignal import BotSignal, SignalPayload, get_botsignal
from app.core.models import IncomingRequest, ReplyTarget, ToolTrace
from app.core.runtime import AgentRuntime
from app.core.security import get_security_guard
from app.minichat.minichat import MiniEngine
from app.settings.config import Config

# ── Platform connectors (same ones used by main.py) ──────────────────────────
from app.telegram import bind_runtime, create_bot
from app.discord import DiscordBot
from app.slack import SlackBot

# ── SARAS agents ──────────────────────────────────────────────────────────────
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

# ── SARAS tools ───────────────────────────────────────────────────────────────
from app.tools.agencytool import AgencyDelegationTool
from app.tools.browsertool import BrowserOperationTool
from app.tools.elevatedtool import ElevatedModeTool
from app.tools.exectool import ExecTool
from app.tools.filetool import AdvancedFileOperationTool
from app.tools.finance import FinanceOperationTool
from app.tools.gittool import GitOperationTool
from app.tools.kgtool import KnowledgeGraphTool
from app.tools.memorytool import MemoryTool
from app.tools.messagingtool import PlatformMessagingTool
from app.tools.network import NetworkTool
from app.tools.news.hackernews import HackerNewsTool
from app.tools.pathchtool import ApplyPatchTool
from app.tools.virustool import VirusTotalTool
from app.tools.webfetch import WebFetchOperationTool
from app.tools.websearch import WebOperationTool
from app.tools.writetool import WriteTodosTool
from app.tools.xaiimagetool import XAIImageUnderstandTool

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# DAEMON THREAD POOL — prevents "Exception ignored in threading._shutdown"
# ──────────────────────────────────────────────────────────────────────────────
# Python 3.12's ThreadPoolExecutor registers every worker thread in the module-
# level `_threads_queues` WeakKeyDict.  At interpreter shutdown, `_python_exit`
# (registered via threading._register_atexit) iterates that dict and calls
# t.join() on every thread.  If an asyncio.to_thread task is still blocked on
# a network call, that join blocks.  A second Ctrl+C then raises
# KeyboardInterrupt inside t.join() → "Exception ignored in threading._shutdown".
#
# Fix: subclass ThreadPoolExecutor and override _adjust_thread_count to:
#   1. Set t.daemon = True  → threading._thread_shutdown() skips daemon threads
#   2. NOT add t to _threads_queues  → _python_exit() never tries to join them
#
# The worker function and all other executor logic are unchanged.


class _DaemonExecutor(concurrent.futures.ThreadPoolExecutor):
    """ThreadPoolExecutor whose workers are daemon threads not registered in
    _threads_queues.  Safe to use as asyncio's default executor."""

    def _adjust_thread_count(self) -> None:
        # Fast path: an idle thread is already available.
        if self._idle_semaphore.acquire(timeout=0):
            return

        # When this executor is garbage-collected, wake all workers so they
        # can exit cleanly (same pattern as the stdlib implementation).
        def weakref_cb(_, q=self._work_queue):
            q.put(None)

        num_threads = len(self._threads)
        if num_threads < self._max_workers:
            thread_name = "%s_%d" % (
                self._thread_name_prefix or self,
                num_threads,
            )
            t = threading.Thread(
                name=thread_name,
                target=_cft._worker,
                args=(
                    weakref.ref(self, weakref_cb),
                    self._work_queue,
                    self._initializer,
                    self._initargs,
                ),
                daemon=True,  # ← skipped by threading._thread_shutdown
            )
            t.start()
            self._threads.add(t)
            # Intentionally NOT added to _cft._threads_queues
            # → _python_exit() will not call t.join() on our threads


# ──────────────────────────────────────────────────────────────────────────────
# ANSI TERMINAL COLOURS
# ──────────────────────────────────────────────────────────────────────────────

CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

_WORKSPACE = "workspace"
_CLI_USER = "cli_test_user"


# ──────────────────────────────────────────────────────────────────────────────
# CLI PROVIDER WRAPPERS
# Used exclusively for swarm worker agents (text-only, no tool_calls needed).
# The main AgentRuntime always uses Killo which supports function calling.
# ──────────────────────────────────────────────────────────────────────────────


class BaseCLIProvider:
    """Base class for subprocess LLM providers."""

    name: str = "cli_base"
    timeout: int = 120

    def _run_cli(self, prompt: str) -> str:
        raise NotImplementedError

    @staticmethod
    def _build_prompt(messages: List[Dict[str, Any]]) -> str:
        """Flatten OpenAI messages array into a single prompt string."""
        parts: List[str] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    c.get("text", "")
                    for c in content
                    if isinstance(c, dict) and c.get("type") == "text"
                )
            content = str(content).strip()
            if not content:
                continue
            if role == "system":
                parts.append(f"[System Instructions]\n{content}")
            elif role == "user":
                parts.append(f"User: {content}")
            elif role == "assistant":
                parts.append(f"Assistant: {content}")
            elif role == "tool":
                tool_name = msg.get("name", "tool")
                parts.append(f"[Tool Result: {tool_name}]\n{content}")
        return "\n\n".join(parts)

    async def chat_completion(
        self,
        *,
        model: str = "",
        messages: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> Dict[str, Any]:
        prompt = self._build_prompt(messages)
        try:
            response = await asyncio.to_thread(self._run_cli, prompt)
            return {
                "success": True,
                "content": response,
                "raw": {
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": response,
                                "tool_calls": None,
                            }
                        }
                    ]
                },
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"{self.name}: timed out after {self.timeout}s",
            }
        except FileNotFoundError:
            return {"success": False, "error": f"{self.name}: CLI not installed"}
        except Exception as exc:
            return {"success": False, "error": f"{self.name}: {exc}"}


class GeminiCLIProvider(BaseCLIProvider):
    """Wraps `gemini -p "prompt"`. Free tier — no --model flag."""

    name = "gemini_cli"

    def _run_cli(self, prompt: str) -> str:
        result = subprocess.run(
            ["gemini", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            env=os.environ.copy(),
        )
        output = (result.stdout or result.stderr or "").strip()
        lines = [
            ln
            for ln in output.splitlines()
            if not any(
                t in ln.lower()
                for t in ["loaded cached", "credentials", "✦", "gemini cli"]
            )
        ]
        return "\n".join(lines).strip() or "No response from Gemini CLI."


class QwenCLIProvider(BaseCLIProvider):
    """Wraps `qwen "prompt" -m qwen3-235b-a22b`."""

    name = "qwen_cli"
    default_model = "qwen3-235b-a22b"

    def _run_cli(self, prompt: str) -> str:
        result = subprocess.run(
            ["qwen", prompt, "-m", self.default_model],
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        raw = result.stdout.strip()
        if raw.startswith("{") or raw.startswith("["):
            try:
                data = json.loads(raw)
                if isinstance(data, dict) and "content" in data:
                    return str(data["content"])
                if isinstance(data, list):
                    texts = [
                        m.get("content", "")
                        for m in data
                        if isinstance(m, dict) and m.get("role") == "assistant"
                    ]
                    if texts:
                        return "\n".join(texts)
            except (json.JSONDecodeError, TypeError):
                pass
        return raw or result.stderr.strip() or "No response from Qwen CLI."


class OpenCodeCLIProvider(BaseCLIProvider):
    """Wraps `opencode run "prompt" --model opencode/minimax-m2.5-free`."""

    name = "opencode_cli"
    default_model = "opencode/minimax-m2.5-free"

    def _run_cli(self, prompt: str) -> str:
        result = subprocess.run(
            ["opencode", "run", prompt, "--model", self.default_model],
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        return (
            result.stdout.strip()
            or result.stderr.strip()
            or "No response from OpenCode CLI."
        )


_CLI_PROVIDER_CLASSES = [GeminiCLIProvider, QwenCLIProvider, OpenCodeCLIProvider]


# ──────────────────────────────────────────────────────────────────────────────
# SAFE TOOL / AGENT HELPERS
# ──────────────────────────────────────────────────────────────────────────────


def _safe_init(cls: type, *args: Any, **kwargs: Any) -> Optional[Any]:
    try:
        instance = cls(*args, **kwargs)
        print(f"  {GREEN}✓{RESET}  {cls.__name__}")
        return instance
    except Exception as exc:
        print(f"  {RED}✗{RESET}  {cls.__name__}: {exc}")
        return None


def _safe_get_tools(agent: Any) -> List[Any]:
    try:
        return list(agent.tools)
    except Exception as exc:
        logger.warning("Agent %s tools failed to init: %s", agent.name, exc)
        return []


# ──────────────────────────────────────────────────────────────────────────────
# CLI BOTSIGNAL SENDER
# Prints colour-coded output to terminal when platform="cli"
# ──────────────────────────────────────────────────────────────────────────────


def _source_color(source_kind: str) -> str:
    sk = (source_kind or "").lower()
    if "mini" in sk:
        return GREEN
    if "swarm" in sk:
        return YELLOW
    if "command" in sk:
        return CYAN
    return BLUE


async def cli_sender(target: ReplyTarget, payload: SignalPayload) -> None:
    source = payload.source_kind or "prompt"
    text = payload.text or payload.caption or ""

    # Status messages (Thinking..., tool calls) render as a single dim line
    if source == "status":
        print(f"{DIM}  ⟩ {text}{RESET}", flush=True)
        return

    color = _source_color(source)

    content_lines = [
        ln
        for ln in text.splitlines()
        if not ln.startswith("[source:") and not ln.startswith("[tool:")
    ]
    clean = "\n".join(content_lines).strip()

    label = source.upper().replace("_", " ")
    print(f"\n{color}{BOLD}━━━ SARAS [{label}] ━━━{RESET}")
    print(f"{color}{clean}{RESET}")

    if payload.tool_traces:
        print(f"\n{DIM}  [Traces]")
        for trace in payload.tool_traces:
            icon = "✓" if trace.success else "✗"
            detail = f": {str(trace.detail)[:90]}" if trace.detail else ""
            print(f"  {icon} {trace.tool_name}.{trace.action}{detail}")
        print(RESET, end="")

    print()


# ──────────────────────────────────────────────────────────────────────────────
# TEST SWARM MANAGER
# Assigns random CLI providers to workers — stable per session, loggable.
# ──────────────────────────────────────────────────────────────────────────────


class TestSwarmManager(SwarmManager):
    """SwarmManager that assigns random CLI providers to each worker agent."""

    def __init__(self, workspace_dir: str = _WORKSPACE) -> None:
        super().__init__(workspace_dir)
        self._agent_providers: Dict[str, BaseCLIProvider] = {}

    def register_agent(self, agent: Any) -> None:
        super().register_agent(agent)
        chosen = random.choice(_CLI_PROVIDER_CLASSES)
        provider = chosen()
        self._agent_providers[agent.name] = provider
        logger.debug(
            "Swarm agent registered: %s  provider=%s", agent.name, provider.name
        )
        print(f"  {YELLOW}•{RESET}  {agent.name:<28} → {MAGENTA}{provider.name}{RESET}")

    async def execute_case_study(
        self,
        request: IncomingRequest,
        tasks: List[Dict[str, Any]],
    ) -> None:
        source_kind = "system2_swarm"
        botsignal = get_botsignal()
        logger.info(
            "SWARM  case study started  user=%s  tasks=%d  agents=%s",
            request.user_id,
            len(tasks),
            [t.get("agent_name") for t in tasks],
        )

        await botsignal.send_text(
            request.reply_target,
            (
                f"🕵️  Case Study Initiated.\n"
                f"Spawning {len(tasks)} parallel sub-agents...\n"
                f"You will receive a synthesised report when complete."
            ),
            source_kind=source_kind,
        )

        workers: List[WorkerAgent] = []
        coroutines = []

        for task_def in tasks:
            agent_name = task_def.get("agent_name")
            if agent_name not in self.available_agents:
                logger.warning("Agent '%s' not registered — skipping.", agent_name)
                continue

            agent_def = self.available_agents[agent_name]
            agent_tools = _safe_get_tools(agent_def)

            worker = WorkerAgent(
                name=agent_def.name,
                role_prompt=agent_def.role_prompt,
                tools=agent_tools,
                workspace_dir=self.workspace_dir,
                provider_name="killo",
                model_name=agent_def.model_name,
            )
            if agent_name in self._agent_providers:
                worker.runtime.provider = self._agent_providers[agent_name]

            workers.append(worker)
            coroutines.append(worker.execute_task(task_def["task"], request))

        if not coroutines:
            await botsignal.send_text(
                request.reply_target,
                "Case study failed: no valid agents found for the requested tasks.",
                source_kind=source_kind,
            )
            return

        results = await asyncio.gather(*coroutines, return_exceptions=True)
        logger.info("SWARM  all workers complete  results=%d", len(results))

        evidence_board = "### 📂 Case Study — Evidence Board\n\n"
        for i, worker in enumerate(workers):
            prov = self._agent_providers.get(worker.name)
            label = f" [{prov.name}]" if prov else ""
            evidence_board += f"#### 🤖 Agent: {worker.name}{label}\n"
            res = results[i]
            if isinstance(res, Exception):
                logger.error(
                    "SWARM  worker %s raised: %s", worker.name, res, exc_info=res
                )
                evidence_board += f"⚠️  Exception: {res}\n\n"
            else:
                logger.debug(
                    "SWARM  worker %s result length=%d", worker.name, len(str(res))
                )
                evidence_board += f"{res}\n\n"

        if "ReviewerQA" in self.available_agents:
            await botsignal.send_text(
                request.reply_target,
                "🧠  Workers finished. Passing evidence board to ReviewerQA for synthesis...",
                source_kind=source_kind,
            )
            reviewer_def = self.available_agents["ReviewerQA"]
            reviewer_tools = _safe_get_tools(reviewer_def)
            reviewer_worker = WorkerAgent(
                name=reviewer_def.name,
                role_prompt=reviewer_def.role_prompt,
                tools=reviewer_tools,
                workspace_dir=self.workspace_dir,
                provider_name="killo",
                model_name=reviewer_def.model_name,
            )
            if "ReviewerQA" in self._agent_providers:
                reviewer_worker.runtime.provider = self._agent_providers["ReviewerQA"]

            final_report = await reviewer_worker.execute_task(
                (
                    "Here is the raw Evidence Board from the worker agents:\n\n"
                    f"{evidence_board}\n\n"
                    "Synthesise this into a final, highly readable report for the user. "
                    "Highlight key findings, flag conflicts, and if you discover any "
                    "permanent facts use the save_memory tool to record them."
                ),
                request,
            )
            await botsignal.send_text(
                request.reply_target,
                final_report,
                source_kind=source_kind,
            )
        else:
            await botsignal.send_text(
                request.reply_target,
                evidence_board,
                source_kind=source_kind,
            )


# ──────────────────────────────────────────────────────────────────────────────
# TEST MESSAGE ORCHESTRATOR
# Drop-in replacement for MessageOrchestrator — identical handle() interface
# so real Telegram and Discord bots can call it directly.
# Uses TestSwarmManager (CLI providers) instead of the default SwarmManager.
# ──────────────────────────────────────────────────────────────────────────────


class TestMessageOrchestrator:
    """
    Full three-layer SARAS orchestrator wired to all platform connectors.

    Compatible with MessageOrchestrator.handle(IncomingRequest) so the
    Telegram and Discord bots can call it exactly as they do in production.
    """

    def __init__(self, botsignal: BotSignal, workspace: str = _WORKSPACE) -> None:
        self._botsignal = botsignal
        logger.info("TestMessageOrchestrator  init  workspace=%s", workspace)

        # ── Layer 1: MiniEngine ───────────────────────────────
        self._engine = MiniEngine()
        logger.debug("MiniEngine initialised")

        # ── Layer 2: AgentRuntime (Killo — tool-calling) ──────
        self._runtime = AgentRuntime(workspace_dir=workspace)

        print(f"\n{CYAN}{BOLD}[TOOL REGISTRY]{RESET}")
        raw_tools = [
            _safe_init(AdvancedFileOperationTool, base_directory=workspace),
            _safe_init(GitOperationTool, repo_path="."),
            _safe_init(NetworkTool),
            _safe_init(WebOperationTool, google_api_key=Config.GEMINI_API_KEY),
            _safe_init(WebFetchOperationTool, google_api_key=Config.GEMINI_API_KEY),
            _safe_init(MemoryTool, workspace),
            _safe_init(WriteTodosTool),
            _safe_init(ApplyPatchTool),
            _safe_init(HackerNewsTool),
            _safe_init(VirusTotalTool),
            _safe_init(KnowledgeGraphTool),
            _safe_init(BrowserOperationTool),
            _safe_init(FinanceOperationTool),
            _safe_init(XAIImageUnderstandTool),
            _safe_init(ExecTool),
            _safe_init(ElevatedModeTool),
            _safe_init(PlatformMessagingTool),
        ]
        tools = [t for t in raw_tools if t is not None]
        for tool in tools:
            self._runtime.register_tool(tool)
            logger.debug("Tool registered: %s", tool.get_name())
        logger.info("Tools loaded: %d / %d", len(tools), len(raw_tools))
        print(f"\n  → {BOLD}{len(tools)}{RESET} / {len(raw_tools)} tools loaded.\n")

        # ── Layer 3: TestSwarmManager (random CLI providers) ──
        print(f"{CYAN}{BOLD}[SWARM REGISTRY]{RESET}")
        self._swarm = TestSwarmManager(workspace_dir=workspace)

        for agent_cls in [
            FinanceAgent,
            ResearcherAgent,
            SecurityAgent,
            ReviewerAgent,
            SysadminAgent,
            DeveloperAgent,
            NewsAgent,
            HomeGuardianAgent,
            HeraldAgent,
            PolymathAgent,
            ConductorAgent,
            ArchivistAgent,
            ConscienceAgent,
        ]:
            try:
                self._swarm.register_agent(agent_cls())
            except Exception as exc:
                print(f"  {RED}✗{RESET}  {agent_cls.__name__}: {exc}")

        try:
            self._swarm.register_agent(PersonalAssistantAgent())
        except Exception as exc:
            print(f"  {RED}✗{RESET}  PersonalAssistantAgent: {exc}")

        # Wire swarm delegation into main runtime
        self._runtime.register_tool(AgencyDelegationTool(self._swarm))

        n_agents = len(self._swarm.available_agents)
        n_tools = len(self._runtime.tools)
        print(
            f"\n  → {BOLD}{n_agents}{RESET} agents  "
            f"|  {BOLD}{n_tools}{RESET} tools registered\n"
        )

    # ── Main entry point — called by ALL platforms ────────────
    async def handle(self, request: IncomingRequest) -> None:
        """
        Entrypoint for Telegram, Discord, and CLI messages.
        Mirrors MessageOrchestrator.handle() exactly.
        """
        source_kind = "command" if request.text.lstrip().startswith("/") else "prompt"
        logger.info(
            "[%s] REQUEST  platform=%s user=%s  text=%r",
            source_kind,
            request.platform,
            request.user_id,
            request.text[:120],
        )

        # Security gate
        security_guard = get_security_guard()
        is_safe, reason = security_guard.analyze_prompt(request.text)
        if not is_safe:
            logger.warning(
                "SECURITY BLOCKED user=%s reason=%s", request.user_id, reason
            )
            await self._botsignal.send_text(
                request.reply_target,
                f"🛡️ Security Alert: {reason}",
                source_kind=source_kind,
            )
            return

        # Layer 1: MiniEngine — instant reflexes (greetings, /time, /server, etc.)
        logger.debug(
            "MINI_ENGINE  routing user=%s text=%r", request.user_id, request.text[:80]
        )
        mini_response, escalate = self._engine.route_message(
            request.user_id, request.text
        )
        if not escalate:
            logger.info(
                "MINI_ENGINE  handled (no escalation)  response=%r", mini_response[:120]
            )
            await self._botsignal.send_text(
                request.reply_target,
                mini_response,
                source_kind="mini_engine",
            )
            return

        # Layer 2: Full ReAct loop with all tools
        logger.info("AGENT_RUNTIME  escalated to ReAct loop  user=%s", request.user_id)
        await self._runtime.execute_turn(request)
        logger.info("AGENT_RUNTIME  turn complete  user=%s", request.user_id)


# ──────────────────────────────────────────────────────────────────────────────
# PLATFORM RUNNER TASKS
# Mirror the _run_telegram / _run_discord pattern from main.py exactly,
# with graceful degradation when tokens are absent.
# ──────────────────────────────────────────────────────────────────────────────


async def _run_telegram(
    stop_event: asyncio.Event,
    orchestrator: TestMessageOrchestrator,
    botsignal: BotSignal,
) -> None:
    token = Config.TELEGRAM_BOT_TOKEN
    if not token or token == "your_telegram_bot_token_here":
        print(f"  {YELLOW}⚠{RESET}  Telegram: TELEGRAM_BOT_TOKEN not set — skipped")
        await stop_event.wait()
        return

    app = None
    try:
        app = create_bot()
        bind_runtime(app, orchestrator, botsignal)

        if app.updater is None:
            raise RuntimeError("Telegram updater unavailable")

        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        print(f"  {GREEN}✓{RESET}  Telegram bot online — listening for messages")

        await stop_event.wait()

    except (asyncio.CancelledError, KeyboardInterrupt):
        # Cancelled externally (e.g. Ctrl+C) — clean up then re-raise
        logger.info("Telegram task cancelled — shutting down bot")
        raise

    except Exception as exc:
        print(f"  {RED}✗{RESET}  Telegram failed: {exc}")
        logger.exception("Telegram bot error")

    finally:
        if app is not None:
            try:
                if app.updater and app.updater.running:
                    await app.updater.stop()
                if app.running:
                    await app.stop()
                await app.shutdown()
            except Exception:
                pass


async def _run_discord(
    stop_event: asyncio.Event,
    orchestrator: TestMessageOrchestrator,
    botsignal: BotSignal,
) -> None:
    token = Config.DISCORD_BOT_TOKEN
    if not token or token == "your_discord_bot_token_here":
        print(f"  {YELLOW}⚠{RESET}  Discord: DISCORD_BOT_TOKEN not set — skipped")
        await stop_event.wait()
        return

    bot: Optional[DiscordBot] = None
    bot_task: Optional[asyncio.Task] = None
    try:
        enable_content = Config.DISCORD_ENABLE_MESSAGE_CONTENT_INTENT
        bot = DiscordBot(
            token,
            Config.DISCORD_CHANNEL_ID,
            orchestrator,
            enable_message_content=enable_content,
        )
        bot.register_output_sender(botsignal)
        print(f"  {GREEN}✓{RESET}  Discord bot connecting...")

        bot_task = asyncio.create_task(bot.start_bot(), name="discord-bot")
        stop_task = asyncio.create_task(stop_event.wait(), name="discord-stop")

        done, pending = await asyncio.wait(
            {bot_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )

        if bot_task in done:
            await bot_task  # re-raise any exception from the bot
        else:
            # stop_event fired — close discord gracefully
            if not bot.is_closed():
                await bot.close()
            bot_task.cancel()
            await asyncio.gather(bot_task, return_exceptions=True)

        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    except (asyncio.CancelledError, KeyboardInterrupt):
        # Cancelled externally (e.g. Ctrl+C) — close discord then re-raise
        logger.info("Discord task cancelled — closing bot")
        if bot is not None and not bot.is_closed():
            try:
                await bot.close()
            except Exception:
                pass
        if bot_task is not None:
            bot_task.cancel()
            await asyncio.gather(bot_task, return_exceptions=True)
        raise  # propagate so asyncio.gather sees CancelledError

    except Exception as exc:
        print(f"  {RED}✗{RESET}  Discord failed: {exc}")
        logger.exception("Discord bot error")


async def _run_slack(
    stop_event: asyncio.Event,
    orchestrator: TestMessageOrchestrator,
    botsignal: BotSignal,
) -> None:
    from app.settings.config import Config as _Config

    bot_token = _Config.SLACK_BOT_TOKEN
    app_token = _Config.SLACK_APP_TOKEN
    if not bot_token or not app_token:
        print(
            f"  {YELLOW}⚠{RESET}  Slack: SLACK_BOT_TOKEN / SLACK_APP_TOKEN not set — skipped"
        )
        await stop_event.wait()
        return

    bot: Optional[SlackBot] = None
    bot_task: Optional[asyncio.Task] = None
    try:
        bot = SlackBot(bot_token, app_token, orchestrator)
        bot.register_output_sender(botsignal)
        print(f"  {GREEN}✓{RESET}  Slack bot connecting...")

        bot_task = asyncio.create_task(bot.start_bot(), name="slack-bot")
        stop_task = asyncio.create_task(stop_event.wait(), name="slack-stop")

        done, pending = await asyncio.wait(
            {bot_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )

        if bot_task in done:
            await bot_task  # re-raise any exception from the bot
        else:
            # stop_event fired — cancel the slack bot task gracefully
            bot_task.cancel()
            await asyncio.gather(bot_task, return_exceptions=True)

        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Slack task cancelled — closing bot")
        if bot_task is not None:
            bot_task.cancel()
            await asyncio.gather(bot_task, return_exceptions=True)
        raise  # propagate so asyncio.gather sees CancelledError

    except Exception as exc:
        print(f"  {RED}✗{RESET}  Slack failed: {exc}")
        logger.exception("Slack bot error")


# ──────────────────────────────────────────────────────────────────────────────
# CLI HELPERS — make an IncomingRequest for a CLI user
# ──────────────────────────────────────────────────────────────────────────────


def _cli_request(text: str, user_id: str = _CLI_USER) -> IncomingRequest:
    return IncomingRequest(
        platform="cli",
        user_id=user_id,
        text=text,
        reply_target=ReplyTarget(platform="cli", chat_id=user_id),
    )


# ──────────────────────────────────────────────────────────────────────────────
# BUILT-IN TEST SCENARIOS
# ──────────────────────────────────────────────────────────────────────────────

TEST_SCENARIOS: List[tuple] = [
    # ── Layer 1 : MiniEngine ─────────────────────────────────
    ("MiniEngine   / greeting", "hello"),
    ("MiniEngine   / how are you", "how are you?"),
    ("MiniEngine   / time", "/time"),
    ("MiniEngine   / server status", "/server"),
    ("MiniEngine   / internet", "/internet"),
    ("MiniEngine   / OS info", "/os"),
    ("MiniEngine   / tools list", "/tools"),
    ("MiniEngine   / identity", "who are you?"),
    # ── Layer 2 : AgentRuntime — text only ───────────────────
    ("AgentRuntime / simple Q", "What is the capital of France?"),
    ("AgentRuntime / explain", "Explain what a ReAct agent loop is in 2 sentences."),
    # ── Layer 2 : AgentRuntime — file_operations ─────────────
    (
        "AgentRuntime / file write",
        "Create a file called saras_test.txt inside the workspace directory "
        "with the content: 'SARAS Full Stack Test — OK'",
    ),
    (
        "AgentRuntime / file read",
        "Read the file workspace/saras_test.txt and show me its content",
    ),
    # ── Layer 2 : AgentRuntime — git_ops ─────────────────────
    ("AgentRuntime / git log", "Show me the last 5 commits in this git repository"),
    # ── Layer 2 : AgentRuntime — web search ──────────────────
    ("AgentRuntime / web search", "Search the web for Python 3.13 release highlights"),
    # ── Layer 2 : AgentRuntime — hacker_news ─────────────────
    ("AgentRuntime / hacker news", "Get the top 5 stories from Hacker News right now"),
    # ── Layer 2 : AgentRuntime — network_tool ────────────────
    (
        "AgentRuntime / network check",
        "Use the network tool to check if we have internet connectivity",
    ),
    # ── Layer 2 : AgentRuntime — save_memory ─────────────────
    (
        "AgentRuntime / memory",
        "Remember this FACT: SARAS is a multi-platform AI assistant built in "
        "Python 3.12 by Swadhin, running on Telegram and Discord",
    ),
    # ── Layer 2 : AgentRuntime — write_todos ─────────────────
    (
        "AgentRuntime / write todos",
        "Create a todo list with 3 tasks: "
        "1) Test all tools, 2) Verify swarm agents, 3) Write final report",
    ),
    # ── Layer 2 : AgentRuntime — exec tool ───────────────────
    (
        "AgentRuntime / exec",
        "Run the shell command: echo 'ExecTool sandboxed test passed'",
    ),
    # ── Layer 3 : SwarmManager — case study ──────────────────
    (
        "SwarmManager / case study",
        "Delegate a case study to the swarm. "
        "Assign WebResearcher to search for recent developments in AI coding assistants, "
        "TrendAnalyst to pull the top HackerNews AI stories today, "
        "and ReviewerQA to synthesise both reports into a final executive summary.",
    ),
]


# ──────────────────────────────────────────────────────────────────────────────
# TEST SUITE RUNNER (CLI only, no bots)
# ──────────────────────────────────────────────────────────────────────────────


async def run_test_suite(
    orchestrator: TestMessageOrchestrator,
    stop_event: asyncio.Event,
) -> None:
    total = len(TEST_SCENARIOS)
    passed = 0
    failed = 0

    print(f"\n{MAGENTA}{BOLD}{'━' * 66}{RESET}")
    print(f"{MAGENTA}{BOLD}  Running {total} test scenarios{RESET}")
    print(f"{MAGENTA}{'━' * 66}{RESET}\n")

    for i, (label, prompt) in enumerate(TEST_SCENARIOS, 1):
        preview = prompt[:72] + ("..." if len(prompt) > 72 else "")
        print(f"{DIM}[{i:02d}/{total}] {label}{RESET}")
        print(f"{DIM}  ► {preview}{RESET}")
        try:
            await orchestrator.handle(_cli_request(prompt))
            passed += 1
        except Exception as exc:
            print(f"{RED}  [ERROR] {exc}{RESET}")
            failed += 1
        print(f"{DIM}{'─' * 50}{RESET}\n")
        await asyncio.sleep(0.5)

    print(
        f"{BOLD}{GREEN}Test suite complete: {passed} passed, {failed} failed.{RESET}\n"
    )
    stop_event.set()


# ──────────────────────────────────────────────────────────────────────────────
# INTERACTIVE REPL (runs alongside real bots)
# ──────────────────────────────────────────────────────────────────────────────


async def run_repl(
    orchestrator: TestMessageOrchestrator,
    stop_event: asyncio.Event,
) -> None:
    n = len(TEST_SCENARIOS)

    print(f"\n{CYAN}{BOLD}{'━' * 66}{RESET}")
    print(
        f"{CYAN}{BOLD}  SARAS  —  Full Stack (Telegram + Discord + Slack + Dashboard + CLI){RESET}"
    )
    print(f"{CYAN}{'━' * 66}{RESET}")
    print(
        f"{DIM}"
        f"  /test      run all {n} built-in CLI scenarios\n"
        f"  /tools     list registered tools\n"
        f"  /agents    list swarm agents + CLI providers\n"
        f"  /platforms show which bots are online\n"
        f"  /clear     wipe the CLI session\n"
        f"  /quit      stop all bots and exit\n"
        f"\n"
        f"  Routing:  {GREEN}MiniEngine{RESET}{DIM}"
        f"  →  {BLUE}AgentRuntime (Killo){RESET}{DIM}"
        f"  →  {YELLOW}Swarm (Gemini|Qwen|OpenCode){RESET}"
    )
    print(f"{CYAN}{'━' * 66}{RESET}\n")

    botsignal = get_botsignal()

    while not stop_event.is_set():
        try:
            raw = await asyncio.to_thread(input, f"{BOLD}You{RESET} › ")
            raw = raw.strip()
        except asyncio.CancelledError:
            # Task was cancelled (Ctrl+C or stop_event) — exit cleanly
            break
        except (EOFError, KeyboardInterrupt):
            print(f"\n{DIM}Goodbye.{RESET}\n")
            stop_event.set()
            break

        if not raw:
            continue

        cmd = raw.lower()

        if cmd in {"/quit", "/exit", "quit", "exit", "q"}:
            print(f"\n{DIM}Stopping all bots... Goodbye.{RESET}\n")
            stop_event.set()
            break

        elif cmd == "/platforms":
            senders = botsignal._senders if hasattr(botsignal, "_senders") else {}
            print(f"\n{CYAN}{BOLD}[ACTIVE PLATFORMS]{RESET}")
            for name in ["telegram", "discord", "slack", "cli"]:
                status = (
                    f"{GREEN}online{RESET}"
                    if name in senders
                    else f"{RED}offline{RESET}"
                )
                print(f"  {CYAN}•{RESET} {name:<12} {status}")
            print()

        elif cmd == "/tools":
            tools = orchestrator._runtime.tools
            print(f"\n{CYAN}{BOLD}[TOOLS — {len(tools)} registered]{RESET}")
            for name in sorted(tools.keys()):
                desc = tools[name].get_description()[:60]
                print(f"  {GREEN}•{RESET} {name:<32}  {DIM}{desc}...{RESET}")
            print()

        elif cmd == "/agents":
            agents = orchestrator._swarm.available_agents
            providers = orchestrator._swarm._agent_providers
            print(f"\n{YELLOW}{BOLD}[SWARM AGENTS — {len(agents)} registered]{RESET}")
            for name, agent_def in agents.items():
                prov = providers.get(name)
                prov_str = prov.name if prov else "killo"
                tools = _safe_get_tools(agent_def)
                tool_str = ", ".join(t.get_name() for t in tools) or "none"
                print(f"  {YELLOW}•{RESET} {name:<28} [{MAGENTA}{prov_str}{RESET}]")
                print(f"      {DIM}tools: {tool_str}{RESET}")
            print()

        elif cmd == "/clear":
            session_file = Path(f"{_WORKSPACE}/sessions/cli_{_CLI_USER}.jsonl")
            if session_file.exists():
                session_file.unlink()
                print(f"{GREEN}CLI session cleared.{RESET}\n")
            else:
                print(f"{DIM}No active CLI session.{RESET}\n")

        elif cmd == "/test":
            await run_test_suite(orchestrator, asyncio.Event())  # local stop only

        else:
            await orchestrator.handle(_cli_request(raw))


# ──────────────────────────────────────────────────────────────────────────────
# STREAMLIT DASHBOARD RUNNER
# ──────────────────────────────────────────────────────────────────────────────


async def _run_streamlit_dashboard(stop_event: asyncio.Event) -> None:
    """Spawn the Streamlit admin dashboard as a subprocess.

    Always starts (no config gate) — this is the test harness, dashboard is
    always useful.  Runs on STREAMLIT_DASHBOARD_PORT (default 8501).
    """
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        "app/dashboard/dashboard.py",
        "--server.port",
        str(Config.STREAMLIT_DASHBOARD_PORT),
        "--server.address",
        Config.STREAMLIT_DASHBOARD_HOST,
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    print(
        f"  {GREEN}✓{RESET}  Streamlit dashboard → "
        f"http://{Config.STREAMLIT_DASHBOARD_HOST}:{Config.STREAMLIT_DASHBOARD_PORT}"
    )

    try:
        await stop_event.wait()
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
        logger.info("Streamlit dashboard shut down.")


# ──────────────────────────────────────────────────────────────────────────────
# LOG TAIL — streams workspace/saras.log to terminal (default mode)
# ──────────────────────────────────────────────────────────────────────────────

_LOG_LEVEL_COLORS = {
    "DEBUG": DIM,
    "INFO": GREEN,
    "WARNING": YELLOW,
    "ERROR": RED,
    "CRITICAL": f"{RED}{BOLD}",
}


async def _tail_log(stop_event: asyncio.Event, log_file: str) -> None:
    """Stream the JSON-lines log file to the terminal with colour coding.

    Runs until stop_event is set (Ctrl+C).  This replaces the CLI REPL as
    the default foreground activity.
    """
    log_path = Path(log_file)

    # Wait for log file to appear (might not exist yet on first run)
    while not log_path.exists() and not stop_event.is_set():
        await asyncio.sleep(0.2)

    if stop_event.is_set():
        return

    print(f"\n{CYAN}{BOLD}{'━' * 66}{RESET}")
    print(f"{CYAN}{BOLD}  SARAS  —  Live Log Stream{RESET}")
    print(f"{CYAN}{'━' * 66}{RESET}")
    print(f"{DIM}  source: {log_file}")
    print(f"  Press Ctrl+C to stop all services and exit{RESET}")
    print(f"{CYAN}{'━' * 66}{RESET}\n")

    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            # Seek to end — only show new entries
            fh.seek(0, 2)

            while not stop_event.is_set():
                line = fh.readline()
                if not line:
                    await asyncio.sleep(0.1)
                    continue

                line = line.rstrip()
                if not line:
                    continue

                # Try to parse JSON log line for coloured output
                try:
                    entry = json.loads(line)
                    lvl = entry.get("lvl", "INFO")
                    ts = entry.get("t", "")
                    name = entry.get("name", "")
                    msg = entry.get("msg", "")

                    color = _LOG_LEVEL_COLORS.get(lvl, "")
                    # Compact: timestamp level name message
                    ts_short = ts.split("T")[1] if "T" in ts else ts
                    print(
                        f"{DIM}{ts_short}{RESET} "
                        f"{color}{lvl:<8}{RESET} "
                        f"{DIM}{name}{RESET}  "
                        f"{msg}"
                    )
                except (json.JSONDecodeError, TypeError):
                    # Plain text line — print as-is
                    print(f"{DIM}{line}{RESET}")

    except asyncio.CancelledError:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────


def _setup_logging(args: List[str]) -> str:
    """
    Parse debug/log flags from argv, configure root logger, return log file path.

    Flags (may appear anywhere in argv):
      --debug        set terminal handler to DEBUG (default: WARNING)
      --quiet        suppress terminal handler entirely (only file gets logs)
      --log FILE     write ALL logs (DEBUG) to FILE in JSON-lines format
                     (default file when --log has no value: workspace/saras.log)

    The log file is ALWAYS written at DEBUG level regardless of --debug.
    JSON lines format:  {"t": "2026-…", "lvl": "INFO", "name": "…", "msg": "…"}
    """
    Path(_WORKSPACE).mkdir(exist_ok=True)

    debug_mode = "--debug" in args
    quiet_mode = "--quiet" in args

    # Resolve log file path
    log_file: Optional[str] = None
    if "--log" in args:
        idx = args.index("--log")
        # If next token exists and doesn't start with '--', it's the filename
        if idx + 1 < len(args) and not args[idx + 1].startswith("--"):
            log_file = args[idx + 1]
        else:
            log_file = f"{_WORKSPACE}/saras.log"
    else:
        # Always log to workspace/saras.log so log_panel.py always has a source
        log_file = f"{_WORKSPACE}/saras.log"

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # capture everything; handlers filter

    # ── Terminal handler ──────────────────────────────────────────────────────
    if not quiet_mode:
        terminal_handler = logging.StreamHandler(sys.stderr)
        terminal_handler.setLevel(logging.DEBUG if debug_mode else logging.WARNING)
        terminal_handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        root.addHandler(terminal_handler)

    # ── File handler (JSON lines, always DEBUG) ───────────────────────────────
    class _JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            self.formatException  # ensure exc_text populated
            msg = record.getMessage()
            if record.exc_info:
                msg += "\n" + self.formatException(record.exc_info)
            return json.dumps(
                {
                    "t": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
                    "ms": int(record.msecs),
                    "lvl": record.levelname,
                    "name": record.name,
                    "msg": msg,
                },
                ensure_ascii=False,
            )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(_JsonFormatter())
    root.addHandler(file_handler)

    # ── Silence noisy third-party libs on terminal (still go to file) ─────────
    if not debug_mode:
        for noisy in ("httpx", "httpcore", "urllib3", "asyncio", "telegram", "discord"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    # Emit a startup line so the log file is never empty on first run
    _startup_logger = logging.getLogger("saras.startup")
    _startup_logger.info(
        "SARAS started  debug=%s  log_file=%s  args=%s",
        debug_mode,
        log_file,
        sys.argv[1:],
    )

    return log_file


async def _main_async() -> None:
    args = sys.argv[1:]

    # Strip flag tokens so they don't pollute mode detection below
    clean_args = [
        a
        for i, a in enumerate(args)
        if a not in ("--debug", "--quiet", "--log", "--cli")
        and not (i > 0 and args[i - 1] == "--log" and not a.startswith("--"))
    ]

    log_file = _setup_logging(args)

    debug_mode = "--debug" in args
    cli_mode = "--cli" in args
    if debug_mode:
        print(
            f"{DIM}[logging] DEBUG → stderr  |  ALL → {log_file}{RESET}",
            file=sys.stderr,
        )
    else:
        print(
            f"{DIM}[logging] WARNING → stderr  |  ALL → {log_file}{RESET}",
            file=sys.stderr,
        )

    # ── Single-shot mode: no bots, just one CLI prompt ────────
    if clean_args and clean_args[0] != "--test":
        prompt = " ".join(clean_args)
        botsignal = get_botsignal()
        botsignal.register_sender("cli", cli_sender)
        print(f"\n{BOLD}Initialising SARAS...{RESET}")
        orchestrator = TestMessageOrchestrator(botsignal)
        print(f"{DIM}Single-shot: {prompt}{RESET}\n")
        await orchestrator.handle(_cli_request(prompt))
        return

    # ── Test suite mode: CLI only, no bots ───────────────────
    if "--test" in clean_args or "--test" in args:
        botsignal = get_botsignal()
        botsignal.register_sender("cli", cli_sender)
        print(f"\n{BOLD}Initialising SARAS Full Agent Test Harness...{RESET}")
        orchestrator = TestMessageOrchestrator(botsignal)
        stop_event = asyncio.Event()
        await run_test_suite(orchestrator, stop_event)
        return

    # ── Full stack mode: bots + dashboard + (logs or CLI REPL) ──
    stop_event = asyncio.Event()
    botsignal = get_botsignal()
    botsignal.register_sender("cli", cli_sender)

    print(f"\n{BOLD}Initialising SARAS Full Stack...{RESET}")
    orchestrator = TestMessageOrchestrator(botsignal)

    print(f"\n{CYAN}{BOLD}[STARTING PLATFORM CONNECTORS]{RESET}")

    # Start all platform tasks + dashboard concurrently
    telegram_task = asyncio.create_task(
        _run_telegram(stop_event, orchestrator, botsignal), name="telegram"
    )
    discord_task = asyncio.create_task(
        _run_discord(stop_event, orchestrator, botsignal), name="discord"
    )
    slack_task = asyncio.create_task(
        _run_slack(stop_event, orchestrator, botsignal), name="slack"
    )
    dashboard_task = asyncio.create_task(
        _run_streamlit_dashboard(stop_event), name="streamlit-dashboard"
    )

    all_tasks = {telegram_task, discord_task, slack_task, dashboard_task}

    if cli_mode:
        # --cli flag: run interactive REPL as foreground
        foreground_task = asyncio.create_task(
            run_repl(orchestrator, stop_event), name="cli-repl"
        )
    else:
        # Default: stream live logs to terminal
        foreground_task = asyncio.create_task(
            _tail_log(stop_event, log_file), name="log-tail"
        )

    all_tasks.add(foreground_task)

    # ── Signal handling: first Ctrl+C → graceful, second → force exit ─────
    _sigint_count = 0
    loop = asyncio.get_running_loop()

    def _handle_sigint() -> None:
        nonlocal _sigint_count
        _sigint_count += 1
        if _sigint_count == 1:
            print(
                f"\n{YELLOW}Shutting down gracefully... (press Ctrl+C again to force quit){RESET}"
            )
            stop_event.set()
        else:
            print(f"\n{RED}Force quit.{RESET}")
            os._exit(0)

    try:
        loop.add_signal_handler(signal.SIGINT, _handle_sigint)
        loop.add_signal_handler(signal.SIGTERM, _handle_sigint)
    except NotImplementedError:
        pass  # Windows — fall back to default KeyboardInterrupt handling

    # Wait: if any one finishes (REPL quit, bot crash, Ctrl+C), stop all
    try:
        done, pending = await asyncio.wait(
            all_tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
    except (asyncio.CancelledError, KeyboardInterrupt):
        done, pending = set(), all_tasks

    # Signal everyone else to stop, then cancel + gather with timeout
    stop_event.set()
    for task in pending:
        task.cancel()
    try:
        await asyncio.wait_for(
            asyncio.gather(*pending, return_exceptions=True),
            timeout=3.0,
        )
    except (asyncio.TimeoutError, asyncio.CancelledError):
        pass

    # Surface any exception from the finished tasks
    for task in done:
        if not task.cancelled():
            try:
                exc = task.exception()
            except asyncio.CancelledError:
                continue
            if exc is not None:
                logger.error("Task %s raised: %s", task.get_name(), exc)

    print(f"\n{DIM}All services stopped.{RESET}\n")


def main() -> None:
    # Use a manually managed event loop so we can install _DaemonExecutor as
    # the default executor BEFORE any coroutines run.  This ensures every
    # asyncio.to_thread() call spawns daemon threads that are NOT registered in
    # concurrent.futures.thread._threads_queues.  Without this, a second Ctrl+C
    # during interpreter shutdown triggers "Exception ignored in
    # threading._shutdown" because _python_exit() tries to t.join() threads
    # that are still blocked on network I/O.
    loop = asyncio.new_event_loop()
    loop.set_default_executor(_DaemonExecutor(thread_name_prefix="saras-io"))
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_main_async())
    except KeyboardInterrupt:
        # Signal handler in _main_async handles graceful shutdown.
        # If we land here, just exit immediately — no more waiting.
        pass
    finally:
        # Fast cleanup — don't block on anything.  Daemon threads will die
        # with the process.  Suppress all errors to avoid noisy tracebacks.
        try:
            pending = asyncio.all_tasks(loop)
            for t in pending:
                t.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.wait_for(
                        asyncio.gather(*pending, return_exceptions=True),
                        timeout=1.0,
                    )
                )
        except Exception:
            pass
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        asyncio.set_event_loop(None)
        loop.close()


if __name__ == "__main__":
    main()
