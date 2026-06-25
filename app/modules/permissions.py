"""Permission_Broker for the Modular Extension Platform.

Layers a trust-level default-grant table (assumption A3) over the existing
``PolicyEngine`` (``app/core/policy.py``). The broker evaluates the permissions a
module declares in its manifest against the default grant for the module's trust
level, applying deny-by-default semantics: only requested permissions that fall
within the trust level's grant are granted, and every other requested permission
is routed to pending operator approval.

This module currently implements ``DEFAULT_GRANTS``, ``evaluate_module``
(task 6.1 / requirements 5.1, 5.2), and the operator approval workflow
(``is_pending_approval``, ``approve``, ``deny`` — task 6.2 / requirements 5.6,
5.7, 5.8, 13.4, 13.5). Runtime tool gating (``evaluate_tool`` — requirements
8.4, 8.5, 8.6) and the pure sandbox-backend selection function
(``sandbox_backend_for`` — requirements 5.3, 5.4, 5.5) are added by task 6.3.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.audit import AuditEvent
from app.core.policy import PolicyDecision
from app.core.sandbox_manager import SandboxBackend
from app.modules.models import BrokerDecision

if TYPE_CHECKING:
    from app.core.audit import ActionLogger
    from app.core.policy import PolicyEngine
    from app.modules.models import ModuleRecord
    from app.tools.base import BaseTool

logger = logging.getLogger(__name__)

# Wildcard token: a trust level whose grant contains it may receive any
# requested permission.
_WILDCARD = "*"

# Default permission grants per trust level (A3). ``system`` is fully trusted,
# ``workspace`` receives a curated set, and ``community`` runs at least privilege.
# Any requested permission outside a level's grant is withheld and routed to
# pending operator approval (Req 5.1, 5.2).
DEFAULT_GRANTS: dict[str, frozenset[str]] = {
    "system": frozenset({_WILDCARD}),
    "workspace": frozenset({"camera.read", "notify.operator", "fs.read", "net.read"}),
    "community": frozenset({"notify.operator"}),
}


class PermissionBroker:
    """Evaluate module permissions against trust-level default grants.

    Built on the existing ``PolicyEngine`` and ``ActionLogger``. The broker holds
    no opinion about a module beyond what its manifest declares: it grants only
    permissions within the trust level's default grant and withholds the rest for
    operator approval (deny-by-default).
    """

    def __init__(self, policy: PolicyEngine, audit: ActionLogger) -> None:
        self._policy = policy
        self._audit = audit
        # Permissions still awaiting an operator decision, keyed by module_id.
        # Populated by ``evaluate_module`` and resolved by the approval workflow
        # (task 6.2).
        self._pending: dict[str, set[str]] = {}
        # Elevated permissions an operator has explicitly approved, keyed by
        # module_id. Populated by ``approve`` and consulted by runtime tool
        # gating (task 6.3).
        self._granted: dict[str, set[str]] = {}

    @staticmethod
    def _grant_for(trust_level: str) -> frozenset[str]:
        """Return the default permission grant for a trust level.

        Unknown trust levels receive the empty grant (deny-by-default).
        """
        return DEFAULT_GRANTS.get(trust_level, frozenset())

    @classmethod
    def _is_granted(cls, permission: str, grant: frozenset[str]) -> bool:
        """True when ``permission`` falls within ``grant`` (wildcard-aware)."""
        return _WILDCARD in grant or permission in grant

    def evaluate_module(self, record: ModuleRecord) -> BrokerDecision:
        """Evaluate a module's requested permissions against its trust level.

        Deny-by-default: only the permissions listed in ``required_permissions``
        that fall within the trust level's ``DEFAULT_GRANTS`` are granted. Every
        other requested permission is routed to pending operator approval. Any
        permission not listed in ``required_permissions`` is never granted
        (Req 5.1, 5.2).
        """
        grant = self._grant_for(record.trust_level)

        granted: list[str] = []
        pending: list[str] = []
        seen: set[str] = set()
        for permission in record.manifest.required_permissions:
            if permission in seen:
                continue
            seen.add(permission)
            if self._is_granted(permission, grant):
                granted.append(permission)
            else:
                pending.append(permission)

        if pending:
            self._pending[record.module_id] = set(pending)
        else:
            self._pending.pop(record.module_id, None)

        logger.debug(
            "Evaluated module %s (trust=%s): granted=%s pending=%s",
            record.module_id,
            record.trust_level,
            granted,
            pending,
        )
        return BrokerDecision(granted=granted, pending=pending)

    def is_pending_approval(self, module_id: str) -> bool:
        """Return True while ``module_id`` awaits an operator approval decision.

        The Module_Platform keeps a module disabled until every pending elevated
        permission has been approved or denied (Req 5.6).
        """
        return bool(self._pending.get(module_id))

    def approve(self, module_id: str, permission: str, operator: str) -> None:
        """Operator approves a pending elevated-permission request.

        Records the approval request and the operator's decision through the
        ``ActionLogger``, grants ``permission`` to the module, and clears it from
        the pending set so the module becomes eligible to be enabled
        (Req 5.7, 13.4, 13.5).
        """
        self._record_request(module_id, permission)
        self._clear_pending(module_id, permission)
        self._granted.setdefault(module_id, set()).add(permission)
        logger.debug(
            "Operator %s approved permission %s for module %s",
            operator,
            permission,
            module_id,
        )
        self._record_decision(module_id, permission, operator, approved=True)

    def deny(self, module_id: str, permission: str, operator: str) -> None:
        """Operator denies a pending elevated-permission request.

        Records the approval request and the operator's decision, withholds
        ``permission`` (it is never added to the granted set) so the
        Module_Platform keeps the module disabled, and reports the denied
        permission (Req 5.8, 13.4, 13.5).
        """
        self._record_request(module_id, permission)
        self._clear_pending(module_id, permission)
        self._granted.get(module_id, set()).discard(permission)
        logger.debug(
            "Operator %s denied permission %s for module %s",
            operator,
            permission,
            module_id,
        )
        self._record_decision(module_id, permission, operator, approved=False)

    def _module_granted_set(self, record: ModuleRecord) -> set[str]:
        """Return every permission currently granted to the module.

        Combines the permissions persisted on the record (the trust-level default
        grant computed by ``evaluate_module``) with any elevated permissions an
        operator has explicitly approved for this module (``approve``).
        """
        granted: set[str] = set(record.granted_permissions)
        granted |= self._granted.get(record.module_id, set())
        return granted

    @staticmethod
    def _tool_permissions(tool: BaseTool) -> set[str]:
        """Return the permissions a tool declares it requires (capability-aware)."""
        get_caps = getattr(tool, "get_capabilities", None)
        if not callable(get_caps):
            return set()
        try:
            capability = get_caps()
        except Exception as exc:  # pragma: no cover - defensive, tool-supplied code
            logger.debug("Tool capability lookup failed: %s", exc)
            return set()
        return set(getattr(capability, "required_permissions", []) or [])

    def evaluate_tool(self, record: ModuleRecord, tool: BaseTool) -> PolicyDecision:
        """Runtime gate evaluated before a module tool executes (Req 8.4-8.6).

        Delegates to ``PolicyEngine.evaluate`` and intersects the verdict with the
        module's granted set: a tool may only run if every permission it requires
        has been granted to the owning module. The combined decision is:

        - **deny** when the tool requires a permission the module was not granted,
          or when the policy engine itself denies — the tool is blocked, the
          module's state is unchanged, and the missing permissions are reported
          (Req 8.6);
        - **requires-confirmation** when the module grants every required
          permission but the policy engine asks for operator confirmation
          (Req 8.5);
        - **allow** only when both the policy engine allows and the module grants
          every required permission (Req 8.4).
        """
        decision = self._policy.evaluate(tool)
        granted = self._module_granted_set(record)
        required = self._tool_permissions(tool)
        module_missing = sorted(
            permission
            for permission in required
            if not self._is_granted(permission, frozenset(granted))
        )

        policy_denied = not decision.allowed and not decision.requires_confirmation
        if module_missing or policy_denied:
            missing = sorted(set(module_missing) | set(decision.permissions_missing))
            if module_missing:
                reason = "Module not granted required permissions"
            else:
                reason = decision.reason or "Tool denied by policy"
            logger.debug(
                "Tool %s denied for module %s: missing=%s",
                getattr(tool, "get_name", lambda: "unknown")(),
                record.module_id,
                missing,
            )
            return PolicyDecision(
                allowed=False,
                reason=reason,
                permissions_missing=missing,
            )

        return decision

    def _clear_pending(self, module_id: str, permission: str) -> None:
        """Remove a resolved ``permission`` from the module's pending set."""
        pending = self._pending.get(module_id)
        if pending is None:
            return
        pending.discard(permission)
        if not pending:
            self._pending.pop(module_id, None)

    def _record_request(self, module_id: str, permission: str) -> None:
        """Audit an elevated-permission approval request (Req 13.4)."""
        self._audit.record(
            AuditEvent(
                kind="module_permission",
                action="approval_request",
                success=True,
                detail=(
                    f"Module {module_id} requested elevated permission {permission}"
                ),
                metadata={"module_id": module_id, "permission": permission},
            )
        )

    def _record_decision(
        self, module_id: str, permission: str, operator: str, *, approved: bool
    ) -> None:
        """Audit an operator's approve/deny decision (Req 13.5)."""
        decision = "approved" if approved else "denied"
        self._audit.record(
            AuditEvent(
                kind="module_permission",
                action=decision,
                success=True,
                detail=(
                    f"Operator {operator} {decision} elevated permission "
                    f"{permission} for module {module_id}"
                ),
                metadata={
                    "module_id": module_id,
                    "permission": permission,
                    "operator": operator,
                    "decision": decision,
                },
            )
        )


def sandbox_backend_for(trust_level: str, docker_available: bool) -> SandboxBackend:
    """Select the sandbox backend for a module's trust level (Req 5.3-5.5).

    Pure selection function with no side effects:

    - ``community`` runs under Docker when available, otherwise falls back to a
      subprocess sandbox, so a community module never runs unsandboxed (Req 5.5);
    - ``workspace`` runs in a subprocess sandbox (Req 5.4);
    - ``system`` (and any other/unknown level) runs on the host with no sandbox,
      so a system module is never forced into Docker (Req 5.3).
    """
    if trust_level == "community":
        return SandboxBackend.DOCKER if docker_available else SandboxBackend.SUBPROCESS
    if trust_level == "workspace":
        return SandboxBackend.SUBPROCESS
    return SandboxBackend.NONE  # system
