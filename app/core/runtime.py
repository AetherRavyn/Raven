import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.bootstrapper import Bootstrapper
from app.core.botsignal import BotSignal, get_botsignal
from app.core.models import IncomingRequest, SignalPayload, ToolTrace
from app.core.multimodal import MultimodalContextBuilder
from app.core.persona import get_persona_engine
from app.core.proactive import schedule_follow_up
from app.core.planner import ResultVerifier, TaskPlanner
from app.core.model_router import ModelRouter
from app.core.policy import get_policy_engine
from app.core.metrics import llm_calls_total, llm_duration_seconds, tool_calls_total
from app.core.memory_manager import MemoryManager
from app.core.user_profile import UserProfileStore
from app.core.workspace_graph import WorkspaceGraph
from app.core.task_inbox import TaskInboxStore
from app.core.task_ledger import TaskLedger
from app.core.hooks import HookDispatcher
from app.core.workflow_engine import WorkflowEngine
from app.core.standing_orders import StandingOrderStore
from app.core.feedback import FeedbackStore
from app.core.session import SessionManager
from app.provider.factory import create_provider
from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class AgentRuntime:
    """The embedded execution environment that manages the lifecycle of an agent's turn with a ReAct loop."""

    def __init__(
        self,
        workspace_dir: str | None = None,
        provider_name: str = "killo",
        model_name: str = "qwen/qwen3-coder:free",
    ):
        from app.settings.config import Config
        from app.core.model_router import AutoModelRouter

        requested_provider = (provider_name or "killo").strip().lower()
        requested_model = (model_name or "").strip()
        configured_provider = (getattr(Config, "LLM_PROVIDER", "auto") or "auto").strip().lower()
        configured_model = (getattr(Config, "LLM_MODEL", "") or "").strip()

        if configured_provider not in {"", "auto", "default"} and requested_provider == "killo":
            provider_name = configured_provider
            model_name = configured_model or AutoModelRouter.default_model_for_provider(
                configured_provider
            )
        elif requested_provider == "killo":
            provider_name, model_name = AutoModelRouter.get_best_model("agent")
        else:
            provider_name = requested_provider
            model_name = requested_model or configured_model or AutoModelRouter.default_model_for_provider(
                requested_provider
            )

        self.workspace_dir = (
            Path(workspace_dir) if workspace_dir else Path(Config.MEMORY_ROOT)
        )
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
        self.memory_manager = MemoryManager()
        self.profile_store = UserProfileStore(workspace_dir)
        self.workspace_graph = WorkspaceGraph(workspace_dir)
        self.task_inbox = TaskInboxStore(workspace_dir)
        self.task_ledger = TaskLedger(workspace_dir)
        self.hooks = HookDispatcher()
        self.workflow_engine = WorkflowEngine(workspace_dir)
        self.standing_orders = StandingOrderStore(workspace_dir)
        self.feedback_store = FeedbackStore(workspace_dir)

    def _provider_name(self) -> str:
        return (
            getattr(self.provider, "name", None)
            or getattr(self.provider, "provider_name", None)
            or self.provider.__class__.__name__.lower()
        )

    @staticmethod
    def _extract_provider_message(res: dict[str, Any]) -> tuple[str, list[dict[str, Any]] | None]:
        raw = res.get("raw") or {}
        raw_msg: dict[str, Any] = {}
        if isinstance(raw, dict):
            choices = raw.get("choices") or []
            if choices and isinstance(choices[0], dict):
                raw_msg = choices[0].get("message", {}) or {}

        content = raw_msg.get("content")
        if not content:
            content = res.get("content") or res.get("output") or ""
        tool_calls = raw_msg.get("tool_calls")

        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text") or item.get("content") or ""
                    if text:
                        parts.append(str(text))
                elif item:
                    parts.append(str(item))
            content = "\n".join(parts).strip()

        return str(content or ""), tool_calls

    def register_tool(self, tool: BaseTool):
        self.tools[tool.get_name()] = tool

    def _approval_tool_result(self, task_id: str) -> str:
        return json.dumps(
            {
                "error": (
                    "EXECUTION PAUSED: This action requires explicit user approval. "
                    f"Task ID: {task_id}. Please inform the user."
                )
            }
        )

    async def _queue_approval_request(
        self,
        *,
        function_name: str,
        args: dict[str, Any],
        request: IncomingRequest,
        session_id: str,
        tool_call_id: str,
        source_kind: str | None,
        messages: list[dict[str, Any]],
    ) -> bool:
        try:
            import uuid

            ledger = TaskLedger(str(self.workspace_dir))
            safe_args = {k: v for k, v in args.items() if k != "_request"}

            for task in ledger.list_tasks():
                if (
                    task.get("task_type") == "approval"
                    and task.get("status") == "approved"
                ):
                    meta = task.get("metadata", {})
                    if (
                        meta.get("tool_name") == function_name
                        and meta.get("args") == safe_args
                    ):
                        ledger.update_status(str(task.get("task_id", "")), "consumed")
                        return False

            task_id = f"app_{uuid.uuid4().hex[:8]}"
            ledger.add_task(
                task_id=task_id,
                task_type="approval",
                title=f"Execute {function_name}",
                user_id=request.user_id,
                platform=request.platform,
                chat_id=getattr(request.reply_target, "chat_id", ""),
                metadata={
                    "tool_name": function_name,
                    "args": safe_args,
                    "session_id": session_id,
                },
            )
            ledger.update_status(task_id, "pending_approval")
            result_str = self._approval_tool_result(task_id)
            tool_msg = {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": result_str,
            }
            messages.append(tool_msg)
            self.session_manager.append_message(session_id, tool_msg)

            if self.botsignal and getattr(self, "emit_status_messages", False):
                await self.botsignal.send_text(
                    request.reply_target,
                    f"⚠️ Action paused for safety approval: {function_name} (task {task_id})",
                    source_kind=source_kind,
                )
            return True
        except Exception as exc:
            logger.error("Failed to queue approval request: %s", exc)
            return False

    def _record_hook_event(
        self, event_name: str, request: IncomingRequest, title: str
    ) -> None:
        try:
            self.task_ledger.record_hook(
                hook_name=event_name,
                title=title,
                user_id=request.user_id,
                platform=request.platform,
                chat_id=request.reply_target.chat_id,
                metadata={"text": request.text[:240]},
            )
        except Exception as exc:
            logger.debug("Failed to record hook event %s: %s", event_name, exc)

    def _standing_orders_context(self) -> str:
        try:
            orders = self.standing_orders.parse()
            if not orders:
                return ""
            lines = ["--- [Standing Orders] ---"]
            for order in orders[:8]:
                lines.append(f"- {order.title}: {order.rule}")
            return "\n".join(lines) + "\n"
        except Exception as exc:
            logger.debug("Standing orders context failed: %s", exc)
            return ""

    def record_feedback(
        self,
        request: IncomingRequest,
        item_type: str,
        item_id: str,
        reward: float,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = self.feedback_store.add_feedback(
            user_id=request.user_id,
            item_type=item_type,
            item_id=item_id,
            reward=reward,
            reason=reason,
            metadata=metadata or {},
        )
        if item_type == "route":
            self.model_router.record_feedback(item_id, reward, reason=reason)
        return {
            "user_id": event.user_id,
            "item_type": event.item_type,
            "item_id": event.item_id,
            "reward": event.reward,
            "reason": event.reason,
        }

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
                self.task_inbox.add_item(
                    request.user_id,
                    title=request.text[:240],
                    kind="follow_up",
                    source="runtime",
                    platform=request.platform,
                    chat_id=request.reply_target.chat_id,
                    context={"reason": "follow_up"},
                )
                self.task_ledger.add_task(
                    task_id=f"followup_{request.user_id}_{len(self.task_ledger.list_tasks()) + 1}",
                    task_type="follow_up",
                    title=request.text[:240],
                    source="runtime",
                    user_id=request.user_id,
                    platform=request.platform,
                    chat_id=request.reply_target.chat_id,
                    metadata={"reason": "follow_up"},
                )
            except Exception as exc:
                logger.debug("Failed to schedule follow-up: %s", exc)

    def _learn_from_turn(
        self, request: IncomingRequest, content: str, session_id: str
    ) -> None:
        try:
            text = f"User: {request.text}\nAssistant: {content}"
            self.memory_manager.store_extraction(text, user_id=request.user_id)
            self.profile_store.append_turn(
                request.user_id,
                request_text=request.text,
                response_text=content,
            )
            if any(
                phrase in request.text.lower()
                for phrase in ("todo", "task", "follow up", "remind me", "please do")
            ):
                self.task_inbox.add_item(
                    request.user_id,
                    title=request.text[:240],
                    kind="task",
                    source="runtime",
                    platform=request.platform,
                    chat_id=request.reply_target.chat_id,
                    context={"response": content[:240]},
                )
                self.task_ledger.add_task(
                    task_id=f"task_{request.user_id}_{len(self.task_ledger.list_tasks()) + 1}",
                    task_type="task",
                    title=request.text[:240],
                    source="runtime",
                    user_id=request.user_id,
                    platform=request.platform,
                    chat_id=request.reply_target.chat_id,
                    metadata={"response": content[:240]},
                )
            # Keep the workspace graph current in the background; prompt access stays cheap.
            import asyncio

            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    loop.create_task(
                        self.workspace_graph.sync_user(
                            request.user_id, query=request.text
                        )
                    )
                    loop.create_task(
                        self.hooks.dispatch(
                            "turn_completed",
                            {
                                "user_id": request.user_id,
                                "platform": request.platform,
                                "session_id": session_id,
                                "text": request.text,
                            },
                        )
                    )
                else:
                    loop.run_until_complete(
                        self.workspace_graph.sync_user(
                            request.user_id, query=request.text
                        )
                    )
                    loop.run_until_complete(
                        self.hooks.dispatch(
                            "turn_completed",
                            {
                                "user_id": request.user_id,
                                "platform": request.platform,
                                "session_id": session_id,
                                "text": request.text,
                            },
                        )
                    )
            except RuntimeError:
                pass
        except Exception as exc:
            logger.debug("Memory extraction failed: %s", exc)

    def _build_evidence_lines(
        self,
        request: IncomingRequest,
        plan: Any,
        traces: list[ToolTrace],
        content: str,
    ) -> list[str]:
        evidence: list[str] = []
        try:
            profile = self.profile_store.load(request.user_id)
            if profile.display_name or profile.preferences:
                evidence.append(
                    f"profile:{profile.display_name or request.user_id} prefs={len(profile.preferences)} facts={len(profile.facts)}"
                )
        except Exception:
            pass

        try:
            graph = self.workspace_graph.build_for_user(
                request.user_id, query=request.text
            )
            if graph.get("nodes"):
                evidence.append(
                    f"graph:nodes={len(graph['nodes'])} edges={len(graph['edges'])}"
                )
        except Exception:
            pass

        for trace in traces[:4]:
            evidence.append(
                f"tool:{trace.tool_name}:{trace.action}:{'ok' if trace.success else 'error'}"
            )

        if plan and getattr(plan, "steps", None):
            evidence.append(f"plan:steps={len(plan.steps)}")

        if not evidence:
            evidence.append("source:assistant_inference")

        return evidence[:6]

    @staticmethod
    def _attach_evidence_footer(content: str, evidence: list[str]) -> str:
        if not evidence:
            return content
        footer = "\n\nEvidence:\n" + "\n".join(f"- {item}" for item in evidence)
        return f"{content.rstrip()}{footer}"

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
                prop: Dict[str, Any] = {
                    "type": param.type,
                    "description": param.description,
                }
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
            standing_orders = self._standing_orders_context()
            if standing_orders:
                system_content = system_content + "\n" + standing_orders

            persona = get_persona_engine()
            system_content = persona.generate_system_prompt(
                system_content, request.user_id
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
            content_array: List[Dict[str, Any]] = [
                {"type": "text", "text": request.text}
            ]
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
        max_turns = 15
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

                provider_name = self._provider_name()
                llm_calls_total.labels(
                    provider=provider_name, model=self.model_name
                ).inc()
                start_llm = __import__("time").perf_counter()

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
                llm_duration_seconds.labels(
                    provider=provider_name, model=self.model_name
                ).observe(__import__("time").perf_counter() - start_llm)

                if not res.get("success"):
                    # Try resilient fallback across all configured providers [CLI, API, Local, etc]
                    logger.warning("AGENT_RUNTIME  primary_provider_failed  session=%s provider=%s", session_id, provider_name)
                    try:
                        from app.core.model_router import AutoModelRouter  # noqa: PLC0415
                        from app.provider.factory import create_provider  # noqa: PLC0415
                        
                        fallbacks = AutoModelRouter.get_available_models("agent")
                        for f_prov_name, f_model_name in fallbacks:
                            if f_prov_name == provider_name and f_model_name == self.model_name:
                                continue # Skip the one that just failed
                            
                            try:
                                logger.info("AGENT_RUNTIME  trying_fallback  session=%s  fallback_provider=%s", session_id, f_prov_name)
                                f_prov = create_provider(f_prov_name)
                                f_res = await f_prov.chat_completion(model=f_model_name, messages=messages, **kwargs)
                                if f_res.get("success"):
                                    logger.info("AGENT_RUNTIME  fallback_success  session=%s  fallback_provider=%s", session_id, f_prov_name)
                                    res = f_res
                                    # Update current provider for remainder of session/turn
                                    self.provider = f_prov
                                    self.model_name = f_model_name
                                    break
                            except Exception as _f_exc:
                                logger.debug("Fallback %s failed: %s", f_prov_name, _f_exc)
                    except Exception as _routing_exc:
                        logger.debug("Fallback routing failed: %s", _routing_exc)

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

                content, tool_calls = self._extract_provider_message(res)

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
                    evidence = self._build_evidence_lines(
                        request, plan, traces, content
                    )
                    content = self._attach_evidence_footer(content, evidence)
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
                        evidence=evidence,
                    )
                    verification = self.verifier.verify(plan, content)
                    if not verification.get("success"):
                        logger.warning(
                            "AGENT_RUNTIME  verification_issue  session=%s  findings=%s",
                            session_id,
                            verification.get("findings"),
                        )
                        msg = {
                            "role": "system",
                            "content": f"[SYSTEM VERIFICATION FAILED] {verification.get('findings')}\nIf your code changes broke tests, use the 'rollback' operation in file_operations or 'git checkout' to restore the file and try again.",
                        }
                        messages.append(msg)
                        self.session_manager.append_message(session_id, msg)
                    self._learn_from_turn(request, content, session_id)
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
                                    approval_queued = await self._queue_approval_request(
                                        function_name=function_name,
                                        args=args,
                                        request=request,
                                        session_id=session_id,
                                        tool_call_id=tc.get("id", ""),
                                        source_kind=source_kind,
                                        messages=messages,
                                    )
                                    if approval_queued:
                                        continue
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

                            # --- SECURITY & APPROVAL CHECK ---
                            try:
                                needs_approval = self.policy_engine.requires_approval(
                                    function_name, args
                                )

                                if needs_approval:
                                    approval_queued = await self._queue_approval_request(
                                        function_name=function_name,
                                        args=args,
                                        request=request,
                                        session_id=session_id,
                                        tool_call_id=tc.get("id", ""),
                                        source_kind=source_kind,
                                        messages=messages,
                                    )
                                    if approval_queued:
                                        continue
                            except Exception as sec_e:
                                logger.error(
                                    f"Failed to check security requirements: {sec_e}"
                                )
                            # ---------------------------------

                            _tool_start = time.time()
                            result = await tool.execute(**args)
                            _tool_latency_ms = (time.time() - _tool_start) * 1000 if '_tool_start' in dir() else 0
                            tool_calls_total.labels(
                                tool_name=function_name, success="true"
                            ).inc()
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
                            # ── Self-improvement feedback ──────────────
                            try:
                                from app.core.self_improvement import get_feedback_tracker
                                get_feedback_tracker().record(
                                    interaction_id=session_id,
                                    tool_name=function_name,
                                    success=True,
                                    latency_ms=_tool_latency_ms,
                                )
                            except Exception:
                                pass
                        except Exception as e:
                            result_str = json.dumps({"error": str(e)})
                            tool_calls_total.labels(
                                tool_name=function_name, success="false"
                            ).inc()
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
                        tool_calls_total.labels(
                            tool_name=function_name, success="false"
                        ).inc()
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

                if not res.get("success"):
                    from app.core.model_router import AutoModelRouter  # noqa: PLC0415
                    from app.provider.factory import create_provider  # noqa: PLC0415
                    
                    for f_prov_name, f_model_name in AutoModelRouter.get_available_models("agent"):
                        try:
                            f_prov = create_provider(f_prov_name)
                            f_res = await f_prov.chat_completion(model=f_model_name, messages=messages)
                            if f_res.get("success"):
                                res = f_res
                                break
                        except Exception:
                            continue
                if res.get("success"):
                    content, _tool_calls = self._extract_provider_message(res)
                    if not content:
                        content = "I have completed the task."
                else:
                    content = "I wasn't able to fully answer — please try rephrasing your question."
            except Exception:
                content = "I wasn't able to fully answer — please try rephrasing your question."

            asst_msg = {"role": "assistant", "content": content}
            messages.append(asst_msg)
            self.session_manager.append_message(session_id, asst_msg)
            evidence = self._build_evidence_lines(request, plan, traces, content)
            content = self._attach_evidence_footer(content, evidence)
            await self.botsignal.send_text(
                request.reply_target,
                content,
                source_kind=source_kind,
                tool_traces=traces,
                evidence=evidence,
            )
            verification = self.verifier.verify(plan, content)
            if not verification.get("success"):
                logger.warning(
                    "AGENT_RUNTIME  verification_issue  session=%s  findings=%s",
                    session_id,
                    verification.get("findings"),
                )
                msg = {
                    "role": "system",
                    "content": f"[SYSTEM VERIFICATION FAILED] {verification.get('findings')}\nIf your code changes broke tests, use the 'rollback' operation in file_operations or 'git checkout' to restore the file and try again.",
                }
                messages.append(msg)
                self.session_manager.append_message(session_id, msg)
            self._learn_from_turn(request, content, session_id)
            self._maybe_schedule_follow_up(request, content)

        self.session_manager.summarize_session(session_id)
        self.session_manager.prune_session(session_id)
