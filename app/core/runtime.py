import json
import logging
import os
import time as _time_module
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
from app.core.security import get_security_guard


# ---------------------------------------------------------------------------
# v2 feature-flag helpers
# ---------------------------------------------------------------------------


def _env_flag(name: str) -> bool:
    val = __import__("os").environ.get(name, "").strip().lower()
    return val in {"1", "true", "yes", "on"}


def _env_float(name: str) -> float | None:
    val = __import__("os").environ.get(name, "").strip()
    if not val:
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _wrap_ledger_with_budget(per_user_per_day_usd: float | None) -> Any:
    """Construct a BudgetLedger with a daily cap, or a default if none."""
    from app.core.cost_router import BudgetConfig, BudgetLedger

    cfg = BudgetConfig(per_user_per_day_usd=per_user_per_day_usd)
    return BudgetLedger(cfg)


def _build_v2_request(*, text: str, user_id: str | None, plan_id: str | None) -> Any:
    """Build a v2 :class:`RouteRequest` from a runtime text request."""
    from app.core.cost_router import RouteRequest, TaskType

    kind = _classify_text_for_task(text)
    return RouteRequest(
        task=kind,
        input_tokens=max(1, len(text) // 4),
        max_output_tokens=1024,
        user_id=user_id,
        plan_id=plan_id,
    )


def _classify_text_for_task(text: str) -> Any:
    """Cheap keyword classifier used to seed the v2 router's task hint."""
    from app.core.cost_router import TaskType

    t = (text or "").lower()
    if any(w in t for w in ("code", "function", "implement", "refactor", "debug", "compile")):
        return TaskType.CODE
    if any(w in t for w in ("research", "investigate", "compare", "analyze", "study")):
        return TaskType.RESEARCH
    if any(w in t for w in ("summarize", "summary", "tldr", "recap")):
        return TaskType.SUMMARIZE
    if any(w in t for w in ("classify", "categorize", "label", "tag")):
        return TaskType.CLASSIFY
    if any(w in t for w in ("extract", "find all", "list the")):
        return TaskType.EXTRACT
    if any(w in t for w in ("reason", "why", "deduce", "prove")):
        return TaskType.REASONING
    return TaskType.CHAT


from app.core.session import SessionManager
from app.core.metacognition import (
    MetaCognitiveMonitor,
    ReasoningStrategy,
    get_metacognitive_monitor,
)
from app.core.learner import LearnerAgent, get_learner_agent
from app.provider.factory import create_provider
from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


def _build_secret_vault() -> Any:
    """Construct a :class:`SecretVault` (A4).

    Module-level so the runtime can be tested without instantiating
    the full ``AgentRuntime`` (which loads LLM providers and
    embedding models).  Returns ``None`` if the vault cannot be
    constructed.
    """
    try:
        from app.core.vault import SecretVault

        return SecretVault()
    except Exception as e:  # noqa: BLE001
        logger.debug("secret vault unavailable: %s", e)
        return None


def _build_audit_log_v2() -> Any:
    """Construct a v2 :class:`AuditLog` (A4).

    The path is read from ``SARAS_AUDIT_PATH`` (default
    ``workspace/audit.jsonl``).  Returns ``None`` on failure.
    """
    try:
        from app.core.audit import AuditLog
        from app.core.audit.log import DEFAULT_PATH

        log_path = Path(os.environ.get("SARAS_AUDIT_PATH", str(DEFAULT_PATH)))
        return AuditLog(jsonl_path=log_path)
    except Exception as e:  # noqa: BLE001
        logger.debug("audit log v2 unavailable: %s", e)
        return None


def _build_policy_v2(
    audit_log: Any | None = None, state_dir: str | os.PathLike[str] | None = None
) -> Any:
    """Construct a v2 :class:`PolicyEngine` (A4).

    Reads ``SARAS_POLICY_STATE_DIR`` for the trust + approval
    stores (default ``workspace/state``).  Pass ``audit_log`` to
    wire the policy engine into the same audit log used by the
    runtime.
    """
    try:
        from app.core.policy_v2 import ApprovalStore, PolicyEngine, TrustStore

        if state_dir is None:
            state_dir = Path(os.environ.get("SARAS_POLICY_STATE_DIR", "workspace/state"))
        else:
            state_dir = Path(state_dir)
        return PolicyEngine(
            trust_store=TrustStore(state_dir / "trust.jsonl"),
            approval_store=ApprovalStore(state_dir / "approvals.jsonl"),
            audit_log=audit_log,
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("policy v2 unavailable: %s", e)
        return None


def _build_conversation_manager() -> Any:
    """Build the per-session conversation manager (Phase D).

    Imports are lazy so the dependency is optional for
    callers that only use the legacy path.
    """
    try:
        from app.core.conversation import ConversationManager

        return ConversationManager()
    except Exception as e:  # noqa: BLE001
        logger.debug("conversation manager unavailable: %s", e)
        return None


def _build_privacy_manager() -> Any:
    """Build the process-singleton :class:`PrivacyManager` (Phase E).

    Returns ``None`` when the package can't be imported so
    the runtime can run without privacy in test environments
    that don't have the package on the path.
    """
    try:
        from app.core.privacy import PrivacyManager, get_privacy_manager

        # Touch the singleton so the manager exists.
        return get_privacy_manager() or PrivacyManager()
    except Exception as e:  # noqa: BLE001
        logger.debug("privacy manager unavailable: %s", e)
        return None


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
            model_name = (
                requested_model
                or configured_model
                or AutoModelRouter.default_model_for_provider(requested_provider)
            )

        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path(Config.MEMORY_ROOT)
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
        # v2 engines (A2 cost router + A3 verifier).  Opt-in via env
        # vars so the legacy path stays the default.
        self.cost_router = self._build_cost_router()
        self.verifier_v2 = self._build_verifier_v2()
        self._use_cost_router_v2 = _env_flag("SARAS_COST_ROUTER_V2")
        self._use_verifier_v2 = _env_flag("SARAS_VERIFIER_V2")
        # A4: vault, audit, policy v2
        self.secret_vault = self._build_secret_vault()
        self.audit_log_v2 = self._build_audit_log_v2()
        self.policy_engine_v2 = self._build_policy_v2()
        self._use_vault_v2 = _env_flag("SARAS_VAULT_ENABLED")
        self._use_audit_v2 = _env_flag("SARAS_AUDIT_V2")
        self._use_policy_v2 = _env_flag("SARAS_POLICY_V2")
        # Phase D: working memory + compression + reference resolution
        # per session.  Opt-in via env var.
        self._use_conversation_v2 = _env_flag("SARAS_CONVERSATION_V2")
        self.conversation_manager = self._build_conversation_manager()
        # Phase E: privacy manager — consent-gated tool calls, log
        # redaction, retention scheduling.  Opt-in via env var.
        self._use_privacy_v2 = _env_flag("SARAS_PRIVACY_V2")
        self.privacy_manager = self._build_privacy_manager()
        self.security_guard = get_security_guard()
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

        # Meta-cognitive monitoring and cross-training
        self.metacognition = get_metacognitive_monitor()
        self.learner = get_learner_agent()
        self._agent_name = "AssistantAgent"  # Default, can be overridden
        self._current_strategy = ReasoningStrategy.ANALYTICAL

    def _provider_name(self) -> str:
        return (
            getattr(self.provider, "name", None)
            or getattr(self.provider, "provider_name", None)
            or self.provider.__class__.__name__.lower()
        )

    def _build_cost_router(self) -> Any:
        """Construct a v2 CostRouter.  Imports are lazy so the dep is
        optional for callers that only use the legacy path."""
        try:
            from app.core.cost_router import CostRouter

            return CostRouter(ledger=_wrap_ledger_with_budget(_env_float("SARAS_DAILY_BUDGET_USD")))
        except Exception as e:  # noqa: BLE001
            logger.debug("cost router unavailable: %s", e)
            return None

    def _build_verifier_v2(self) -> Any:
        try:
            from app.core.verifier import Verifier

            return Verifier()
        except Exception as e:  # noqa: BLE001
            logger.debug("verifier v2 unavailable: %s", e)
            return None

    def _build_secret_vault(self) -> Any:
        # Delegates to the module-level helper so tests can construct
        # the vault without instantiating the full runtime.
        return _build_secret_vault()

    def _build_audit_log_v2(self) -> Any:
        return _build_audit_log_v2()

    def _build_policy_v2(self) -> Any:
        return _build_policy_v2(audit_log=self.audit_log_v2)

    def _build_conversation_manager(self) -> Any:
        return _build_conversation_manager()

    def _build_privacy_manager(self) -> Any:
        return _build_privacy_manager()

    # ------------------------------------------------------------------
    # A4 audit + policy helpers
    # ------------------------------------------------------------------

    def _audit(
        self,
        *,
        kind: str,
        actor: str,
        action: str,
        target: str | None = None,
        success: bool = True,
        detail: str | None = None,
        context: dict[str, Any] | None = None,
        risk_level: str = "low",
    ) -> None:
        """Append an audit event.  No-op when A4 audit is disabled."""
        if not self._use_audit_v2 or self.audit_log_v2 is None:
            return
        try:
            from app.core.audit import AuditEvent, AuditKind, RiskLevel

            self.audit_log_v2.record(
                AuditEvent(
                    kind=AuditKind(kind),
                    actor=actor,
                    action=action,
                    target=target,
                    context=context or {},
                    success=success,
                    detail=detail,
                    risk_level=RiskLevel(risk_level),
                )
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("audit v2 record failed: %s", e)

    # ------------------------------------------------------------------
    # E Privacy & Trust helper
    # ------------------------------------------------------------------

    def _privacy_check_tool(self, function_name: str, user_id: str) -> tuple[bool, str, str | None]:
        """Run a privacy/consent check on a tool call (Phase E).

        Returns ``(allowed, reason, data_class_value)``:

        - ``allowed=True`` — proceed.
        - ``allowed=False`` — denied; ``reason`` is human-readable.

        When the privacy v2 flag is off, returns
        ``(True, "", None)`` so the legacy path is unaffected.
        """
        if not self._use_privacy_v2 or self.privacy_manager is None:
            return True, "", None
        try:
            dc = self.privacy_manager.check_tool(user_id, function_name)
            return True, "", dc.value
        except Exception as e:  # noqa: BLE001
            # PrivacyError + any other error → deny.
            from app.core.privacy import PrivacyError

            if isinstance(e, PrivacyError):
                self._audit(
                    kind="privacy",
                    actor=user_id,
                    action=function_name,
                    success=False,
                    detail=str(e),
                    context={
                        "gate": "v2",
                        "data_class": e.data_class.value,
                        "current_level": (e.current_level.value if e.current_level else None),
                    },
                    risk_level="high",
                )
                return False, f"privacy: {e}", e.data_class.value
            logger.debug("privacy check failed: %s", e)
            # Unknown error → fail open (legacy gates still run).
            return True, "", None

    def _policy_v2_check(
        self, function_name: str, args: dict[str, Any], user_id: str
    ) -> tuple[bool, str, str | None]:
        """Run a v2 policy check on a tool call.

        Returns ``(allowed, reason, approval_id)``:

        - ``allowed=True`` — proceed.
        - ``allowed=False, approval_id=...`` — enqueued for approval.
        - ``allowed=False, approval_id=None`` — denied.

        When A4 policy v2 is disabled, returns ``(True, "", None)``
        so the legacy gate remains the only authority.
        """
        if not self._use_policy_v2 or self.policy_engine_v2 is None:
            return True, "", None
        try:
            from app.core.policy_v2 import PolicyRequest, Verdict

            decision = self.policy_engine_v2.evaluate(
                PolicyRequest(
                    user_id=user_id,
                    action=function_name,
                    target=args.get("path") or args.get("command"),
                    args={
                        k: v
                        for k, v in args.items()
                        if k != "_request" and isinstance(v, (str, int, float, bool))
                    },
                )
            )
            if decision.verdict == Verdict.ALLOW:
                return True, "", None
            if decision.verdict == Verdict.ASK:
                return False, "policy v2: requires approval", decision.approval_id
            return False, f"policy v2 denied: {'; '.join(decision.reasons)}", None
        except Exception as e:  # noqa: BLE001
            # Fail open: legacy path still runs after this.
            logger.debug("policy v2 check failed: %s", e)
            return True, "", None

    def _resolve_credential(
        self, name: str, env_var: str, default: str | None = None
    ) -> str | None:
        """Look up a credential, preferring the vault over env vars.

        When A4 vault is disabled, this is equivalent to
        ``os.environ.get(env_var, default)``.
        """
        if self._use_vault_v2 and self.secret_vault is not None:
            try:
                from app.core.vault import resolve_secret

                v = resolve_secret(name, vault=self.secret_vault, env_var=env_var)
                if v:
                    return v
            except Exception as e:  # noqa: BLE001
                logger.debug("vault credential lookup failed for %s: %s", name, e)
        return os.environ.get(env_var, default)

    async def _route_request(self, request: Any) -> Any:
        """Pick a model for the current request.

        When ``SARAS_COST_ROUTER_V2`` is set and the v2 router is
        available, we use the budget-aware :class:`CostRouter`.  The
        returned :class:`RouteDecision` is converted to the legacy
        :class:`RouteDecision` shape so the rest of the runtime doesn't
        need to change.
        """
        if self._use_cost_router_v2 and self.cost_router is not None:
            try:
                from app.core.cost_router import TaskType

                decision = await self.cost_router.route(
                    _build_v2_request(
                        text=request.text,
                        user_id=request.user_id,
                        plan_id=getattr(request, "request_id", None),
                    )
                )
                # Lazy-import the legacy type to avoid a hard dep cycle.
                from app.core.model_router import RouteDecision

                provider = create_provider(decision.provider)
                return RouteDecision(
                    provider=provider,
                    model_name=decision.model,
                    route_kind=decision.tier.value,
                    rationale=decision.rationale,
                )
            except Exception as e:  # noqa: BLE001
                logger.debug("cost router v2 failed, falling back: %s", e)
        return await self.model_router.resolve(request.text)

    async def _verify_step(self, plan: Any, step: Any, content: str) -> dict[str, Any]:
        """Verify a step's output.

        When ``SARAS_VERIFIER_V2`` is set, the structured v2 verifier
        produces a :class:`VerificationReport`; the legacy path stays
        unchanged.
        """
        if self._use_verifier_v2 and self.verifier_v2 is not None:
            try:
                from app.core.verifier import StepContext

                ctx = StepContext(
                    plan_id=getattr(plan, "goal", ""),
                    step_id=str(getattr(step, "step", "")),
                    action="llm",
                    tool_name=None,
                    prompt=None,
                    output=content,
                    metadata={"success_criteria": getattr(step, "success_criteria", "")},
                )
                report = await self.verifier_v2.verify(ctx)
                return report.to_dict()
            except Exception as e:  # noqa: BLE001
                logger.debug("verifier v2 failed, falling back: %s", e)
        return self.verifier.verify(plan, content)

    @staticmethod
    def _extract_provider_message(
        res: dict[str, Any],
    ) -> tuple[str, list[dict[str, Any]] | None]:
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

    def deregister_tool(self, name: str) -> bool:
        """Remove a registered tool from the runtime tool layer by name.

        Idempotent: removing an absent tool is a no-op. Returns ``True`` if a
        tool was removed, ``False`` otherwise. Used by the Module_Platform to
        reverse a hot-load during rollback (A2, Req 10.7).
        """
        return self.tools.pop(name, None) is not None

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
                if task.get("task_type") == "approval" and task.get("status") == "approved":
                    meta = task.get("metadata", {})
                    if meta.get("tool_name") == function_name and meta.get("args") == safe_args:
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

    def _record_hook_event(self, event_name: str, request: IncomingRequest, title: str) -> None:
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
        if any(phrase in lower for phrase in ("follow up", "get back to you", "remind me")):
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

    def _classify_task(self, text: str) -> str:
        """Classify a user query into a task category for meta-cognitive tracking."""
        text_lower = text.lower()

        # Code-related tasks
        if any(
            phrase in text_lower
            for phrase in (
                "code",
                "function",
                "class",
                "debug",
                "fix",
                "implement",
                "refactor",
                "test",
                "python",
                "javascript",
                "bug",
                "error",
                "compile",
                "syntax",
                "variable",
                "loop",
                "array",
                "dict",
            )
        ):
            return "coding"

        # Research tasks
        if any(
            phrase in text_lower
            for phrase in (
                "research",
                "find",
                "search",
                "look up",
                "what is",
                "who is",
                "explain",
                "tell me about",
                "history of",
                "compare",
            )
        ):
            return "research"

        # Analysis tasks
        if any(
            phrase in text_lower
            for phrase in (
                "analyze",
                "analysis",
                "review",
                "evaluate",
                "assess",
                "pros and cons",
                "advantages",
                "disadvantages",
            )
        ):
            return "analysis"

        # Creative tasks
        if any(
            phrase in text_lower
            for phrase in (
                "write",
                "create",
                "generate",
                "compose",
                "draft",
                "story",
                "poem",
                "essay",
                "article",
                "blog",
            )
        ):
            return "creative"

        # Planning tasks
        if any(
            phrase in text_lower
            for phrase in (
                "plan",
                "strategy",
                "roadmap",
                "schedule",
                "organize",
                "todo",
                "task",
                "project",
                "steps to",
            )
        ):
            return "planning"

        # System/DevOps tasks
        if any(
            phrase in text_lower
            for phrase in (
                "deploy",
                "server",
                "docker",
                "kubernetes",
                "install",
                "configure",
                "setup",
                "monitor",
                "log",
                "system",
            )
        ):
            return "devops"

        # Math/calculation tasks
        if any(
            phrase in text_lower
            for phrase in (
                "calculate",
                "math",
                "equation",
                "formula",
                "compute",
                "sum",
                "average",
                "percentage",
                "convert",
            )
        ):
            return "math"

        # Communication tasks
        if any(
            phrase in text_lower
            for phrase in (
                "email",
                "message",
                "reply",
                "respond",
                "draft email",
                "write to",
                "send",
                "communicate",
            )
        ):
            return "communication"

        # Finance tasks
        if any(
            phrase in text_lower
            for phrase in (
                "stock",
                "crypto",
                "finance",
                "money",
                "budget",
                "invest",
                "portfolio",
                "price",
                "market",
            )
        ):
            return "finance"

        # Security tasks
        if any(
            phrase in text_lower
            for phrase in (
                "security",
                "vulnerability",
                "scan",
                "audit",
                "hack",
                "exploit",
                "patch",
                "firewall",
                "encrypt",
            )
        ):
            return "security"

        return "general"

    def _learn_from_turn(self, request: IncomingRequest, content: str, session_id: str) -> None:
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
                        self.workspace_graph.sync_user(request.user_id, query=request.text)
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
                        self.workspace_graph.sync_user(request.user_id, query=request.text)
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
            graph = self.workspace_graph.build_for_user(request.user_id, query=request.text)
            if graph.get("nodes"):
                evidence.append(f"graph:nodes={len(graph['nodes'])} edges={len(graph['edges'])}")
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
    ) -> dict[str, Any]:
        """Execute a full ReAct loop turn.

        Returns a dict with execution summary:
            - tool_calls: list of tool execution dicts
            - success: whether the turn completed successfully
            - response: the final response text (if available)
            - latency_ms: total execution time
        """
        import time as _time_module

        _turn_start = _time_module.time()
        _tool_call_records: list[dict[str, Any]] = []
        _final_response: str = ""
        _turn_success: bool = True

        # A5 observability: bind request context so every log line
        # carries user_id / session_id / platform for the duration
        # of the turn.  Cleared at the end of the turn.
        def _noop_bind(**_kw):  # type: ignore[no-untyped-def]
            return None

        def _noop_clear():  # type: ignore[no-untyped-def]
            return None

        try:
            from app.observability import bind_context as _obs_bind
            from app.observability import clear_context as _obs_clear
        except ImportError:  # pragma: no cover - observability is core
            _obs_bind = _noop_bind
            _obs_clear = _noop_clear

        _obs_bind(
            platform=request.platform,
            user_id=request.user_id,
        )

        session_id = self.get_session_id(request)
        _obs_bind(session_id=session_id)
        source_kind = "command" if request.text.lstrip().startswith("/") else "prompt"

        # Meta-cognitive strategy selection
        task_category = self._classify_task(request.text)
        self._current_strategy = self.metacognition.select_strategy(request.text, task_category)
        logger.debug(
            "Meta-cognition: selected strategy '%s' for category '%s'",
            self._current_strategy,
            task_category,
        )

        plan = self.planner.plan(request.text)
        route_decision = await self._route_request(request)
        route_kind = route_decision.route_kind
        self.provider = route_decision.provider
        self.model_name = route_decision.model_name

        messages = self.session_manager.load_session(session_id)

        # Phase D: prepend a "memory" block to the system
        # prompt when the conversation manager is enabled.
        # This is what gives the LLM a long-memory across
        # turns: facts the user has stated, the current
        # topic, and a rolling summary of older turns.
        conversation_memory_block = ""
        if self._use_conversation_v2 and self.conversation_manager is not None:
            try:
                conversation_memory_block = self.conversation_manager.context_for_prompt(session_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("conversation context_for_prompt failed: %s", exc)

        if not messages:
            system_content = self.bootstrapper.build_system_prompt(
                query=request.text,
                user_id=request.user_id,
            )
            standing_orders = self._standing_orders_context()
            if standing_orders:
                system_content = system_content + "\n" + standing_orders

            persona = get_persona_engine()
            system_content = persona.generate_system_prompt(system_content, request.user_id)

            if conversation_memory_block:
                system_content = system_content + "\n\n" + conversation_memory_block

            system_prompt = {"role": "system", "content": system_content}
            messages.append(system_prompt)
            self.session_manager.append_message(session_id, system_prompt)
        elif conversation_memory_block:
            # Session already has a system prompt — append the
            # memory block as a follow-up system message so we
            # don't mutate the persisted prompt in place.
            messages.append({"role": "system", "content": conversation_memory_block})

        if plan.steps:
            plan_message = {
                "role": "system",
                "content": "Planner: "
                + " | ".join(
                    f"{step.step}:{step.action}:{step.description}" for step in plan.steps
                ),
            }
            messages.append(plan_message)
            self.session_manager.append_message(session_id, plan_message)

        # Build user message (handle True Native Multimodality)
        if request.image_urls:
            content_array: List[Dict[str, Any]] = [{"type": "text", "text": request.text}]
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

        # Phase D: ingest the user turn into the conversation
        # manager (extracted facts, entities, current topic).
        # This is best-effort: when the manager is disabled or
        # unavailable we silently skip — the legacy message
        # flow still works.
        if self._use_conversation_v2 and self.conversation_manager is not None:
            try:
                self.conversation_manager.ingest_turn(
                    session_id,
                    "user",
                    request.text,
                    user_id=request.user_id or "",
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("conversation ingest (user) failed: %s", exc)

        messages.append(user_msg)
        self.session_manager.append_message(session_id, user_msg)

        openai_tools = self._build_openai_tools()
        max_turns = 15
        turn_count = 0
        # ── Loop guardrails ────────────────────────────────────────────
        MAX_SAME_TOOL_STREAK = 3  # force synthesis after N consecutive identical tool calls
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
                llm_calls_total.labels(provider=provider_name, model=self.model_name).inc()
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
                llm_duration_seconds.labels(provider=provider_name, model=self.model_name).observe(
                    __import__("time").perf_counter() - start_llm
                )

                if not res.get("success"):
                    # Try resilient fallback across all configured providers [CLI, API, Local, etc]
                    logger.warning(
                        "AGENT_RUNTIME  primary_provider_failed  session=%s provider=%s",
                        session_id,
                        provider_name,
                    )
                    try:
                        from app.core.model_router import AutoModelRouter  # noqa: PLC0415
                        from app.provider.factory import create_provider  # noqa: PLC0415

                        fallbacks = AutoModelRouter.get_available_models("agent")
                        for f_prov_name, f_model_name in fallbacks:
                            if f_prov_name == provider_name and f_model_name == self.model_name:
                                continue  # Skip the one that just failed

                            try:
                                logger.info(
                                    "AGENT_RUNTIME  trying_fallback  session=%s  fallback_provider=%s",
                                    session_id,
                                    f_prov_name,
                                )
                                f_prov = create_provider(f_prov_name)
                                f_res = await f_prov.chat_completion(
                                    model=f_model_name, messages=messages, **kwargs
                                )
                                if f_res.get("success"):
                                    logger.info(
                                        "AGENT_RUNTIME  fallback_success  session=%s  fallback_provider=%s",
                                        session_id,
                                        f_prov_name,
                                    )
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
                    evidence = self._build_evidence_lines(request, plan, traces, content)
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
                    # Phase D: ingest the assistant's final turn
                    # into the conversation manager.  Only the
                    # final response is captured — intermediate
                    # tool-call messages are noisy.
                    if self._use_conversation_v2 and self.conversation_manager is not None:
                        try:
                            self.conversation_manager.ingest_turn(
                                session_id,
                                "assistant",
                                content,
                                user_id=request.user_id or "",
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.debug(
                                "conversation ingest (assistant) failed: %s",
                                exc,
                            )
                    break

                # Execute tools
                tool_names = [tc.get("function", {}).get("name", "unknown") for tc in tool_calls]
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
                            # ── A4 audit: tool attempt ────────────────────
                            self._audit(
                                kind="tool_call",
                                actor=request.user_id,
                                action=function_name,
                                target=str(args.get("path") or args.get("command") or ""),
                                success=True,
                                detail="attempt",
                                context={
                                    "session_id": session_id,
                                    "platform": request.platform,
                                    "tool_call_id": tc.get("id", ""),
                                },
                                risk_level="low",
                            )
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
                                self._audit(
                                    kind="policy",
                                    actor=request.user_id,
                                    action=function_name,
                                    success=False,
                                    detail=f"deny (legacy): {decision.reason}",
                                    context={"gate": "legacy", "verdict": "deny"},
                                    risk_level="high",
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
                                logger.error(f"Failed to check security requirements: {sec_e}")
                            # ---------------------------------

                            # ── E privacy check (if enabled) ────────────
                            privacy_ok, privacy_reason, _dc_value = self._privacy_check_tool(
                                function_name, request.user_id
                            )
                            if not privacy_ok:
                                traces.append(
                                    ToolTrace(
                                        tool_name=function_name,
                                        action="privacy_deny",
                                        success=False,
                                        detail=privacy_reason,
                                    )
                                )
                                await self.botsignal.send_text(
                                    request.reply_target,
                                    f"Action blocked: {privacy_reason}",
                                    source_kind=source_kind,
                                    tool_traces=traces,
                                )
                                break
                            # ── end E privacy check ─────────────────────

                            # ── A4 policy v2 check (if enabled) ─────────
                            allowed_v2, reason_v2, approval_id_v2 = self._policy_v2_check(
                                function_name, args, request.user_id
                            )
                            if not allowed_v2 and approval_id_v2 is not None:
                                # ASK: enqueue using legacy queue (which
                                # also tracks a v2 approval id in metadata)
                                self._audit(
                                    kind="approval",
                                    actor=request.user_id,
                                    action=function_name,
                                    success=False,
                                    detail=reason_v2,
                                    context={
                                        "gate": "v2",
                                        "verdict": "ask",
                                        "approval_id": approval_id_v2,
                                    },
                                    risk_level="high",
                                )
                                approval_queued = await self._queue_approval_request(
                                    function_name=function_name,
                                    args={**args, "_v2_approval_id": approval_id_v2},
                                    request=request,
                                    session_id=session_id,
                                    tool_call_id=tc.get("id", ""),
                                    source_kind=source_kind,
                                    messages=messages,
                                )
                                if approval_queued:
                                    continue
                            elif not allowed_v2:
                                # DENY: block, no approval path
                                self._audit(
                                    kind="policy",
                                    actor=request.user_id,
                                    action=function_name,
                                    success=False,
                                    detail=f"deny (v2): {reason_v2}",
                                    context={"gate": "v2", "verdict": "deny"},
                                    risk_level="critical",
                                )
                                traces.append(
                                    ToolTrace(
                                        tool_name=function_name,
                                        action="policy_v2_deny",
                                        success=False,
                                        detail=reason_v2,
                                    )
                                )
                                await self.botsignal.send_text(
                                    request.reply_target,
                                    f"Action blocked: {reason_v2}",
                                    source_kind=source_kind,
                                    tool_traces=traces,
                                )
                                break
                            # ── end A4 policy v2 check ────────────────

                            _tool_start = time.time()
                            # A5 observability: wrap the tool call
                            # in a span so traces show the latency
                            # and any error.
                            _obs_span_obj: Any = None
                            _obs_span_cm: Any = None
                            try:
                                from app.observability.tracing import (
                                    get_tracer as _obs_get_tracer,
                                )

                                _obs_span_cm = _obs_get_tracer(
                                    "saras.runtime"
                                ).start_as_current_span(
                                    f"tool.{function_name}",
                                    attributes={"tool": function_name},
                                )
                                _obs_span_obj = _obs_span_cm.__enter__()
                            except Exception:  # noqa: BLE001
                                _obs_span_obj = None
                                _obs_span_cm = None
                            try:
                                result = await tool.execute(**args)
                            finally:
                                if _obs_span_cm is not None:
                                    try:
                                        _obs_span_cm.__exit__(None, None, None)
                                    except Exception:  # noqa: BLE001
                                        pass
                            _tool_latency_ms = (
                                (time.time() - _tool_start) * 1000 if "_tool_start" in dir() else 0
                            )
                            tool_calls_total.labels(tool_name=function_name, success="true").inc()
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
                            _tool_call_records.append(
                                {
                                    "tool": function_name,
                                    "action": "execute",
                                    "args": args,
                                    "success": True,
                                    "latency_ms": _tool_latency_ms,
                                }
                            )
                            # ── Self-improvement feedback ──────────────
                            try:
                                from app.core.self_improvement import (
                                    get_feedback_tracker,
                                )

                                get_feedback_tracker().record(
                                    interaction_id=session_id,
                                    tool_name=function_name,
                                    success=True,
                                    latency_ms=_tool_latency_ms,
                                )
                            except Exception:
                                pass
                        except Exception as e:
                            # A5 observability: record the exception
                            # on the span (if it was opened).
                            if _obs_span_obj is not None and hasattr(
                                _obs_span_obj, "record_exception"
                            ):
                                try:
                                    _obs_span_obj.record_exception(e)
                                except Exception:  # noqa: BLE001
                                    pass
                            if _obs_span_cm is not None:
                                try:
                                    _obs_span_cm.__exit__(type(e), e, e.__traceback__)
                                except Exception:  # noqa: BLE001
                                    pass
                            result_str = json.dumps({"error": str(e)})
                            tool_calls_total.labels(tool_name=function_name, success="false").inc()
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
                        result_str = json.dumps({"error": f"Tool {function_name} not found"})
                        tool_calls_total.labels(tool_name=function_name, success="false").inc()
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

                    for (
                        f_prov_name,
                        f_model_name,
                    ) in AutoModelRouter.get_available_models("agent"):
                        try:
                            f_prov = create_provider(f_prov_name)
                            f_res = await f_prov.chat_completion(
                                model=f_model_name, messages=messages
                            )
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
            _final_response = content

        self.session_manager.summarize_session(session_id)
        self.session_manager.prune_session(session_id)

        _turn_latency_ms = (_time_module.time() - _turn_start) * 1000

        # Meta-cognitive performance recording
        tools_used = [tc.get("tool", "") for tc in _tool_call_records if tc.get("success")]
        self.metacognition.record(
            query=request.text,
            category=task_category,
            strategy=self._current_strategy,
            tools_used=tools_used,
            success=_turn_success,
            confidence=self.metacognition.get_confidence(),
            duration_ms=_turn_latency_ms,
        )

        # Learner agent performance recording
        self.learner.record(
            agent_name=self._agent_name,
            task_category=task_category,
            success=_turn_success,
            duration_ms=_turn_latency_ms,
            tools_used=tools_used,
        )

        # A5 observability: clear bound context now that the turn
        # is finished.
        try:
            _obs_clear()
        except NameError:  # pragma: no cover
            pass

        return {
            "tool_calls": _tool_call_records,
            "success": _turn_success,
            "response": _final_response,
            "latency_ms": _turn_latency_ms,
            "session_id": session_id,
            "turns": turn_count,
        }
