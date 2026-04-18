import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.bootstrapper import Bootstrapper
from app.core.botsignal import BotSignal, get_botsignal
from app.core.models import IncomingRequest, SignalPayload, ToolTrace
from app.core.multimodal import MultimodalContextBuilder
from app.core.proactive import schedule_follow_up
from app.core.planner import ResultVerifier, TaskPlanner
from app.core.model_router import ModelRouter
from app.core.policy import get_policy_engine
from app.core.session import SessionManager
from app.provider.factory import create_provider
from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class AgentRuntime:
    """The embedded execution environment that manages the lifecycle of an agent's turn with a ReAct loop."""

    def __init__(
        self,
        workspace_dir: str = "workspace",
        provider_name: str = "killo",
        model_name: str = "qwen/qwen3-coder:free",
    ):
        self.workspace_dir = Path(workspace_dir)
        self.session_manager = SessionManager(workspace_dir)
        self.bootstrapper = Bootstrapper(workspace_dir)
        self.provider = create_provider(provider_name)
        self.model_name = model_name
        self.botsignal = get_botsignal()
        self.emit_status_messages = True
        self.tools: Dict[str, BaseTool] = {}
        self.planner = TaskPlanner()
        self.verifier = ResultVerifier()
        self.model_router = ModelRouter(self.provider, self.model_name)
        self.multimodal_builder = MultimodalContextBuilder()
        self.policy_engine = get_policy_engine()

    def register_tool(self, tool: BaseTool):
        self.tools[tool.get_name()] = tool

    def _maybe_schedule_follow_up(self, request: IncomingRequest, content: str) -> None:
        lower = (request.text + " " + content).lower()
        if any(
            phrase in lower for phrase in ("follow up", "get back to you", "remind me")
        ):
            try:
                schedule_follow_up(
                    platform=request.platform,
                    user_id=request.user_id,
                    chat_id=request.reply_target.chat_id,
                    question=request.text,
                    hours=24,
                )
            except Exception as exc:
                logger.debug("Failed to schedule follow-up: %s", exc)

    def get_session_id(self, request: IncomingRequest) -> str:
        if request.conversation_id:
            return f"{request.platform}_{request.conversation_id}"
        return f"{request.platform}_{request.user_id}"

    def _build_openai_tools(self) -> List[Dict[str, Any]]:
        """Converts registered BaseTools into OpenAI JSON schema tool array."""
        openai_tools = []
        for name, tool in self.tools.items():
            schema = tool.get_schema()
            properties = {}
            required = []
            for param in schema.parameters:
                prop = {"type": param.type, "description": param.description}
                if param.enum:
                    prop["enum"] = param.enum
                properties[param.name] = prop
                if param.required:
                    required.append(param.name)

            openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": schema.name,
                        "description": schema.description,
                        "parameters": {
                            "type": "object",
                            "properties": properties,
                            "required": required,
                        },
                    },
                }
            )
        return openai_tools

    async def execute_turn(
        self, request: IncomingRequest, streaming: bool = False
    ) -> None:
        session_id = self.get_session_id(request)
        source_kind = "command" if request.text.lstrip().startswith("/") else "prompt"

        plan = self.planner.plan(request.text)
        route_decision = await self.model_router.resolve(request.text)
        route_kind = route_decision.route_kind
        self.provider = route_decision.provider
        self.model_name = route_decision.model_name

        messages = self.session_manager.load_session(session_id)

        if not messages:
            system_content = self.bootstrapper.build_system_prompt(
                query=request.text,
                user_id=request.user_id,
            )
            system_prompt = {"role": "system", "content": system_content}
            messages.append(system_prompt)
            self.session_manager.append_message(session_id, system_prompt)

        if plan.steps:
            plan_message = {
                "role": "system",
                "content": "Planner: "
                + " | ".join(
                    f"{step.step}:{step.action}:{step.description}"
                    for step in plan.steps
                ),
            }
            messages.append(plan_message)
            self.session_manager.append_message(session_id, plan_message)

        # Build user message (handle True Native Multimodality)
        if request.image_urls:
            content_array = [{"type": "text", "text": request.text}]
            for url in request.image_urls:
                content_array.append({"type": "image_url", "image_url": {"url": url}})
            user_msg = {"role": "user", "content": content_array}
        else:
            user_msg = {"role": "user", "content": request.text}

        multimodal_context = self.multimodal_builder.from_request(
            request,
            memory_snippets=self.bootstrapper._read_and_truncate(
                "AGENTS.md", max_chars=240
            ).splitlines()[:5],
        )
        # SARAS stays DB-only: monitoring-owned video/semantic fusion stays external.
        if multimodal_context.has_signal():
            messages.append({"role": "system", "content": multimodal_context.render()})

        messages.append(user_msg)
        self.session_manager.append_message(session_id, user_msg)

        openai_tools = self._build_openai_tools()
        max_turns = 6
        turn_count = 0
        # ── Loop guardrails ────────────────────────────────────────────
        MAX_SAME_TOOL_STREAK = (
            3  # force synthesis after N consecutive identical tool calls
        )
        _last_tool_name: str | None = None
        _same_tool_streak = 0

        traces = []

        # Let the user know we're thinking before the first LLM call
        if self.emit_status_messages:
            await self.botsignal.send_text(
                request.reply_target,
                "⏳ Thinking...",
                source_kind="status",
            )
        logger.info(
            "AGENT_RUNTIME  begin_react_loop  session=%s  tools=%d",
            session_id,
            len(openai_tools),
        )

        while turn_count < max_turns:
            turn_count += 1
            logger.debug(
                "AGENT_RUNTIME  llm_call  session=%s  turn=%d  messages=%d",
                session_id,
                turn_count,
                len(messages),
            )
            try:
                kwargs = {}
                if openai_tools:
                    kwargs["tools"] = openai_tools

                # ── Streaming path (edit-based, no tool calls) ──────────────
                if (
                    streaming
                    and not openai_tools
                    and hasattr(self.provider, "chat_completion_stream")
                ):
                    import time as _time  # noqa: PLC0415

                    buffer = ""
                    last_edit = _time.monotonic()
                    sent_msg = False

                    async for token in self.provider.chat_completion_stream(
                        model=self.model_name, messages=messages
                    ):
                        buffer += token
                        if not sent_msg or _time.monotonic() - last_edit > 0.5:
                            await self.botsignal.send_text(
                                request.reply_target,
                                buffer[:4000],
                                source_kind=source_kind,
                                tool_traces=traces,
                            )
                            last_edit = _time.monotonic()
                            sent_msg = True

                    if buffer:
                        # Final send with full content
                        await self.botsignal.send_text(
                            request.reply_target,
                            buffer[:4000],
                            source_kind=source_kind,
                            tool_traces=traces,
                        )
                        # Store assistant message in session
                        asst_msg = {"role": "assistant", "content": buffer}
                        messages.append(asst_msg)
                        self.session_manager.append_message(session_id, asst_msg)
                    break
                # ── End streaming path ──────────────────────────────────────

                if hasattr(self.provider, "chat_completion_resilient"):
                    res = await self.provider.chat_completion_resilient(
                        messages=messages,
                        preferred_models=[self.model_name],
                        free_only_guard=True,
                        **kwargs,
                    )
                else:
                    res = await self.provider.chat_completion(
                        model=self.model_name, messages=messages, **kwargs
                    )

                if not res.get("success"):
                    # Try Ollama as resilient local fallback before giving up
                    try:
                        from app.providers.ollama.client import OllamaProvider  # noqa: PLC0415
                        from app.settings.config import Config  # noqa: PLC0415

                        if Config.OLLAMA_BASE_URL:
                            _ollama = OllamaProvider(
                                Config.OLLAMA_BASE_URL, Config.OLLAMA_MODEL
                            )
                            if await _ollama.health():
                                logger.warning(
                                    "AGENT_RUNTIME  ollama_fallback  session=%s",
                                    session_id,
                                )
                                res = await _ollama.chat_completion(
                                    messages=messages, **kwargs
                                )
                    except Exception as _ollama_exc:
                        logger.debug("Ollama fallback failed: %s", _ollama_exc)

                if not res.get("success"):
                    error_msg = f"Provider Error: {res.get('error', 'Unknown error')}"
                    logger.error(
                        "AGENT_RUNTIME  provider_error  session=%s  error=%s",
                        session_id,
                        error_msg,
                    )
                    await self.botsignal.send_text(
                        request.reply_target,
                        error_msg,
                        source_kind=source_kind,
                        tool_traces=traces,
                    )
                    break

                raw_msg = res.get("raw", {}).get("choices", [{}])[0].get("message", {})
                content = raw_msg.get("content") or ""
                tool_calls = raw_msg.get("tool_calls")

                # Append assistant message
                asst_msg = {"role": "assistant", "content": content}
                if tool_calls:
                    asst_msg["tool_calls"] = tool_calls
                messages.append(asst_msg)
                self.session_manager.append_message(session_id, asst_msg)

                if not tool_calls:
                    # Final response achieved
                    if not content:
                        content = "I have completed the task."
                    logger.info(
                        "AGENT_RUNTIME  final_response  session=%s  turn=%d  len=%d",
                        session_id,
                        turn_count,
                        len(content),
                    )
                    await self.botsignal.send_text(
                        request.reply_target,
                        content,
                        source_kind=source_kind,
                        tool_traces=traces,
                    )
                    verification = self.verifier.verify(plan, content)
                    if not verification.get("success"):
                        logger.warning(
                            "AGENT_RUNTIME  verification_issue  session=%s  findings=%s",
                            session_id,
                            verification.get("findings"),
                        )
                    self._maybe_schedule_follow_up(request, content)
                    break

                # Execute tools
                tool_names = [
                    tc.get("function", {}).get("name", "unknown") for tc in tool_calls
                ]
                logger.debug(
                    "AGENT_RUNTIME  tool_calls  session=%s  turn=%d  tools=%s",
                    session_id,
                    turn_count,
                    tool_names,
                )

                # ── Repeated-tool streak detection ─────────────────────
                primary_tool = tool_names[0] if tool_names else None
                if primary_tool == _last_tool_name:
                    _same_tool_streak += 1
                else:
                    _same_tool_streak = 1
                    _last_tool_name = primary_tool

                # If the LLM keeps hammering the same tool, force it to
                # synthesize from what it already has.
                if _same_tool_streak >= MAX_SAME_TOOL_STREAK:
                    logger.warning(
                        "AGENT_RUNTIME  tool_streak_breaker  session=%s  tool=%s  streak=%d",
                        session_id,
                        primary_tool,
                        _same_tool_streak,
                    )
                    nudge = {
                        "role": "user",
                        "content": (
                            "[SYSTEM] You have already called the same tool "
                            f"{_same_tool_streak} times in a row. You have enough "
                            "information. Synthesize a final answer NOW from the "
                            "data you have collected. Do NOT call any more tools."
                        ),
                    }
                    messages.append(nudge)
                    self.session_manager.append_message(session_id, nudge)
                    # Remove tools from next LLM call to force text-only response
                    openai_tools = []
                    continue  # re-enter the loop — next call has no tools

                for tc in tool_calls:
                    function_name = tc.get("function", {}).get("name")
                    try:
                        args = json.loads(tc.get("function", {}).get("arguments", "{}"))
                    except Exception:
                        args = {}

                    # Notify user which tool is running
                    if self.emit_status_messages:
                        await self.botsignal.send_text(
                            request.reply_target,
                            f"🔧 {function_name}...",
                            source_kind="status",
                        )
                    logger.debug(
                        "AGENT_RUNTIME  tool_execute  session=%s  tool=%s",
                        session_id,
                        function_name,
                    )

                    if function_name in self.tools:
                        tool = self.tools[function_name]
                        try:
                            decision = self.policy_engine.evaluate(
                                tool,
                                user_id=request.user_id,
                                agent_name=getattr(self, "name", None),
                            )
                            if not decision.allowed:
                                traces.append(
                                    ToolTrace(
                                        tool_name=function_name,
                                        action="policy_check",
                                        success=False,
                                        detail=decision.reason,
                                    )
                                )
                                if decision.requires_confirmation:
                                    await self.botsignal.send_confirmation_request(
                                        request.reply_target,
                                        f"Confirmation required for {function_name}",
                                        decision.reason,
                                        source_kind=source_kind,
                                    )
                                else:
                                    await self.botsignal.send_text(
                                        request.reply_target,
                                        f"Action blocked: {decision.reason}",
                                        source_kind=source_kind,
                                        tool_traces=traces,
                                    )
                                break
                            args["_request"] = request
                            result = await tool.execute(**args)
                            result_str = json.dumps(result, default=str)
                            logger.debug(
                                "AGENT_RUNTIME  tool_success  session=%s  tool=%s  result_len=%d",
                                session_id,
                                function_name,
                                len(result_str),
                            )
                            traces.append(
                                ToolTrace(
                                    tool_name=function_name,
                                    action="execute",
                                    success=True,
                                    detail=str(args),
                                )
                            )
                        except Exception as e:
                            result_str = json.dumps({"error": str(e)})
                            logger.warning(
                                "AGENT_RUNTIME  tool_error  session=%s  tool=%s  error=%s",
                                session_id,
                                function_name,
                                e,
                            )
                            traces.append(
                                ToolTrace(
                                    tool_name=function_name,
                                    action="execute",
                                    success=False,
                                    detail=str(e),
                                )
                            )
                    else:
                        result_str = json.dumps(
                            {"error": f"Tool {function_name} not found"}
                        )
                        logger.warning(
                            "AGENT_RUNTIME  tool_not_found  session=%s  tool=%s",
                            session_id,
                            function_name,
                        )
                        traces.append(
                            ToolTrace(
                                tool_name=function_name,
                                action="execute",
                                success=False,
                                detail="Tool not found",
                            )
                        )

                    tool_msg = {
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "name": function_name,
                        "content": result_str,
                    }
                    messages.append(tool_msg)
                    self.session_manager.append_message(session_id, tool_msg)

                # ── Penultimate turn: inject synthesis nudge ───────────
                if turn_count == max_turns - 1:
                    nudge = {
                        "role": "user",
                        "content": (
                            "[SYSTEM] This is your last tool turn. On the next "
                            "response you MUST provide a final answer to the user. "
                            "Synthesize everything you have gathered so far."
                        ),
                    }
                    messages.append(nudge)
                    self.session_manager.append_message(session_id, nudge)

            except Exception as e:
                logger.error(f"Runtime error: {e}", exc_info=True)
                try:
                    error_text = f"Internal Runtime Error: {str(e)}"
                    # Truncate to stay within platform limits
                    await self.botsignal.send_text(
                        request.reply_target,
                        error_text[:1900],
                        source_kind=source_kind,
                        tool_traces=traces,
                    )
                except Exception:
                    logger.error("Failed to send error message to user", exc_info=True)
                break
        else:
            # ── Max turns exhausted — force a final answer ─────────────
            logger.warning(
                "AGENT_RUNTIME  max_turns_exhausted  session=%s  turns=%d",
                session_id,
                max_turns,
            )
            # One last LLM call with no tools to force text generation
            nudge = {
                "role": "user",
                "content": (
                    "[SYSTEM] Tool budget exhausted. Provide your best final "
                    "answer to the user NOW, based on all the information you "
                    "have gathered. Do NOT call any tools."
                ),
            }
            messages.append(nudge)
            self.session_manager.append_message(session_id, nudge)
            try:
                if hasattr(self.provider, "chat_completion_resilient"):
                    res = await self.provider.chat_completion_resilient(
                        messages=messages,
                        preferred_models=[self.model_name],
                        free_only_guard=True,
                    )
                else:
                    res = await self.provider.chat_completion(
                        model=self.model_name, messages=messages
                    )
                if res.get("success"):
                    raw_msg = (
                        res.get("raw", {}).get("choices", [{}])[0].get("message", {})
                    )
                    content = raw_msg.get("content") or "I have completed the task."
                else:
                    content = "I wasn't able to fully answer — please try rephrasing your question."
            except Exception:
                content = "I wasn't able to fully answer — please try rephrasing your question."

            asst_msg = {"role": "assistant", "content": content}
            messages.append(asst_msg)
            self.session_manager.append_message(session_id, asst_msg)
            await self.botsignal.send_text(
                request.reply_target,
                content,
                source_kind=source_kind,
                tool_traces=traces,
            )
            verification = self.verifier.verify(plan, content)
            if not verification.get("success"):
                logger.warning(
                    "AGENT_RUNTIME  verification_issue  session=%s  findings=%s",
                    session_id,
                    verification.get("findings"),
                )
            self._maybe_schedule_follow_up(request, content)

        self.session_manager.summarize_session(session_id)
        self.session_manager.prune_session(session_id)
