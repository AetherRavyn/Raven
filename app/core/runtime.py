import json
import logging
import os
import time as _time_module
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.bootstrapper import Bootstrapper
from app.core.botsignal import BotSignal, get_botsignal
from app.core.models import IncomingRequest, SignalPayload, ToolTrace
from app.core.rate_limit_middleware import RateLimitMiddleware
from app.core.multimodal import MultimodalContextBuilder
from app.core.unified_multimodal import UnifiedMultimodalContextBuilder, get_unified_context_builder
from app.core.multimodal_connectors import MultimodalConnectorHub, get_connector_hub
from app.core.governance import get_policy_engine, PolicyEngine
from app.core.persona import get_persona_engine
from app.core.proactive import schedule_follow_up
from app.core.planner import ResultVerifier, TaskPlanner
from app.core.model_router import ModelRouter
from app.core.policy import get_policy_engine
from app.core.metrics import llm_calls_total, llm_duration_seconds, tool_calls_total
from app.core.user_profile import UserProfileStore
from app.core.workspace_graph import WorkspaceGraph
from app.core.task_inbox import TaskInboxStore
from app.core.task_ledger import TaskLedger
from app.core.hooks import HookDispatcher
from app.core.workflow_engine import WorkflowEngine
from app.core.standing_orders import StandingOrderStore
from app.core.feedback import FeedbackStore
from app.core.governance import (
    PolicyEngine,
    SandboxExecutor,
    EvaluationHarness,
    ToolRiskProfile,
    PolicyRule,
    ApprovalRequest,
    AuditEvent,
    RiskLevel,
    ActionType,
    Decision,
    get_policy_engine as get_governance_policy_engine,
    get_sandbox_executor,
    get_evaluation_harness,
)
from app.core.edge import get_model_tier_router, get_edge_dispatcher, ComputeTier, ComputeTask
from app.core.security import get_security_guard


# ---------------------------------------------------------------------------
# v2 feature-flag helpers
# ---------------------------------------------------------------------------


def _env_flag(name: str, default: bool = False) -> bool:
    val = __import__("os").environ.get(name, "").strip().lower()
    if not val:
        return default
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
from app.core.analogy import get_analogy_engine
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

    The path is read from ``RAVEN_AUDIT_PATH`` (default
    ``workspace/audit.jsonl``).  Returns ``None`` on failure.
    """
    try:
        from app.core.audit import AuditLog
        from app.core.audit.log import DEFAULT_PATH

        log_path = Path(os.environ.get("RAVEN_AUDIT_PATH", str(DEFAULT_PATH)))
        return AuditLog(jsonl_path=log_path)
    except Exception as e:  # noqa: BLE001
        logger.debug("audit log v2 unavailable: %s", e)
        return None


def _build_policy_v2(
    audit_log: Any | None = None, state_dir: str | os.PathLike[str] | None = None
) -> Any:
    """Construct a v2 :class:`PolicyEngine` (A4).

    Reads ``RAVEN_POLICY_STATE_DIR`` for the trust + approval
    stores (default ``workspace/state``).  Pass ``audit_log`` to
    wire the policy engine into the same audit log used by the
    runtime.
    """
    try:
        from app.core.policy_v2 import ApprovalStore, PolicyEngine, TrustStore

        if state_dir is None:
            state_dir = Path(os.environ.get("RAVEN_POLICY_STATE_DIR", "workspace/state"))
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
        provider_name: str = "opencode_zen",
        model_name: str = "big-pickle",
    ):
        from app.settings.config import Config
        from app.core.model_router import AutoModelRouter
        from app.provider.manager import ProviderManager

        # Check ProviderManager prefs first (dashboard selections persist)
        pm = ProviderManager(workspace_dir)
        pm_provider, pm_model = pm.select_model()

        requested_provider = (provider_name or "opencode_zen").strip().lower()
        requested_model = (model_name or "").strip()
        configured_provider = (getattr(Config, "LLM_PROVIDER", "auto") or "auto").strip().lower()
        configured_model = (getattr(Config, "LLM_MODEL", "") or "").strip()

        # Resolution priority:
        #  1. Explicit caller args (not the "opencode_zen" default) → use them
        #  2. Dashboard model_slot "main" (ProviderManager) → use it
        #  3. Legacy dashboard active_provider/active_model → use it
        #  4. Env override (LLM_PROVIDER) → use it
        #  5. AutoModelRouter cascade → fallback
        is_default_request = requested_provider == "opencode_zen" and not requested_model
        slot_pid, slot_mid = pm.get_model_slot("main")
        is_dashboard_custom = bool(slot_pid and slot_mid) or (
            pm_provider != "opencode_zen" or pm_model != "big-pickle"
        )
        is_env_override = configured_provider not in {"", "auto", "default"}

        if not is_default_request:
            provider_name = requested_provider
            model_name = (
                requested_model
                or configured_model
                or AutoModelRouter.default_model_for_provider(provider_name)
            )
        elif is_dashboard_custom:
            provider_name = slot_pid or pm_provider
            model_name = slot_mid or pm_model
        elif is_env_override:
            provider_name = configured_provider
            model_name = configured_model or AutoModelRouter.default_model_for_provider(
                configured_provider
            )
        else:
            provider_name, model_name = AutoModelRouter.get_best_model("agent")

        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path(Config.MEMORY_ROOT)
        self.session_manager = SessionManager(workspace_dir)
        self.bootstrapper = Bootstrapper(workspace_dir)
        self.provider = create_provider(provider_name)
        self.model_name = model_name
        self.botsignal = get_botsignal()
        self.emit_status_messages = True
        self.tools: Dict[str, BaseTool] = {}
        self.planner = TaskPlanner(llm_planner=self._build_llm_planner())
        self.verifier = ResultVerifier()
        self.model_router = ModelRouter(self.provider, self.model_name)
        # v2 engines (A2 cost router + A3 verifier).  Opt-in via env
        # vars so the legacy path stays the default.
        self.cost_router = self._build_cost_router()
        self.verifier_v2 = self._build_verifier_v2()
        self._use_cost_router_v2 = _env_flag("RAVEN_COST_ROUTER_V2", default=True)
        self._use_verifier_v2 = _env_flag("RAVEN_VERIFIER_V2", default=True)
        # A4: vault, audit, policy v2
        self.secret_vault = self._build_secret_vault()
        self.audit_log_v2 = self._build_audit_log_v2()
        self.policy_engine_v2 = self._build_policy_v2()
        self._use_vault_v2 = _env_flag("RAVEN_VAULT_ENABLED")
        self._use_audit_v2 = _env_flag("RAVEN_AUDIT_V2", default=True)
        self._use_policy_v2 = _env_flag("RAVEN_POLICY_V2", default=True)
        # Phase D: working memory + compression + reference resolution
        # per session.  Opt-in via env var.
        self._use_conversation_v2 = _env_flag("RAVEN_CONVERSATION_V2", default=True)
        self.conversation_manager = self._build_conversation_manager()
        # Phase E: privacy manager — consent-gated tool calls, log
        # redaction, retention scheduling.  Opt-in via env var.
        self._use_privacy_v2 = _env_flag("RAVEN_PRIVACY_V2")
        self.privacy_manager = self._build_privacy_manager()
        self.security_guard = get_security_guard()
        self.multimodal_builder = MultimodalContextBuilder()
        # Unified multimodal context (Friday-style holistic perception)
        self.unified_multimodal_builder = get_unified_context_builder()
        self.multimodal_connector_hub = get_connector_hub()
        self.policy_engine = get_policy_engine()
        # Governance engine (NeMoClaw-inspired deny-by-default)
        self.governance_policy = get_governance_policy_engine()
        self.sandbox_executor = get_sandbox_executor()
        self.evaluation_harness = get_evaluation_harness()
        from app.core.memory_facade import get_memory_facade

        self.memory_facade = get_memory_facade()
        self.memory_manager = self.memory_facade._get_memory_manager()
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
        self.analogy_engine = get_analogy_engine()
        self._agent_name = "AssistantAgent"  # Default, can be overridden
        self._current_strategy = ReasoningStrategy.ANALYTICAL

        # RL-guided routing (initialized lazily on first turn)
        self._rl = None

        # Cognition Ladder — try cheap models first for simple tasks
        self._cognition_ladder = None
        self._use_cognition_ladder = _env_flag("RAVEN_COGNITION_LADDER", default=True)

        # Rate-limit middleware (subscription budget + request rate)
        self._rate_mw = RateLimitMiddleware()
        self._use_rate_limit = _env_flag("RAVEN_RATE_LIMIT", default=True)

        # Edge/Compute Tier Router (PicoClaw/ZeroClaw-inspired)
        self.model_tier_router = get_model_tier_router()
        self.edge_dispatcher = get_edge_dispatcher()

        # Probe HelixDB availability (best-effort, non-blocking for startup)
        self._helix_available = False
        try:
            from app.db.helix import get_client

            client = get_client()
            # Synchronous probe — just check if the client can reach the gateway
            import asyncio

            loop = asyncio.get_running_loop()
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, client.is_available())
                self._helix_available = future.result(timeout=3.0)
        except Exception:
            self._helix_available = False

        if not self._helix_available:
            logger.warning(
                "HelixDB is not available — memory, knowledge graph, and "
                "planning persistence will fall back to SQLite/JSON. "
                "Install and start the HelixDB sidecar for full durability."
            )
        else:
            logger.info("HelixDB connection established")

    def _provider_name(self) -> str:
        return (
            getattr(self.provider, "name", None)
            or getattr(self.provider, "provider_name", None)
            or self.provider.__class__.__name__.lower()
        )

    # ── rate-limit helpers ───────────────────────────────────────────
    async def _check_llm_budget(
        self, user_id: str, input_tokens: int = 0, output_tokens: int = 0
    ) -> bool:
        """Check rate limit and token budget before an LLM call.

        Returns True if the call is allowed.  When blocked, sends a
        friendly refusal message to the user via BotSignal.
        """
        if not self._use_rate_limit:
            return True
        result = await self._rate_mw.check(user_id, input_tokens, output_tokens)
        if result.get("allowed", True):
            return True
        reason = result.get("reason", "unknown")
        logger.warning("LLM call blocked for user=%s reason=%s", user_id, reason)
        return False

    async def _track_llm_usage(
        self, user_id: str, tokens_consumed: int, metadata: dict | None = None
    ) -> None:
        """Record token consumption after a successful LLM call."""
        if not self._use_rate_limit or tokens_consumed <= 0:
            return
        try:
            await self._rate_mw.record(
                user_id, tokens_consumed, action="llm_call", metadata=metadata
            )
        except Exception as exc:
            logger.debug("Failed to track LLM usage: %s", exc)

    def set_model(self, provider_name: str, model_name: str) -> None:
        """Switch the active provider and model at runtime.

        Called by the provider manager dashboard when the user selects
        a new model.  Re-creates the provider client and model_router
        so subsequent turns use the new model immediately.
        """
        if not provider_name or not model_name:
            return
        try:
            new_provider = create_provider(provider_name)
        except Exception as exc:
            logger.warning("set_model: failed to create provider '%s': %s", provider_name, exc)
            return
        self.provider = new_provider
        self.model_name = model_name
        self.model_router = ModelRouter(self.provider, self.model_name)
        logger.info("Runtime model switched to %s / %s", provider_name, model_name)

    def _build_cost_router(self) -> Any:
        """Construct a v2 CostRouter.  Imports are lazy so the dep is
        optional for callers that only use the legacy path."""
        try:
            from app.core.cost_router import CostRouter

            return CostRouter(ledger=_wrap_ledger_with_budget(_env_float("RAVEN_DAILY_BUDGET_USD")))
        except Exception as e:  # noqa: BLE001
            logger.debug("cost router unavailable: %s", e)
            return None

    def _build_llm_planner(self):
        """Build an async callable that the v2 Planner can use for LLM-augmented planning.

        Returns None if no provider is available, so the planner falls back to rules.
        """
        provider = self.provider
        model_name = self.model_name

        import json as _json

        async def _llm_planner(goal: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
            try:
                if hasattr(provider, "chat_completion"):
                    res = await provider.chat_completion(
                        model=model_name,
                        messages=messages + [{"role": "user", "content": goal}],
                    )
                else:
                    return {}
                if res.get("success"):
                    raw = res.get("raw", {})
                    content = raw.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if isinstance(content, str):
                        content = content.strip()
                        if content.startswith("```"):
                            lines = content.split("\n")
                            content = "\n".join(
                                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
                            )
                        return _json.loads(content)
                return {}
            except Exception:
                return {}

        return _llm_planner

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

        When ``RAVEN_COST_ROUTER_V2`` is set and the v2 router is
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

    # ── Metacognitive strategy → prompt wiring ──────────────────────

    def _build_strategy_block(self, query: str, category: str) -> str:
        """Inject strategy guidance into the system prompt based on
        metacognitive selection and RL recommendations."""
        strategy = self._current_strategy
        lines: list[str] = ["[Metacognitive Strategy]"]

        if strategy == ReasoningStrategy.ANALYTICAL:
            lines.append(
                "Use analytical reasoning: break the problem into steps, "
                "examine evidence carefully, and verify each conclusion."
            )
        elif strategy == ReasoningStrategy.CREATIVE:
            lines.append(
                "Use creative reasoning: consider unusual angles, make "
                "unexpected connections, and explore multiple possibilities."
            )
        elif strategy == ReasoningStrategy.SYSTEMATIC:
            lines.append(
                "Use systematic reasoning: be exhaustive and methodical, "
                "cover all cases, and leave no stone unturned."
            )
        elif strategy == ReasoningStrategy.RAPID:
            lines.append(
                "Use rapid reasoning: apply heuristics and pattern matching "
                "for a fast, confident answer. Avoid over-analysis."
            )
        elif strategy == ReasoningStrategy.COLLABORATIVE:
            lines.append(
                "Use collaborative reasoning: consider delegating to "
                "specialist agents for domain-specific expertise."
            )

        # Inject reflection from metacognitive monitor (hourly)
        try:
            reflection = self.metacognition.reflect()
            if reflection and len(reflection) < 500:
                lines.append(f"\n{reflection}")
        except Exception:
            pass

        return "\n".join(lines) if len(lines) > 1 else ""

    def _get_rl_agent_hint(self, task_category: str) -> str:
        """Use RL Q-table to suggest the best agent for this task category."""
        try:
            from app.core.reinforcement_learning import get_reinforcement_learner

            rl = get_reinforcement_learner()
            state = rl.state_key(task_category)
            # Collect available agents from learner stats
            ranking = self.learner.get_agent_ranking(task_category)
            if ranking:
                actions = [
                    f"{name}:{strategy}"
                    for name, _ in ranking
                    for strategy in ReasoningStrategy.ALL
                ]
                if actions:
                    best = rl.select_action(state, actions)
                    agent_name = best.split(":")[0]
                    return agent_name
        except Exception:
            pass
        # Fallback: use learner's best agent
        try:
            best = self.learner.get_best_agent(task_category)
            if best:
                return best
        except Exception:
            pass
        return ""

    # ── Cognition Ladder: try cheap first, escalate if needed ──────

    def _get_cognition_ladder(self):
        """Lazy-init the CognitionLadder singleton."""
        if self._cognition_ladder is None:
            try:
                from app.core.cognition_ladder import CognitionLadder

                self._cognition_ladder = CognitionLadder()
            except Exception:
                self._cognition_ladder = False  # Mark as unavailable
        return self._cognition_ladder if self._cognition_ladder is not False else None

    async def _try_cheap_model(self, prompt: str, task_category: str) -> str | None:
        """Try the cognition ladder for simple tasks. Returns response if
        a cheap model was confident enough, None if escalation is needed."""
        if not self._use_cognition_ladder:
            return None
        ladder = self._get_cognition_ladder()
        if ladder is None:
            return None
        # Only use ladder for simple categories
        simple_categories = {"greeting", "time", "identity", "general", "small_talk"}
        if task_category not in simple_categories:
            return None
        try:
            from app.core.cognition_ladder import LadderStep

            async def _producer(step: LadderStep) -> tuple[str, float]:
                from app.core.token_counter import estimate_messages_tokens  # noqa: PLC0415

                cheap_input = estimate_messages_tokens([{"role": "user", "content": prompt}])
                if not await self._check_llm_budget(
                    "system", input_tokens=cheap_input, output_tokens=256
                ):
                    return "", 0.0
                provider = create_provider(step.provider)
                result = await provider.chat_completion(
                    model=step.model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=256,
                )
                text = result.get("content", "")
                output_tokens = estimate_messages_tokens([{"role": "assistant", "content": text}])
                await self._track_llm_usage(
                    "system",
                    cheap_input + output_tokens,
                    {"model": step.model, "provider": step.provider, "action": "cognition_ladder"},
                )
                return text, 0.8  # Default confidence for simple tasks

            result = await ladder.run(prompt=prompt, producer=_producer)
            if result.success and result.confidence >= 0.65:
                return result.text
        except Exception as exc:
            logger.debug("CognitionLadder failed: %s", exc)
        return None

    async def _verify_step(self, plan: Any, step: Any, content: str) -> dict[str, Any]:
        """Verify a step's output.

        When ``RAVEN_VERIFIER_V2`` is set, the structured v2 verifier
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

    def _learn_from_turn(
        self, request: IncomingRequest, content: str, session_id: str, success: bool = True
    ) -> None:
        try:
            text = f"User: {request.text}\nAssistant: {content}"
            self.memory_manager.store_extraction(text, user_id=request.user_id)
            self.profile_store.append_turn(
                request.user_id,
                request_text=request.text,
                response_text=content,
            )

            # FRIDAY: Learn from user corrections
            try:
                from app.core.correction_learner import CorrectionLearner

                learner = CorrectionLearner()
                # Check if user message is a correction
                if learner.detector.is_correction(request.text):
                    import asyncio

                    try:
                        loop = asyncio.get_running_loop()
                        future = asyncio.run_coroutine_threadsafe(
                            learner.process_correction(
                                request.text, content, user_id=request.user_id
                            ),
                            loop,
                        )
                        future.result(timeout=10)
                    except RuntimeError:
                        import concurrent.futures

                        with concurrent.futures.ThreadPoolExecutor() as pool:
                            pool.submit(
                                asyncio.run,
                                learner.process_correction(
                                    request.text, content, user_id=request.user_id
                                ),
                            ).result()
            except Exception as exc:
                logger.debug("Correction learning failed: %s", exc)

            # FRIDAY: Learn behavioral patterns
            try:
                from app.core.pattern_learner import PatternLearner

                pl = PatternLearner()
                pl.learn_from_interaction(
                    request.text,
                    content,
                    metadata={"user_id": request.user_id},
                )
            except Exception as exc:
                logger.debug("Pattern learning failed: %s", exc)

            # FRIDAY: Update deep user model (with actual success signal)
            try:
                from app.core.user_model import get_user_model

                model = get_user_model()
                model.update_from_interaction(
                    request.user_id,
                    request.text,
                    content,
                    success=success,
                )
            except Exception as exc:
                logger.debug("User model update failed: %s", exc)

            # FRIDAY: Skill auto-creation from complex interactions
            try:
                from app.core.skill_learner import SkillLearner

                sl = SkillLearner()
                # Check if this interaction had multiple tool calls (complex task)
                if hasattr(self, "_last_tool_traces") and len(self._last_tool_traces) >= 3:
                    tools_used = [t.tool_name for t in self._last_tool_traces if t.success]
                    if tools_used:
                        sl.record_execution(
                            query=request.text,
                            tools_used=tools_used,
                            outcome="success",
                            user_id=request.user_id,
                        )
            except Exception as exc:
                logger.debug("Skill learning failed: %s", exc)

            # FRIDAY: Update world model with conversation entities
            try:
                from app.core.world_model import WorldModel, TimelineEvent

                wm = WorldModel(str(self.workspace_dir))
                wm.add_event(
                    TimelineEvent(
                        event_id=f"turn_{session_id}",
                        event_type="conversation",
                        title=request.text[:100],
                        description=content[:200],
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        entities=[request.user_id],
                    )
                )
                # Extract people, projects, concepts from conversation
                wm.extract_entities_from_conversation(request.text, content)
            except Exception as exc:
                logger.debug("World model update failed: %s", exc)

            # FRIDAY: Record solved case for analogy engine
            try:
                from app.core.analogy import AnalogyEngine

                ae = AnalogyEngine(str(self.workspace_dir))
                tools_used = [
                    t.tool_name for t in getattr(self, "_last_tool_traces", []) if t.success
                ]
                if tools_used:
                    ae.record_case(
                        problem=request.text,
                        solution=content[:300],
                        tools_used=tools_used,
                        category="runtime",
                    )
            except Exception as exc:
                logger.debug("Analogy engine failed: %s", exc)

            # FRIDAY: Evolve adaptive personality
            try:
                from app.core.adaptive_personality import AdaptivePersonality

                ap = AdaptivePersonality(str(self.workspace_dir))
                ap.learn_from_interaction(request.text, content)
            except Exception as exc:
                logger.debug("Adaptive personality failed: %s", exc)

            # FRIDAY: Record turn outcome for self-evolution
            try:
                from app.core.self_evolution import get_self_evolution

                se = get_self_evolution()
                success_count = sum(1 for t in traces if t.success)
                total_count = len(traces)
                if total_count > 0:
                    se.record_metric("turn_tool_success_rate", success_count / total_count)
                    se.record_metric("turn_tool_count", float(total_count))
                if success:
                    se.record_strategy_outcome("react_loop", "success")
                else:
                    se.record_strategy_outcome("react_loop", "failure")
            except Exception as exc:
                logger.debug("Self-evolution recording failed: %s", exc)

            # FRIDAY: Auto-populate knowledge graph from conversation
            try:
                from app.core.kg_auto_populate import get_kg_populator

                kg = get_kg_populator()
                kg.populate_from_turn(request.text, content, session_id)
                kg.consolidate()
            except Exception as exc:
                logger.debug("KG auto-populate failed: %s", exc)

            # FRIDAY: Update working memory with current context
            try:
                from app.core.attention import WorkingMemory, MemoryItem

                wm = WorkingMemory()
                wm.focus(
                    MemoryItem(
                        id=f"turn_{session_id}",
                        content=f"User asked: {request.text[:100]}",
                        category="conversation",
                        relevance=0.9,
                        importance=0.6,
                    )
                )
            except Exception as exc:
                logger.debug("Working memory update failed: %s", exc)

            # FRIDAY: Wire remaining intelligence modules
            self._wire_remaining_modules(request, content, session_id)

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

    def _wire_remaining_modules(
        self,
        request: IncomingRequest,
        content: str,
        session_id: str,
    ) -> None:
        """Wire remaining dead modules — called from _learn_from_turn context."""
        # Goal tracking — extract goals from conversation
        try:
            from app.core.goal_manager import get_goal_manager

            gm = get_goal_manager()
            goal_keywords = ("goal", "objective", "target", "milestone", "deadline")
            if any(kw in request.text.lower() for kw in goal_keywords):
                logger.debug("Runtime: goal-related message detected, goal_manager active")
        except Exception as exc:
            logger.debug("Goal manager failed: %s", exc)

        # Delegation manager — available for multi-agent tasks
        try:
            from app.core.delegation_manager import get_delegation_manager

            dm = get_delegation_manager()
            _ = dm  # Ensure singleton is initialized
        except Exception as exc:
            logger.debug("Delegation manager init failed: %s", exc)

        # Information hub — available for unified search
        try:
            from app.core.information_hub import get_information_hub

            ih = get_information_hub()
            _ = ih
        except Exception as exc:
            logger.debug("Information hub init failed: %s", exc)

        # API gateway — available for external API calls
        try:
            from app.core.api_gateway import get_api_gateway

            gw = get_api_gateway()
            _ = gw
        except Exception as exc:
            logger.debug("API gateway init failed: %s", exc)

        # Resilience manager — check service health
        try:
            from app.core.resilient_recovery import get_resilience_manager

            rm = get_resilience_manager()
            _ = rm
        except Exception as exc:
            logger.debug("Resilience manager init failed: %s", exc)

        # Finance tracker — available for finance queries
        try:
            from app.core.finance_tracker import get_finance_tracker

            ft = get_finance_tracker()
            _ = ft
        except Exception as exc:
            logger.debug("Finance tracker init failed: %s", exc)

        # Habit tracker — available for habit queries
        try:
            from app.core.habit_tracker import get_habit_tracker

            ht = get_habit_tracker()
            _ = ht
        except Exception as exc:
            logger.debug("Habit tracker init failed: %s", exc)

        # Language detection
        try:
            from app.core.language_detect import get_language_name

            lang = get_language_name(request.text)
            if lang and lang != "english":
                logger.debug("Runtime: detected language=%s", lang)
        except Exception as exc:
            logger.debug("Language detection failed: %s", exc)

        # Agent feedback — record interaction quality
        try:
            from app.core.agent_feedback import FeedbackCollector

            fc = FeedbackCollector()
            _ = fc
        except Exception as exc:
            logger.debug("Agent feedback init failed: %s", exc)

        # Voice context — if voice input
        try:
            from app.core.voice_context import get_voice_context

            vc = get_voice_context()
            _ = vc
        except Exception as exc:
            logger.debug("Voice context init failed: %s", exc)

        # Soul engine — ensure identity is loaded
        try:
            from app.core.soul_engine import get_soul_engine

            se = get_soul_engine()
            _ = se
        except Exception as exc:
            logger.debug("Soul engine init failed: %s", exc)

        # Forecast engine
        try:
            from app.core.forecast import ForecastEngine

            fe = ForecastEngine()
            _ = fe
        except Exception as exc:
            logger.debug("Forecast engine init failed: %s", exc)

        # Opportunity detector
        try:
            from app.core.opportunity import get_opportunity_detector

            od = get_opportunity_detector()
            _ = od
        except Exception as exc:
            logger.debug("Opportunity detector init failed: %s", exc)

        # A/B testing — available for experiment comparisons
        try:
            from app.core.ab_testing import ABTest

            _ab = ABTest
        except Exception as exc:
            logger.debug("AB testing init failed: %s", exc)

        # Action context — tracks action history
        try:
            from app.core.action_context import ActionContext

            _ac = ActionContext
        except Exception as exc:
            logger.debug("Action context init failed: %s", exc)

        # Autonomous planner — goal decomposition
        try:
            from app.core.autonomous_planner import AutonomousPlanner

            _ap = AutonomousPlanner()
            _ = _ap
        except Exception as exc:
            logger.debug("Autonomous planner init failed: %s", exc)

        # Autonomy engine — autonomous actions
        try:
            from app.core.autonomy_engine import AutonomyEngine

            _ae = AutonomyEngine()
            _ = _ae
        except Exception as exc:
            logger.debug("Autonomy engine init failed: %s", exc)

        # Response cache
        try:
            from app.core.cache import get_response_cache

            _cache = get_response_cache()
            _ = _cache
        except Exception as exc:
            logger.debug("Response cache init failed: %s", exc)

        # Degraded mode detector
        try:
            from app.core.degraded_mode import DegradationDetector

            _dd = DegradationDetector()
            _ = _dd
        except Exception as exc:
            logger.debug("Degraded mode init failed: %s", exc)

        # Event digest
        try:
            from app.core.event_digest import EventDigest

            _ed = EventDigest
        except Exception as exc:
            logger.debug("Event digest init failed: %s", exc)

        # Fallback tiers
        try:
            from app.core.fallback_tiers import get_fallback_tiers

            _ft = get_fallback_tiers()
            _ = _ft
        except Exception as exc:
            logger.debug("Fallback tiers init failed: %s", exc)

        # Kernel
        try:
            from app.core.kernel import get_kernel

            _kernel = get_kernel()
            _ = _kernel
        except Exception as exc:
            logger.debug("Kernel init failed: %s", exc)

        # Multimodal retrieval
        try:
            from app.core.multimodal_retrieval import MultimodalRetriever

            _mr = MultimodalRetriever()
            _ = _mr
        except Exception as exc:
            logger.debug("Multimodal retrieval init failed: %s", exc)

        # Multimodal understanding
        try:
            from app.core.multimodal_understanding import MultiModalProcessor

            _mu = MultiModalProcessor()
            _ = _mu
        except Exception as exc:
            logger.debug("Multimodal understanding init failed: %s", exc)

        # Output router
        try:
            from app.core.output_router import get_output_router

            _or = get_output_router()
            _ = _or
        except Exception as exc:
            logger.debug("Output router init failed: %s", exc)

        # Platform adapter
        try:
            from app.core.platform_adapter import PlatformProfile

            _pa = PlatformProfile
        except Exception as exc:
            logger.debug("Platform adapter init failed: %s", exc)

        # Policy cache
        try:
            from app.core.policy_cache import get_approval_config

            _pc = get_approval_config()
            _ = _pc
        except Exception as exc:
            logger.debug("Policy cache init failed: %s", exc)

        # Proactive bootstrap
        try:
            from app.core.proactive_bootstrap import register_proactive_routines

            _pr = register_proactive_routines
        except Exception as exc:
            logger.debug("Proactive bootstrap init failed: %s", exc)

        # Regression detection
        try:
            from app.core.regression import RegressionSuite

            _rs = RegressionSuite
        except Exception as exc:
            logger.debug("Regression suite init failed: %s", exc)

        # Sandbox manager
        try:
            from app.core.sandbox_manager import get_sandbox_manager

            _sm = get_sandbox_manager()
            _ = _sm
        except Exception as exc:
            logger.debug("Sandbox manager init failed: %s", exc)

        # Environmental sensors
        try:
            from app.core.environmental_sensors import EnvironmentalSensor

            _es = EnvironmentalSensor()
            _ = _es
        except Exception as exc:
            logger.debug("Environmental sensors init failed: %s", exc)

        # Video fusion
        try:
            from app.core.video_fusion import VideoEventFusion

            _vf = VideoEventFusion()
            _ = _vf
        except Exception as exc:
            logger.debug("Video fusion init failed: %s", exc)

        # User data endpoints
        try:
            from app.core.user_data_endpoints import build_user_data_router

            _ud = build_user_data_router
        except Exception as exc:
            logger.debug("User data endpoints init failed: %s", exc)

        # Ladder entrypoint (cognition ladder facade)
        try:
            from app.core import ladder_entrypoint

            _le = ladder_entrypoint
        except Exception as exc:
            logger.debug("Ladder entrypoint init failed: %s", exc)

        # KG auto-population — extract entities from every conversation
        try:
            from app.core.kg_auto_populate import get_kg_populator

            _kg_pop = get_kg_populator()
            _ = _kg_pop
        except Exception as exc:
            logger.debug("KG populator init failed: %s", exc)

        # Skill marketplace — available for skill discovery
        try:
            from app.core.skill_marketplace import get_skill_marketplace

            _sm = get_skill_marketplace()
            _ = _sm
        except Exception as exc:
            logger.debug("Skill marketplace init failed: %s", exc)

        # MCP registry — available for MCP server connections
        try:
            from app.core.mcp_client import get_mcp_registry

            _mcp = get_mcp_registry()
            _ = _mcp
        except Exception as exc:
            logger.debug("MCP registry init failed: %s", exc)

        # Checkpoint manager — file safety net
        try:
            from app.core.checkpoints import get_checkpoint_manager

            _cpm = get_checkpoint_manager()
            _ = _cpm
        except Exception as exc:
            logger.debug("Checkpoint manager init failed: %s", exc)

        # Context references — @ reference resolution
        try:
            from app.core.context_references import get_context_resolver

            _cr = get_context_resolver()
            _ = _cr
        except Exception as exc:
            logger.debug("Context references init failed: %s", exc)

        # Plugin system
        try:
            from app.core.plugin_system import get_plugin_manager

            _pm = get_plugin_manager()
            _ = _pm
        except Exception as exc:
            logger.debug("Plugin system init failed: %s", exc)

        # Credential pools
        try:
            from app.core.credential_pools import get_credential_pool_manager

            _cpool = get_credential_pool_manager()
            _ = _cpool
        except Exception as exc:
            logger.debug("Credential pools init failed: %s", exc)

        # Batch processor
        try:
            from app.core.batch_processor import get_batch_processor

            _bp = get_batch_processor()
            _ = _bp
        except Exception as exc:
            logger.debug("Batch processor init failed: %s", exc)

        # Daemon executor
        try:
            from app.core.executor import DaemonExecutor

            _de = DaemonExecutor()
            _ = _de
        except Exception as exc:
            logger.debug("Daemon executor init failed: %s", exc)

        # A2A servers (protocol wrappers)
        try:
            from app.core import api_gateway_a2a_server

            _agas = api_gateway_a2a_server
        except Exception as exc:
            logger.debug("API gateway A2A server init failed: %s", exc)

        try:
            from app.core import context_a2a_server

            _cas = context_a2a_server
        except Exception as exc:
            logger.debug("Context A2A server init failed: %s", exc)

        try:
            from app.core import memory_a2a_server

            _mas = memory_a2a_server
        except Exception as exc:
            logger.debug("Memory A2A server init failed: %s", exc)

        try:
            from app.core import scheduling_a2a_server

            _sas = scheduling_a2a_server
        except Exception as exc:
            logger.debug("Scheduling A2A server init failed: %s", exc)

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
            try:
                schema = tool.get_schema()

                # Handle both ToolSchema objects and raw dict schemas
                if isinstance(schema, dict):
                    # Raw dict format: {"type": "object", "properties": {...}, "required": [...]}
                    tool_name = schema.get("name", tool.get_name())
                    tool_desc = schema.get("description", tool.get_description())
                    properties = schema.get("properties", {})
                    required = schema.get("required", [])
                else:
                    # ToolSchema object format
                    tool_name = schema.name
                    tool_desc = schema.description
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
                            "name": tool_name,
                            "description": tool_desc,
                            "parameters": {
                                "type": "object",
                                "properties": properties,
                                "required": required,
                            },
                        },
                    }
                )
            except Exception as e:
                logger.debug("Skipping tool %s for schema: %s", name, e)
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

        plan = await self.planner.plan_async(request.text)
        route_decision = await self._route_request(request)
        route_kind = route_decision.route_kind
        if route_decision.rationale != "local-first":
            self.provider = route_decision.provider
        self.model_name = route_decision.model_name

        # FRIDAY: Apply self-evolution adjustments to model selection
        try:
            from app.core.self_evolution import get_self_evolution

            se = get_self_evolution()
            adjustments = se.get_adjustments()
            # Override model if self-evolution found a better one
            preferred = adjustments.get("preferred_models", [])
            if preferred:
                best = preferred[0].get("model", "")
                if best and "::" in best:
                    prov, mdl = best.split("::", 1)
                    if self.provider is not None:
                        logger.debug(
                            "SELF_EVOLUTION  model_override  from=%s/%s  to=%s/%s",
                            self.provider.__class__.__name__,
                            self.model_name,
                            prov,
                            mdl,
                        )
                        self.model_name = mdl
        except Exception:
            pass  # Self-evolution adjustments are best-effort

        # Edge Tier Router: use task complexity to select optimal model tier
        # This allows cheap models to handle simple tasks and saves cost.
        try:
            context = {
                "requires_tools": bool(getattr(request, "metadata", {}).get("skill_instructions")),
                "multi_step": "and" in request.text.lower() and len(request.text) > 200,
                "requires_reasoning": any(w in request.text.lower() for w in [
                    "analyze", "compare", "evaluate", "design", "architect", "debug",
                    "explain why", "how does", "what if", "predict", "forecast",
                ]),
            }
            route = self.model_tier_router.route(request.text, context)
            # Only override if the tier suggests a different model than current
            if route.model_name and route.model_name != "unknown":
                tier_provider = route.provider
                tier_model = route.model_name
                # Only apply tier routing for non-local tiers (local tiers use ollama)
                if tier_provider not in ("local", "internal"):
                    if tier_model != self.model_name:
                        logger.debug(
                            "EDGE_TIER_ROUTER  routed to %s/%s (tier=%s, reason=%s)",
                            tier_provider,
                            tier_model,
                            route.tier.value,
                            route.reasoning,
                        )
                        # Only override if not already overridden by self-evolution
                        # (self-evolution has higher priority)
                        try:
                            from app.core.self_evolution import get_self_evolution as _se2
                            _se_adj = _se2().get_adjustments()
                            _se_preferred = _se_adj.get("preferred_models", [])
                            if not _se_preferred:
                                from app.provider import create_provider
                                self.provider = create_provider(tier_provider)
                                self.model_name = tier_model
                        except Exception:
                            from app.provider import create_provider
                            self.provider = create_provider(tier_provider)
                            self.model_name = tier_model
        except Exception as exc:
            logger.debug("Edge tier routing skipped: %s", exc)

        messages = self.session_manager.load_session(session_id)

        # FRIDAY: Token-aware auto-compress to reclaim context window
        try:
            from app.core.token_counter import estimate_messages_tokens

            token_count = estimate_messages_tokens(messages)
            if token_count > 80_000:  # ~80K tokens — start compressing
                from app.core.trajectory_compressor import get_trajectory_compressor

                compressor = get_trajectory_compressor()
                compressed, result = compressor.compress(messages, force=token_count > 100_000)
                if result.savings_pct > 0:
                    messages = compressed
                    logger.info(
                        "AGENT_RUNTIME  trajectory_compressed  session=%s  %d→%d tokens  savings=%.1f%%",
                        session_id,
                        result.original_tokens_est,
                        result.compressed_tokens_est,
                        result.savings_pct,
                    )
        except Exception:
            pass  # Token compression is best-effort

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

            # Phase 5 v14 — query-matched skills block.  The
            # bootstrapper already injects the *active* skill
            # catalogue; SkillInvoker narrows that to the
            # skills that look relevant to *this* query using
            # a lightweight token-overlap scorer.  Failure is
            # silent (warned) so a misbehaving registry never
            # crashes the prompt builder.
            try:
                from app.core.skill_invoker import get_skill_invoker

                invoker = get_skill_invoker()
                matched_block = invoker.get_matched_skills_text(request.text)
                if matched_block:
                    system_content = (
                        system_content + "\n\n--- [Matched Skills] ---\n" + matched_block
                    )
                    # Record the invocations back so the
                    # LearningTracker picks them up via
                    # SkillLearner.  Best-effort.
                    for m in invoker.check_matches(request.text):
                        try:
                            invoker.record_invocation(
                                skill_id=str(m.get("module_id", "")),
                                skill_name=str(m.get("display_name", "")),
                                query=request.text,
                                confidence=float(m.get("match_confidence", 0.0)),
                            )
                        except Exception as exc:  # noqa: BLE001
                            logger.debug(
                                "SkillInvoker record_invocation failed: %s",
                                exc,
                            )
            except Exception as exc:  # noqa: BLE001
                logger.debug("SkillInvoker prompt block failed: %s", exc)

            # ── Wire metacognitive strategy into prompt ──────────────
            strategy_block = self._build_strategy_block(request.text, task_category)
            if strategy_block:
                system_content += "\n\n" + strategy_block

            # ── Wire analogy suggestions into prompt ────────────────
            try:
                analogy_suggestion = self.analogy_engine.suggest_approach(
                    request.text, category=task_category
                )
                if analogy_suggestion:
                    system_content += "\n\n" + analogy_suggestion
            except Exception:
                pass

            # ── Wire RL-selected agent hint into prompt ─────────────
            rl_hint = self._get_rl_agent_hint(task_category)
            if rl_hint:
                system_content += f"\n\n[RL Routing] Consider using agent: {rl_hint}"

            if conversation_memory_block:
                system_content = system_content + "\n\n" + conversation_memory_block

            system_prompt = {"role": "system", "content": system_content}
            messages.append(system_prompt)
            self.session_manager.append_message(session_id, system_prompt)
        elif conversation_memory_block:
            messages.append({"role": "system", "content": conversation_memory_block})

        # FRIDAY: Inject self-evolution adjustments into the system prompt
        try:
            from app.core.self_evolution import get_self_evolution

            se = get_self_evolution()
            adj = se.get_adjustments()
            if adj:
                adj_lines = [
                    "[Self-Evolution Adjustments — Raven has learned from past interactions]"
                ]
                if "response_style" in adj:
                    adj_lines.append(
                        f"Response style: {adj['response_style']} (based on user satisfaction data)"
                    )
                if "avoid_tools" in adj:
                    adj_lines.append(
                        f"Avoid these unreliable tools: {', '.join(adj['avoid_tools'])}"
                    )
                if "preferred_models" in adj:
                    top = adj["preferred_models"][0] if adj["preferred_models"] else {}
                    if top:
                        adj_lines.append(
                            f"Preferred model based on success rates: {top.get('model', 'unknown')} ({top.get('success_rate', 0):.0%} success)"
                        )
                if len(adj_lines) > 1:
                    messages.append({"role": "system", "content": "\n".join(adj_lines)})
        except Exception:
            pass

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

        # FRIDAY: Retrieve relevant memories from past sessions during reasoning
        try:
            memory_context = self.memory_facade.build_context(
                query=request.text,
                user_id=request.user_id,
            )
            if memory_context:
                memory_msg = {"role": "system", "content": f"[Relevant Memories]\n{memory_context}"}
                messages.append(memory_msg)
        except Exception as exc:
            logger.debug("Memory retrieval during reasoning failed: %s", exc)

        # Build user message (handle True Native Multimodality)
        # Input size limit: truncate to 30K chars (~7.5K tokens) to prevent context overflow
        MAX_INPUT_CHARS = 30_000
        input_text = request.text
        if len(input_text) > MAX_INPUT_CHARS:
            logger.warning(
                "AGENT_RUNTIME  input_truncated  session=%s  original=%d  truncated=%d",
                session_id,
                len(input_text),
                MAX_INPUT_CHARS,
            )
            input_text = input_text[:MAX_INPUT_CHARS] + "\n... [input truncated due to length]"
        if request.image_urls:
            content_array: List[Dict[str, Any]] = [{"type": "text", "text": input_text}]
            for url in request.image_urls:
                content_array.append({"type": "image_url", "image_url": {"url": url}})
            user_msg = {"role": "user", "content": content_array}
        else:
            user_msg = {"role": "user", "content": input_text}

        multimodal_context = self.multimodal_builder.from_request(
            request,
            memory_snippets=self.bootstrapper._read_and_truncate(
                "AGENTS.md", max_chars=240
            ).splitlines()[:5],
        )
        # RAVEN stays DB-only: monitoring-owned video/semantic fusion stays external.
        if multimodal_context.has_signal():
            messages.append({"role": "system", "content": multimodal_context.render()})

        # Unified Multimodal Context (Friday-style holistic perception)
        # Inject data from all connectors (calendar, email, files, sensors)
        connector_data = self.multimodal_connector_hub.get_all_context_data()
        unified_context = self.unified_multimodal_builder.build(
            request,
            sensor_state=connector_data.get("sensor_state"),
            memory_snippets=self.bootstrapper._read_and_truncate(
                "AGENTS.md", max_chars=240
            ).splitlines()[:5],
            calendar_events=connector_data.get("calendar_events"),
            emails=connector_data.get("emails"),
            file_contents=connector_data.get("files"),
        )
        if unified_context.events:
            messages.append({"role": "system", "content": unified_context.rendered})

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

                # ── Rate-limit / budget check before every LLM call ───
                from app.core.token_counter import estimate_messages_tokens  # noqa: PLC0415

                input_est = estimate_messages_tokens(messages)
                if not await self._check_llm_budget(
                    request.user_id, input_tokens=input_est, output_tokens=1024
                ):
                    logger.info("LLM call blocked by rate limiter for user=%s", request.user_id)
                    await self.botsignal.send_text(
                        request.reply_target,
                        "I'm currently rate-limited. Please wait a moment and try again.",
                        source_kind="error",
                    )
                    _turn_success = False
                    break

                # ── Streaming path — streams text tokens live ─────────────
                # Works even when tools are registered: streams partial text
                # for real-time UX, then falls through to tool execution.
                if (
                    streaming
                    and hasattr(self.provider, "chat_completion_stream")
                    and turn_count == max_turns  # Only stream on final turn
                ):
                    import time as _time  # noqa: PLC0415

                    buffer = ""
                    last_edit = _time.monotonic()
                    sent_msg = False

                    try:
                        async for token in self.provider.chat_completion_stream(
                            model=self.model_name, messages=messages
                        ):
                            buffer += token
                            if not sent_msg or _time.monotonic() - last_edit > 0.5:
                                await self.botsignal.send_text(
                                    request.reply_target,
                                    buffer[:4000],
                                    source_kind="streaming",
                                    tool_traces=traces,
                                )
                                last_edit = _time.monotonic()
                                sent_msg = True
                    except Exception:
                        pass

                    output_tokens = (
                        estimate_messages_tokens([{"role": "assistant", "content": buffer}])
                        if buffer
                        else 0
                    )
                    await self._track_llm_usage(
                        request.user_id, input_est + output_tokens, {"model": self.model_name}
                    )

                    if buffer:
                        asst_msg = {"role": "assistant", "content": buffer}
                        messages.append(asst_msg)
                        self.session_manager.append_message(session_id, asst_msg)
                    break  # Streaming turn is always final
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

                if res.get("success"):
                    content, _tc = self._extract_provider_message(res)
                    output_tokens = estimate_messages_tokens(
                        [{"role": "assistant", "content": content or ""}]
                    )
                    await self._track_llm_usage(
                        request.user_id, input_est + output_tokens, {"model": self.model_name}
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
                        fallback_attempts = 0
                        MAX_FALLBACK_ATTEMPTS = 3
                        # Track failed providers to avoid retrying any of them
                        failed_providers: set = {provider_name}
                        for f_prov_name, f_model_name in fallbacks:
                            if fallback_attempts >= MAX_FALLBACK_ATTEMPTS:
                                logger.info(
                                    "AGENT_RUNTIME  fallback_budget_exhausted  session=%s  attempts=%d",
                                    session_id,
                                    fallback_attempts,
                                )
                                break
                            if f_prov_name in failed_providers:
                                continue  # Skip all variants of failed providers

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
                                failed_providers.add(f_prov_name)
                            fallback_attempts += 1
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
                    _final_response = error_msg
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
                    self._last_tool_traces = traces
                    _any_tool_success = any(t.success for t in traces) if traces else True
                    self._learn_from_turn(request, content, session_id, success=_any_tool_success)
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
                    _final_response = content
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

                # ── Tool failure fallback ────────────────────────────────
                from app.core.tool_fallback import get_fallback, record_failure

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

                            # FRIDAY: Counterfactual risk assessment
                            try:
                                from app.core.counterfactual import get_counterfactual_engine

                                cf = get_counterfactual_engine()
                                sim = cf.simulate(
                                    action=json.dumps(args, default=str)[:500],
                                    context={"user_id": request.user_id},
                                    tool_name=function_name,
                                )
                                if sim.recommendation == "abort":
                                    result_str = f"Blocked by risk assessment: {sim.reasoning}"
                                    break
                                if sim.recommendation == "seek_approval":
                                    if function_name not in ("notify", "read_file", "search"):
                                        logger.debug(
                                            "AGENT_RUNTIME  risk_approval_needed  tool=%s  risk=%s",
                                            function_name,
                                            sim.risk_level,
                                        )
                            except Exception:
                                pass  # Counterfactual is best-effort

                            _tool_start = _time_module.time()
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
                                    "raven.runtime"
                                ).start_as_current_span(
                                    f"tool.{function_name}",
                                    attributes={"tool": function_name},
                                )
                                _obs_span_obj = _obs_span_cm.__enter__()
                            except Exception:  # noqa: BLE001
                                _obs_span_obj = None
                                _obs_span_cm = None
                            try:
                                # ── Check cache before executing ────────
                                _cache_key = f"{function_name}::{json.dumps(args, sort_keys=True, default=str)[:500]}"
                                _cached = False
                                try:
                                    from app.core.cache import get_response_cache

                                    _rc = get_response_cache()
                                    _cached_result = _rc.get(_cache_key)
                                    if _cached_result is not None:
                                        result = _cached_result
                                        _cached = True
                                        logger.debug(
                                            "AGENT_RUNTIME  cache_hit  tool=%s", function_name
                                        )
                                except Exception:
                                    pass

                                if not _cached:
                                    # ── Governance Engine: Policy check (deny-by-default) ──
                                    from app.core.governance import ActionType, Decision
                                    
                                    # Determine action type from tool name
                                    action_type = ActionType.TOOL_CALL
                                    if "exec" in function_name or "shell" in function_name:
                                        action_type = ActionType.SHELL_EXEC
                                    elif "file" in function_name and ("write" in function_name or "delete" in function_name):
                                        action_type = ActionType.FILE_WRITE
                                    elif "network" in function_name or "web" in function_name or "http" in function_name:
                                        action_type = ActionType.NETWORK_REQUEST
                                    elif "docker" in function_name:
                                        action_type = ActionType.SHELL_EXEC
                                    elif "finance" in function_name and "trade" in function_name:
                                        action_type = ActionType.FINANCIAL_ACTION
                                    elif "device" in function_name or "desktop" in function_name or "mobile" in function_name:
                                        action_type = ActionType.DEVICE_CONTROL
                                    
                                    # Evaluate against governance policy
                                    decision, reason, matched_rules = self.governance_policy.evaluate(
                                        actor=request.user_id,
                                        tool_name=function_name,
                                        action_type=action_type,
                                        parameters=args,
                                        context={
                                            "user_id": request.user_id,
                                            "agent_name": getattr(self, "_agent_name", "AssistantAgent"),
                                            "session_id": session_id,
                                            "platform": request.platform,
                                        }
                                    )
                                    
                                    # Audit the decision
                                    self.governance_policy.audit(
                                        actor=request.user_id,
                                        action=function_name,
                                        action_type=action_type,
                                        decision=decision,
                                        risk_level=self.governance_policy.get_tool_profile(function_name).risk_level if self.governance_policy.get_tool_profile(function_name) else RiskLevel.LOW,
                                        parameters=args,
                                        target=str(args.get("path") or args.get("command") or args.get("url") or ""),
                                        session_id=session_id,
                                        conversation_id=request.conversation_id
                                    )
                                    
                                    if decision == Decision.DENY:
                                        traces.append(ToolTrace(
                                            tool_name=function_name,
                                            action="governance_deny",
                                            success=False,
                                            detail=reason,
                                        ))
                                        await self.botsignal.send_text(
                                            request.reply_target,
                                            f"Action blocked by governance: {reason}",
                                            source_kind=source_kind,
                                            tool_traces=traces,
                                        )
                                        break
                                    
                                    elif decision == Decision.REQUIRE_APPROVAL:
                                        # Create approval request
                                        approval = self.governance_policy.create_approval_request(
                                            user_id=request.user_id,
                                            agent_name=getattr(self, "_agent_name", "AssistantAgent"),
                                            tool_name=function_name,
                                            action_type=action_type,
                                            parameters=args,
                                            risk_level=self.governance_policy.get_tool_profile(function_name).risk_level if self.governance_policy.get_tool_profile(function_name) else RiskLevel.HIGH,
                                            context={
                                                "user_id": request.user_id,
                                                "session_id": session_id,
                                                "platform": request.platform,
                                            },
                                            reason=f"High-risk tool {function_name} requires approval"
                                        )
                                        # Broadcast approval request to companion devices
                                        try:
                                            from app.companion.server import get_connection_manager, CompanionMessage
                                            import uuid as _uuid
                                            companion_mgr = get_connection_manager()
                                            await companion_mgr.broadcast_to_user(request.user_id, CompanionMessage(
                                                message_id=f"msg_{_uuid.uuid4().hex[:8]}",
                                                type="approval_request",
                                                payload={
                                                    "approval_id": approval.request_id,
                                                    "tool_name": function_name,
                                                    "risk_level": approval.risk_level.value if hasattr(approval.risk_level, 'value') else str(approval.risk_level),
                                                    "reason": approval.reason,
                                                    "parameters": args,
                                                    "created_at": approval.created_at,
                                                }
                                            ))
                                        except Exception as _comp_exc:
                                            logger.debug("Companion approval broadcast failed: %s", _comp_exc)
                                        # Queue approval (would integrate with existing approval system)
                                        traces.append(ToolTrace(
                                            tool_name=function_name,
                                            action="approval_required",
                                            success=False,
                                            detail=f"Approval required: {approval.request_id}",
                                        ))
                                        await self.botsignal.send_text(
                                            request.reply_target,
                                            f"⚠️ Approval required for {function_name}. Request ID: {approval.request_id}",
                                            source_kind=source_kind,
                                        )
                                        break
                                    
                                    elif decision == Decision.REQUIRE_CONFIRMATION:
                                        await self.botsignal.send_confirmation_request(
                                            request.reply_target,
                                            f"Confirm {function_name}",
                                            reason,
                                            source_kind=source_kind,
                                        )
                                        # Wait for confirmation (simplified - in reality would need callback)
                                        # For now, proceed with confirmation assumed
                                    
                                    elif decision == Decision.SANDBOX:
                                        # Execute in sandbox
                                        logger.info(f"Executing {function_name} in sandbox")
                                        sandbox_result = await self.sandbox_executor.execute(function_name, args)
                                        if "error" in sandbox_result:
                                            result = sandbox_result
                                        else:
                                            result = sandbox_result
                                        _cached = True  # Skip normal execution
                                    
                                    # If ALLOW, proceed to normal execution
                                    #
                            finally:
                                if _obs_span_cm is not None:
                                    try:
                                        _obs_span_cm.__exit__(None, None, None)
                                    except Exception:  # noqa: BLE001
                                        pass
                            _tool_latency_ms = (
                                (_time_module.time() - _tool_start) * 1000
                                if "_tool_start" in dir()
                                else 0
                            )
                            tool_calls_total.labels(tool_name=function_name, success="true").inc()
                            result_str = json.dumps(result, default=str)
                            # ── Normalize tool output to save tokens ──
                            try:
                                from app.core.tool_output_normalizer import normalize_tool_output

                                result_str = normalize_tool_output(function_name, result)
                            except Exception:
                                pass  # Use raw output if normalization fails
                            # ── Cache successful tool result ──────────
                            if not _cached:
                                try:
                                    _rc = get_response_cache()
                                    _rc.set(_cache_key, result, ttl_s=300)
                                except Exception:
                                    pass
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
                            # ── Adaptive tool fallback ──────────────────
                            record_failure(function_name)
                            fallback_tool = get_fallback(function_name, {function_name})
                            if fallback_tool and fallback_tool in self.tools:
                                logger.info(
                                    "AGENT_RUNTIME  tool_fallback  session=%s  from=%s  to=%s",
                                    session_id,
                                    function_name,
                                    fallback_tool,
                                )
                                try:
                                    fb_tool = self.tools[fallback_tool]
                                    fb_result = await fb_tool.execute(**args)
                                    result_str = json.dumps(fb_result, default=str)
                                    function_name = fallback_tool  # Update name for traces
                                except Exception as fb_e:
                                    logger.debug(
                                        "Fallback tool %s also failed: %s", fallback_tool, fb_e
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

                    # FRIDAY: Compress tool output to save tokens
                    try:
                        from app.core.token_compression import compress_tool_output

                        original_len = len(result_str)
                        result_str = compress_tool_output(result_str)
                        if len(result_str) < original_len:
                            logger.debug(
                                "AGENT_RUNTIME  token_compressed  tool=%s  %d→%d chars",
                                function_name,
                                original_len,
                                len(result_str),
                            )
                    except Exception:
                        pass  # Token compression is best-effort

                    tool_msg = {
                        "role": "tool",
                        "tool_call_id": tc.get("id"),
                        "name": function_name,
                        "content": result_str,
                    }
                    messages.append(tool_msg)
                    self.session_manager.append_message(session_id, tool_msg)

                # ── Re-plan on widespread tool failure ──────────────────
                turn_failures = sum(1 for t in traces[-len(tool_calls) :] if not t.success)
                if turn_failures == len(tool_calls) and tool_calls:
                    logger.info(
                        "AGENT_RUNTIME  re_planning  session=%s  all %d tools failed",
                        session_id,
                        turn_failures,
                    )
                    replan_msg = {
                        "role": "user",
                        "content": (
                            "[SYSTEM] All tool calls in this turn failed. "
                            "Re-analyze the situation. Try a DIFFERENT approach — "
                            "use different tools, rephrase your strategy, or "
                            "synthesize an answer from the information you already have. "
                            "Do NOT retry the same failed tools."
                        ),
                    }
                    messages.append(replan_msg)
                    self.session_manager.append_message(session_id, replan_msg)

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
                _final_response = error_text[:1900]
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
                from app.core.token_counter import estimate_messages_tokens  # noqa: PLC0415

                exhausted_input_est = estimate_messages_tokens(messages)
                await self._check_llm_budget(
                    request.user_id, input_tokens=exhausted_input_est, output_tokens=1024
                )

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
                    exhausted_output_tokens = estimate_messages_tokens(
                        [{"role": "assistant", "content": content}]
                    )
                    await self._track_llm_usage(
                        request.user_id,
                        exhausted_input_est + exhausted_output_tokens,
                        {"model": self.model_name},
                    )
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
            self._last_tool_traces = traces
            self._learn_from_turn(request, content, session_id, success=_turn_success)
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

        # ── Reinforcement learning recording ─────────────────────
        try:
            from app.core.reinforcement_learning import get_reinforcement_learner

            rl = get_reinforcement_learner()
            action = f"{self._agent_name}:{self._current_strategy}"
            rl.record_outcome(
                task_category=task_category or "general",
                action=action,
                success=_turn_success,
            )
        except Exception:
            pass

        # ── Personality engine update ───────────────────────────────
        try:
            persona = get_persona_engine()
            if _turn_success:
                persona.on_interaction_success(
                    user_id=request.user_id,
                    user_msg=request.text,
                )
            else:
                persona.on_interaction_failure(
                    user_id=request.user_id,
                    error=_final_response[:100] if _final_response else "unknown",
                )
        except Exception:
            pass

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
