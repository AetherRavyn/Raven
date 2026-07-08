"""Safety & Governance Engine — NeMoClaw-inspired deny-by-default policy system.

Provides:
- Deny-by-default policy engine with explicit allow rules
- Per-tool risk classification and approval workflows
- Immutable audit log for all decisions and actions
- Sandbox execution for risky tools
- Evaluation harness for tool reliability and safety
- Trust tiers for agents and tools
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Risk levels for tools and actions."""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ActionType(Enum):
    """Types of actions that can be governed."""
    TOOL_CALL = "tool_call"
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    SHELL_EXEC = "shell_exec"
    NETWORK_REQUEST = "network_request"
    DATABASE_QUERY = "database_query"
    MESSAGE_SEND = "message_send"
    DEVICE_CONTROL = "device_control"
    FINANCIAL_ACTION = "financial_action"
    SYSTEM_CONFIG = "system_config"
    USER_DATA_ACCESS = "user_data_access"
    AGENT_DELEGATION = "agent_delegation"


class Decision(Enum):
    """Policy decision outcomes."""
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"
    REQUIRE_CONFIRMATION = "require_confirmation"
    SANDBOX = "sandbox"


@dataclass(slots=True)
class ToolRiskProfile:
    """Risk profile for a tool."""
    tool_name: str
    risk_level: RiskLevel
    action_types: list[ActionType]
    requires_approval: bool = False
    requires_confirmation: bool = False
    sandbox_required: bool = False
    max_frequency_per_minute: int | None = None
    allowed_users: list[str] | None = None  # None = all
    allowed_agents: list[str] | None = None  # None = all
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PolicyRule:
    """A policy rule for governance."""
    rule_id: str
    name: str
    description: str
    conditions: dict[str, Any]  # Conditions that trigger this rule
    decision: Decision
    priority: int = 100  # Lower = higher priority
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ApprovalRequest:
    """Request for human approval."""
    request_id: str
    user_id: str
    agent_name: str
    tool_name: str
    action_type: ActionType
    parameters: dict[str, Any]
    risk_level: RiskLevel
    context: dict[str, Any]
    reason: str
    status: str = "pending"  # pending, approved, denied, expired
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved_at: str | None = None
    resolved_by: str | None = None
    resolution_reason: str = ""


@dataclass(slots=True)
class AuditEvent:
    """Immutable audit log entry."""
    event_id: str
    timestamp: str
    actor: str  # user_id or agent_name
    action: str
    action_type: ActionType
    target: str | None
    decision: Decision
    risk_level: RiskLevel
    parameters: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None
    approval_request_id: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None
    hash_chain: str = ""  # Hash of previous event for immutability


class PolicyEngine:
    """Deny-by-default policy engine with explicit allow rules."""
    
    def __init__(self, workspace_dir: str = "workspace") -> None:
        self._dir = Path(workspace_dir) / "governance"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._rules_file = self._dir / "policy_rules.json"
        self._tool_profiles_file = self._dir / "tool_profiles.json"
        self._audit_file = self._dir / "audit_log.jsonl"
        self._approvals_file = self._dir / "approvals.jsonl"
        
        self._rules: list[PolicyRule] = []
        self._tool_profiles: dict[str, ToolRiskProfile] = {}
        self._last_audit_hash = ""
        
        self._load()
        self._initialize_default_policies()
    
    def _load(self) -> None:
        """Load policies and tool profiles from disk."""
        try:
            if self._rules_file.exists():
                data = json.loads(self._rules_file.read_text(encoding="utf-8"))
                self._rules = [PolicyRule(**r) for r in data]
        except Exception as e:
            logger.warning("Failed to load policy rules: %s", e)
        
        try:
            if self._tool_profiles_file.exists():
                data = json.loads(self._tool_profiles_file.read_text(encoding="utf-8"))
                self._tool_profiles = {
                    k: ToolRiskProfile(**v) for k, v in data.items()
                }
        except Exception as e:
            logger.warning("Failed to load tool profiles: %s", e)
    
    def _save_rules(self) -> None:
        """Save policy rules to disk."""
        try:
            self._rules_file.write_text(
                json.dumps([asdict(r) for r in self._rules], indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error("Failed to save policy rules: %s", e)
    
    def _save_tool_profiles(self) -> None:
        """Save tool profiles to disk."""
        try:
            self._tool_profiles_file.write_text(
                json.dumps({k: asdict(v) for k, v in self._tool_profiles.items()}, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error("Failed to save tool profiles: %s", e)
    
    def _initialize_default_policies(self) -> None:
        """Initialize default deny-by-default policies."""
        # Check if already initialized
        if self._rules or self._tool_profiles:
            return
        
        # Default tool risk profiles
        default_profiles = {
            # Low risk - read-only operations
            "filetool:read": ToolRiskProfile(
                tool_name="filetool:read",
                risk_level=RiskLevel.LOW,
                action_types=[ActionType.FILE_READ],
                requires_approval=False
            ),
            "websearch": ToolRiskProfile(
                tool_name="websearch",
                risk_level=RiskLevel.LOW,
                action_types=[ActionType.NETWORK_REQUEST],
                requires_approval=False
            ),
            "webfetch": ToolRiskProfile(
                tool_name="webfetch",
                risk_level=RiskLevel.LOW,
                action_types=[ActionType.NETWORK_REQUEST],
                requires_approval=False
            ),
            "weathertool": ToolRiskProfile(
                tool_name="weathertool",
                risk_level=RiskLevel.LOW,
                action_types=[ActionType.NETWORK_REQUEST],
                requires_approval=False
            ),
            
            # Medium risk - write operations, non-destructive
            "filetool:write": ToolRiskProfile(
                tool_name="filetool:write",
                risk_level=RiskLevel.MEDIUM,
                action_types=[ActionType.FILE_WRITE],
                requires_confirmation=True
            ),
            "filetool:list": ToolRiskProfile(
                tool_name="filetool:list",
                risk_level=RiskLevel.LOW,
                action_types=[ActionType.FILE_READ],
            ),
            "gittool:status": ToolRiskProfile(
                tool_name="gittool:status",
                risk_level=RiskLevel.LOW,
                action_types=[ActionType.FILE_READ],
            ),
            "gittool:diff": ToolRiskProfile(
                tool_name="gittool:diff",
                risk_level=RiskLevel.LOW,
                action_types=[ActionType.FILE_READ],
            ),
            "calendartool:read": ToolRiskProfile(
                tool_name="calendartool:read",
                risk_level=RiskLevel.LOW,
                action_types=[ActionType.USER_DATA_ACCESS],
            ),
            
            # High risk - modifications, executions
            "exectool": ToolRiskProfile(
                tool_name="exectool",
                risk_level=RiskLevel.HIGH,
                action_types=[ActionType.SHELL_EXEC],
                requires_approval=True,
                sandbox_required=True
            ),
            "dockertool": ToolRiskProfile(
                tool_name="dockertool",
                risk_level=RiskLevel.HIGH,
                action_types=[ActionType.SHELL_EXEC, ActionType.SYSTEM_CONFIG],
                requires_approval=True,
                sandbox_required=True
            ),
            "filetool:delete": ToolRiskProfile(
                tool_name="filetool:delete",
                risk_level=RiskLevel.HIGH,
                action_types=[ActionType.FILE_WRITE],
                requires_approval=True
            ),
            "gittool:push": ToolRiskProfile(
                tool_name="gittool:push",
                risk_level=RiskLevel.MEDIUM,
                action_types=[ActionType.NETWORK_REQUEST],
                requires_confirmation=True
            ),
            "calendartool:write": ToolRiskProfile(
                tool_name="calendartool:write",
                risk_level=RiskLevel.MEDIUM,
                action_types=[ActionType.USER_DATA_ACCESS],
                requires_confirmation=True
            ),
            "mailtool:send": ToolRiskProfile(
                tool_name="mailtool:send",
                risk_level=RiskLevel.MEDIUM,
                action_types=[ActionType.MESSAGE_SEND],
                requires_confirmation=True
            ),
            "messagingtool:send": ToolRiskProfile(
                tool_name="messagingtool:send",
                risk_level=RiskLevel.MEDIUM,
                action_types=[ActionType.MESSAGE_SEND],
                requires_confirmation=True
            ),
            
            # Critical risk - financial, system config, device control
            "financetool:trade": ToolRiskProfile(
                tool_name="financetool:trade",
                risk_level=RiskLevel.CRITICAL,
                action_types=[ActionType.FINANCIAL_ACTION],
                requires_approval=True
            ),
            "smarthometool:actuate": ToolRiskProfile(
                tool_name="smarthometool:actuate",
                risk_level=RiskLevel.CRITICAL,
                action_types=[ActionType.DEVICE_CONTROL],
                requires_approval=True
            ),
            "elevatedtool": ToolRiskProfile(
                tool_name="elevatedtool",
                risk_level=RiskLevel.CRITICAL,
                action_types=[ActionType.SYSTEM_CONFIG, ActionType.SHELL_EXEC],
                requires_approval=True,
                sandbox_required=True
            ),
            "desktoptool:control": ToolRiskProfile(
                tool_name="desktoptool:control",
                risk_level=RiskLevel.HIGH,
                action_types=[ActionType.DEVICE_CONTROL],
                requires_approval=True,
                sandbox_required=True
            ),
            "mobiletool:control": ToolRiskProfile(
                tool_name="mobiletool:control",
                risk_level=RiskLevel.HIGH,
                action_types=[ActionType.DEVICE_CONTROL],
                requires_approval=True,
                sandbox_required=True
            ),
        }
        
        for profile in default_profiles.values():
            self._tool_profiles[profile.tool_name] = profile
        self._save_tool_profiles()
        
        # Default deny-by-default rules
        default_rules = [
            PolicyRule(
                rule_id="default_deny",
                name="Default Deny",
                description="Deny all actions not explicitly allowed",
                conditions={"default": True},
                decision=Decision.DENY,
                priority=1000
            ),
            PolicyRule(
                rule_id="allow_low_risk",
                name="Allow Low Risk Tools",
                description="Allow low-risk tools without approval",
                conditions={"risk_level": "low", "requires_approval": False},
                decision=Decision.ALLOW,
                priority=100
            ),
            PolicyRule(
                rule_id="confirm_medium_risk",
                name="Confirm Medium Risk",
                description="Require confirmation for medium-risk actions",
                conditions={"risk_level": "medium", "requires_confirmation": True},
                decision=Decision.REQUIRE_CONFIRMATION,
                priority=50
            ),
            PolicyRule(
                rule_id="approve_high_risk",
                name="Approve High Risk",
                description="Require approval for high-risk actions",
                conditions={"risk_level": "high", "requires_approval": True},
                decision=Decision.REQUIRE_APPROVAL,
                priority=10
            ),
            PolicyRule(
                rule_id="approve_critical_risk",
                name="Approve Critical Risk",
                description="Require approval for critical-risk actions",
                conditions={"risk_level": "critical", "requires_approval": True},
                decision=Decision.REQUIRE_APPROVAL,
                priority=5
            ),
            PolicyRule(
                rule_id="sandbox_required",
                name="Sandbox Required",
                description="Run sandboxed tools in isolation",
                conditions={"sandbox_required": True},
                decision=Decision.SANDBOX,
                priority=1
            ),
        ]
        
        self._rules.extend(default_rules)
        self._save_rules()
    
    # ── Tool Profile Management ───────────────────────────────────
    
    def register_tool(self, profile: ToolRiskProfile) -> None:
        """Register or update a tool's risk profile."""
        self._tool_profiles[profile.tool_name] = profile
        self._save_tool_profiles()
    
    def get_tool_profile(self, tool_name: str) -> ToolRiskProfile | None:
        """Get risk profile for a tool."""
        return self._tool_profiles.get(tool_name)
    
    def list_tool_profiles(self) -> list[ToolRiskProfile]:
        """List all registered tool profiles."""
        return list(self._tool_profiles.values())
    
    # ── Policy Rule Management ────────────────────────────────────
    
    def add_rule(self, rule: PolicyRule) -> None:
        """Add a policy rule."""
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority)
        self._save_rules()
    
    def remove_rule(self, rule_id: str) -> bool:
        """Remove a policy rule by ID."""
        for i, rule in enumerate(self._rules):
            if rule.rule_id == rule_id:
                self._rules.pop(i)
                self._save_rules()
                return True
        return False
    
    def get_rules(self) -> list[PolicyRule]:
        """Get all policy rules."""
        return list(self._rules)
    
    # ── Decision Engine ───────────────────────────────────────────
    
    def evaluate(
        self,
        actor: str,
        tool_name: str,
        action_type: ActionType,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None
    ) -> tuple[Decision, str, list[str]]:
        """
        Evaluate an action against policies.
        
        Returns: (decision, reason, matched_rule_ids)
        """
        context = context or {}
        profile = self._tool_profiles.get(tool_name)
        
        if not profile:
            # Unknown tool - default deny
            return Decision.DENY, f"Unknown tool: {tool_name}", ["default_deny"]
        
        # Check frequency limits
        if profile.max_frequency_per_minute:
            # Would check rate limiter here
            pass
        
        # Check user/agent allowlists
        user_id = context.get("user_id", actor)
        if profile.allowed_users and user_id not in profile.allowed_users:
            return Decision.DENY, f"User {user_id} not authorized for {tool_name}", ["user_not_authorized"]
        
        agent_name = context.get("agent_name", actor)
        if profile.allowed_agents and agent_name not in profile.allowed_agents:
            return Decision.DENY, f"Agent {agent_name} not authorized for {tool_name}", ["agent_not_authorized"]
        
        # Build evaluation context
        eval_context = {
            "tool_name": tool_name,
            "action_type": action_type.value,
            "risk_level": profile.risk_level.value,
            "requires_approval": profile.requires_approval,
            "requires_confirmation": profile.requires_confirmation,
            "sandbox_required": profile.sandbox_required,
            **context
        }
        
        # Evaluate rules in priority order
        matched_rules = []
        for rule in self._rules:
            if not rule.enabled:
                continue
            if self._match_conditions(rule.conditions, eval_context):
                matched_rules.append(rule.rule_id)
                return rule.decision, f"Matched rule: {rule.name}", matched_rules
        
        # Default deny
        return Decision.DENY, "No matching allow rule (default deny)", ["default_deny"]
    
    def _match_conditions(self, conditions: dict[str, Any], context: dict[str, Any]) -> bool:
        """Check if conditions match context."""
        for key, expected in conditions.items():
            if key == "default":
                continue  # Special case for default rule
            actual = context.get(key)
            if isinstance(expected, list):
                if actual not in expected:
                    return False
            elif actual != expected:
                return False
        return True
    
    # ── Approval Workflow ─────────────────────────────────────────
    
    def create_approval_request(
        self,
        user_id: str,
        agent_name: str,
        tool_name: str,
        action_type: ActionType,
        parameters: dict[str, Any],
        risk_level: RiskLevel,
        context: dict[str, Any],
        reason: str
    ) -> ApprovalRequest:
        """Create an approval request for human review."""
        request = ApprovalRequest(
            request_id=f"appr_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            agent_name=agent_name,
            tool_name=tool_name,
            action_type=action_type,
            parameters=parameters,
            risk_level=risk_level,
            context=context,
            reason=reason
        )
        
        # Persist
        try:
            with open(self._approvals_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(request), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error("Failed to save approval request: %s", e)
        
        return request
    
    def resolve_approval(
        self,
        request_id: str,
        approved: bool,
        resolved_by: str,
        reason: str = ""
    ) -> ApprovalRequest | None:
        """Resolve an approval request."""
        # Read all requests, find and update
        requests = []
        target = None
        
        try:
            if self._approvals_file.exists():
                for line in self._approvals_file.read_text(encoding="utf-8").strip().splitlines():
                    if line.strip():
                        req = ApprovalRequest(**json.loads(line))
                        if req.request_id == request_id:
                            req.status = "approved" if approved else "denied"
                            req.resolved_at = datetime.now(timezone.utc).isoformat()
                            req.resolved_by = resolved_by
                            req.resolution_reason = reason
                            target = req
                        requests.append(req)
        except Exception as e:
            logger.error("Failed to load approvals: %s", e)
            return None
        
        # Rewrite file
        try:
            with open(self._approvals_file, "w", encoding="utf-8") as f:
                for req in requests:
                    f.write(json.dumps(asdict(req), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error("Failed to save approvals: %s", e)
        
        return target
    
    def get_pending_approvals(self, user_id: str | None = None) -> list[ApprovalRequest]:
        """Get pending approval requests."""
        requests = []
        try:
            if self._approvals_file.exists():
                for line in self._approvals_file.read_text(encoding="utf-8").strip().splitlines():
                    if line.strip():
                        req = ApprovalRequest(**json.loads(line))
                        if req.status == "pending" and (user_id is None or req.user_id == user_id):
                            requests.append(req)
        except Exception as e:
            logger.error("Failed to load approvals: %s", e)
        return requests
    
    # ── Audit Logging ─────────────────────────────────────────────
    
    def audit(
        self,
        actor: str,
        action: str,
        action_type: ActionType,
        decision: Decision,
        risk_level: RiskLevel,
        parameters: dict[str, Any],
        result: dict[str, Any] | None = None,
        error: str | None = None,
        target: str | None = None,
        approval_request_id: str | None = None,
        session_id: str | None = None,
        conversation_id: str | None = None
    ) -> AuditEvent:
        """Record an immutable audit event."""
        # Compute hash chain for immutability
        prev_hash = self._last_audit_hash
        event_data = f"{actor}{action}{action_type.value}{decision.value}{risk_level.value}{json.dumps(parameters, sort_keys=True)}{prev_hash}"
        event_hash = hashlib.sha256(event_data.encode()).hexdigest()
        
        event = AuditEvent(
            event_id=f"audit_{uuid.uuid4().hex[:12]}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            actor=actor,
            action=action,
            action_type=action_type,
            target=target,
            decision=decision,
            risk_level=risk_level,
            parameters=parameters,
            result=result,
            error=error,
            approval_request_id=approval_request_id,
            session_id=session_id,
            conversation_id=conversation_id,
            hash_chain=event_hash
        )
        
        self._last_audit_hash = event_hash
        
        # Persist
        try:
            with open(self._audit_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error("Failed to write audit log: %s", e)
        
        return event
    
    def get_audit_log(
        self,
        actor: str | None = None,
        action_type: ActionType | None = None,
        since: str | None = None,
        limit: int = 100
    ) -> list[AuditEvent]:
        """Query audit log."""
        events = []
        try:
            if self._audit_file.exists():
                lines = self._audit_file.read_text(encoding="utf-8").strip().splitlines()
                for line in reversed(lines):  # Most recent first
                    if not line.strip():
                        continue
                    event = AuditEvent(**json.loads(line))
                    
                    if actor and event.actor != actor:
                        continue
                    if action_type and event.action_type != action_type:
                        continue
                    if since and event.timestamp < since:
                        break  # Logs are chronological
                    
                    events.append(event)
                    if len(events) >= limit:
                        break
        except Exception as e:
            logger.error("Failed to read audit log: %s", e)
        
        return list(reversed(events))  # Return chronological
    
    def verify_audit_integrity(self) -> tuple[bool, list[str]]:
        """Verify audit log hash chain integrity."""
        errors = []
        prev_hash = ""
        
        try:
            if self._audit_file.exists():
                for line_num, line in enumerate(
                    self._audit_file.read_text(encoding="utf-8").strip().splitlines(), 1
                ):
                    if not line.strip():
                        continue
                    event = AuditEvent(**json.loads(line))
                    
                    # Recompute hash
                    event_data = f"{event.actor}{event.action}{event.action_type.value}{event.decision.value}{event.risk_level.value}{json.dumps(event.parameters, sort_keys=True)}{prev_hash}"
                    expected_hash = hashlib.sha256(event_data.encode()).hexdigest()
                    
                    if event.hash_chain != expected_hash:
                        errors.append(f"Line {line_num}: Hash mismatch (event {event.event_id})")
                    
                    prev_hash = event.hash_chain
        except Exception as e:
            errors.append(f"Verification error: {e}")
        
        return len(errors) == 0, errors


class SandboxExecutor:
    """Executes tools in isolated sandbox environments."""
    
    def __init__(self, workspace_dir: str = "workspace") -> None:
        self._dir = Path(workspace_dir) / "sandbox"
        self._dir.mkdir(parents=True, exist_ok=True)
    
    async def execute(
        self,
        tool_name: str,
        parameters: dict[str, Any],
        timeout: int = 60
    ) -> dict[str, Any]:
        """Execute a tool in sandbox. Returns result or error."""
        # This is a simplified implementation
        # In production, would use Docker, gVisor, or similar
        
        sandbox_dir = self._dir / f"{tool_name}_{uuid.uuid4().hex[:8]}"
        sandbox_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # Write parameters
            (sandbox_dir / "input.json").write_text(json.dumps(parameters))
            
            # Execute based on tool type
            if tool_name == "exectool":
                return await self._exec_shell(parameters, sandbox_dir, timeout)
            elif tool_name == "dockertool":
                return await self._exec_docker(parameters, sandbox_dir, timeout)
            else:
                return {"error": f"No sandbox handler for {tool_name}"}
        
        except Exception as e:
            return {"error": str(e)}
        finally:
            # Cleanup (in production, might keep for forensics)
            import shutil
            shutil.rmtree(sandbox_dir, ignore_errors=True)
    
    async def _exec_shell(
        self,
        params: dict[str, Any],
        workdir: Path,
        timeout: int
    ) -> dict[str, Any]:
        """Execute shell command in sandbox."""
        import asyncio
        cmd = params.get("command", "")
        if not cmd:
            return {"error": "No command provided"}
        
        # Security: validate command
        dangerous = ["rm -rf", "mkfs", "dd if=", ":(){ :|:& };:", "chmod 777", "chown root"]
        for d in dangerous:
            if d in cmd:
                return {"error": f"Dangerous command pattern detected: {d}"}
        
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                cwd=workdir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            
            return {
                "returncode": proc.returncode,
                "stdout": stdout.decode()[:10000],
                "stderr": stderr.decode()[:10000]
            }
        except asyncio.TimeoutError:
            return {"error": "Command timed out"}
        except Exception as e:
            return {"error": str(e)}
    
    async def _exec_docker(
        self,
        params: dict[str, Any],
        workdir: Path,
        timeout: int
    ) -> dict[str, Any]:
        """Execute Docker command in sandbox."""
        # Would use docker SDK or CLI with restrictions
        return {"error": "Docker sandbox not fully implemented"}


class EvaluationHarness:
    """Evaluation harness for tool reliability and safety testing."""
    
    def __init__(self, workspace_dir: str = "workspace") -> None:
        self._dir = Path(workspace_dir) / "evaluation"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._results_file = self._dir / "evaluation_results.jsonl"
    
    async def evaluate_tool(
        self,
        tool_name: str,
        test_cases: list[dict[str, Any]],
        expected_outcomes: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """Run evaluation tests for a tool."""
        results = {
            "tool_name": tool_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "test_cases": len(test_cases),
            "passed": 0,
            "failed": 0,
            "errors": [],
            "details": []
        }
        
        for i, test_case in enumerate(test_cases):
            try:
                # Import and execute tool
                # This is simplified - would use actual tool execution
                result = await self._run_tool_test(tool_name, test_case)
                
                passed = True
                if expected_outcomes and i < len(expected_outcomes):
                    expected = expected_outcomes[i]
                    passed = self._compare_results(result, expected)
                
                if passed:
                    results["passed"] += 1
                else:
                    results["failed"] += 1
                    results["errors"].append(f"Test {i}: Output mismatch")
                
                results["details"].append({
                    "test_index": i,
                    "input": test_case,
                    "output": result,
                    "passed": passed
                })
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(f"Test {i}: {str(e)}")
                results["details"].append({
                    "test_index": i,
                    "input": test_case,
                    "error": str(e),
                    "passed": False
                })
        
        # Save results
        try:
            with open(self._results_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(results, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error("Failed to save evaluation results: %s", e)
        
        return results
    
    async def _run_tool_test(self, tool_name: str, test_case: dict[str, Any]) -> dict[str, Any]:
        """Run a single tool test. Placeholder for actual tool execution."""
        # In real implementation, would invoke the actual tool
        return {"status": "not_implemented", "tool": tool_name}
    
    def _compare_results(self, actual: dict[str, Any], expected: dict[str, Any]) -> bool:
        """Compare actual vs expected results."""
        # Simplified comparison
        for key, value in expected.items():
            if key not in actual:
                return False
            if actual[key] != value:
                return False
        return True
    
    def get_evaluation_history(self, tool_name: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """Get evaluation history."""
        results = []
        try:
            if self._results_file.exists():
                lines = self._results_file.read_text(encoding="utf-8").strip().splitlines()
                for line in reversed(lines):
                    if not line.strip():
                        continue
                    result = json.loads(line)
                    if tool_name is None or result.get("tool_name") == tool_name:
                        results.append(result)
                        if len(results) >= limit:
                            break
        except Exception as e:
            logger.error("Failed to load evaluation history: %s", e)
        return list(reversed(results))


# Global instances
_policy_engine: PolicyEngine | None = None
_sandbox_executor: SandboxExecutor | None = None
_evaluation_harness: EvaluationHarness | None = None


def get_policy_engine() -> PolicyEngine:
    """Get global policy engine instance."""
    global _policy_engine
    if _policy_engine is None:
        _policy_engine = PolicyEngine()
    return _policy_engine


def get_sandbox_executor() -> SandboxExecutor:
    """Get global sandbox executor instance."""
    global _sandbox_executor
    if _sandbox_executor is None:
        _sandbox_executor = SandboxExecutor()
    return _sandbox_executor


def get_evaluation_harness() -> EvaluationHarness:
    """Get global evaluation harness instance."""
    global _evaluation_harness
    if _evaluation_harness is None:
        _evaluation_harness = EvaluationHarness()
    return _evaluation_harness