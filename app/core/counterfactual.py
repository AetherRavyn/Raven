"""Counterfactual Engine — "What if" simulation before high-risk actions.

Simulates possible outcomes before committing to irreversible actions.
Generates best-case, worst-case, and likely scenarios with risk scores.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Recommendation(str, Enum):
    PROCEED = "proceed"
    PROCEED_WITH_CAUTION = "proceed_with_caution"
    SEEK_APPROVAL = "seek_approval"
    ABORT = "abort"


@dataclass(slots=True)
class Scenario:
    """A possible outcome of an action."""

    label: str          # "best_case", "worst_case", "likely"
    description: str
    probability: float  # 0.0 to 1.0
    impact: str         # Description of impact
    reversible: bool = True


@dataclass(slots=True)
class SimulationResult:
    """Result of a counterfactual simulation."""

    action: str
    risk_level: str = RiskLevel.LOW.value
    confidence: float = 0.5
    recommendation: str = Recommendation.PROCEED.value
    scenarios: list[Scenario] = field(default_factory=list)
    mitigations: list[str] = field(default_factory=list)
    reasoning: str = ""

    @property
    def should_proceed(self) -> bool:
        return self.recommendation in (
            Recommendation.PROCEED.value,
            Recommendation.PROCEED_WITH_CAUTION.value,
        )


# ── Risk classification rules ──────────────────────────────────────

_DESTRUCTIVE_PATTERNS: list[tuple[str, str]] = [
    ("rm -rf", "Recursive file deletion"),
    ("drop table", "Database table deletion"),
    ("drop database", "Database deletion"),
    ("truncate", "Data truncation"),
    ("delete from", "Mass data deletion"),
    ("format", "Disk formatting"),
    ("mkfs", "Filesystem creation"),
    ("dd if=", "Raw disk write"),
    ("shutdown", "System shutdown"),
    ("reboot", "System reboot"),
    ("kill -9", "Force kill process"),
    ("iptables -F", "Firewall flush"),
]

_EXTERNAL_PATTERNS: list[tuple[str, str]] = [
    ("curl -X POST", "External HTTP POST"),
    ("curl -X DELETE", "External HTTP DELETE"),
    ("git push --force", "Force push to remote"),
    ("npm publish", "Package publication"),
    ("pip install", "Package installation"),
    ("docker push", "Container publication"),
    ("tweet", "Social media post"),
    ("send_email", "Email transmission"),
    ("send_message", "Message transmission"),
]


class CounterfactualEngine:
    """Simulates "what if" scenarios before committing to actions.

    Used by the SecurityGuard and runtime to evaluate high-risk
    tool invocations before execution.
    """

    def simulate(
        self,
        action: str,
        context: dict[str, Any] | None = None,
        tool_name: str = "",
    ) -> SimulationResult:
        """Run a mental simulation of an action's consequences.

        Analyzes the action for destructive patterns, generates
        best/worst/likely scenarios, and returns a recommendation.
        """
        context = context or {}

        # Classify risk
        risk_level, risk_reasons = self._classify_risk(action, tool_name)

        # Generate scenarios
        scenarios = self._generate_scenarios(action, risk_level, risk_reasons)

        # Determine mitigations
        mitigations = self._suggest_mitigations(action, risk_level)

        # Make recommendation
        recommendation = self._recommend(risk_level, scenarios)

        # Calculate confidence
        confidence = self._calculate_confidence(risk_level, scenarios)

        # Build reasoning
        reasoning_parts = [f"Action: {action[:200]}"]
        if risk_reasons:
            reasoning_parts.append(f"Risks detected: {', '.join(risk_reasons)}")
        reasoning_parts.append(f"Risk level: {risk_level}")
        reasoning_parts.append(f"Recommendation: {recommendation}")

        return SimulationResult(
            action=action,
            risk_level=risk_level,
            confidence=confidence,
            recommendation=recommendation,
            scenarios=scenarios,
            mitigations=mitigations,
            reasoning="\n".join(reasoning_parts),
        )

    # ── Risk Classification ─────────────────────────────────────────

    def _classify_risk(
        self, action: str, tool_name: str
    ) -> tuple[str, list[str]]:
        """Classify the risk level of an action."""
        action_lower = action.lower()
        reasons: list[str] = []

        # Check destructive patterns
        for pattern, description in _DESTRUCTIVE_PATTERNS:
            if pattern in action_lower:
                reasons.append(description)

        if reasons:
            return RiskLevel.CRITICAL.value, reasons

        # Check external side-effect patterns
        for pattern, description in _EXTERNAL_PATTERNS:
            if pattern in action_lower:
                reasons.append(description)

        if reasons:
            return RiskLevel.HIGH.value, reasons

        # Check tool risk
        high_risk_tools = {
            "system_execute", "bash_execute", "sandbox_exec",
            "git_ops", "file_operations", "agency_delegation",
        }
        if tool_name in high_risk_tools:
            return RiskLevel.MEDIUM.value, [f"Tool '{tool_name}' has elevated risk"]

        return RiskLevel.LOW.value, []

    # ── Scenario Generation ─────────────────────────────────────────

    def _generate_scenarios(
        self, action: str, risk_level: str, risks: list[str]
    ) -> list[Scenario]:
        """Generate best/worst/likely scenarios."""
        scenarios: list[Scenario] = []

        if risk_level == RiskLevel.LOW.value:
            scenarios.append(Scenario(
                label="likely",
                description="Action completes successfully with no side effects.",
                probability=0.95,
                impact="Minimal",
                reversible=True,
            ))
            return scenarios

        # Best case
        scenarios.append(Scenario(
            label="best_case",
            description="Action completes successfully. All changes are as intended.",
            probability=0.6 if risk_level == RiskLevel.MEDIUM.value else 0.4,
            impact="Positive — task accomplished",
            reversible=True,
        ))

        # Worst case
        is_destructive = risk_level == RiskLevel.CRITICAL.value
        scenarios.append(Scenario(
            label="worst_case",
            description=(
                f"Action causes: {'; '.join(risks[:3])}. "
                f"{'Data loss may be permanent.' if is_destructive else 'May require manual cleanup.'}"
            ),
            probability=0.1 if risk_level == RiskLevel.MEDIUM.value else 0.3,
            impact="Severe" if is_destructive else "Moderate",
            reversible=not is_destructive,
        ))

        # Likely case
        scenarios.append(Scenario(
            label="likely",
            description="Action completes but may have unintended side effects.",
            probability=0.3,
            impact="Moderate — may need review",
            reversible=True,
        ))

        return scenarios

    # ── Mitigations ─────────────────────────────────────────────────

    def _suggest_mitigations(
        self, action: str, risk_level: str
    ) -> list[str]:
        """Suggest risk mitigations."""
        mitigations: list[str] = []
        action_lower = action.lower()

        if risk_level in (RiskLevel.HIGH.value, RiskLevel.CRITICAL.value):
            mitigations.append("Create a backup before executing")
            mitigations.append("Execute in sandbox/container if possible")

        if "rm" in action_lower or "delete" in action_lower:
            mitigations.append("Verify file/directory paths before deletion")
            mitigations.append("Use --dry-run flag if available")

        if "git push" in action_lower:
            mitigations.append("Review diff before pushing")
            mitigations.append("Push to a feature branch first")

        if "deploy" in action_lower or "publish" in action_lower:
            mitigations.append("Deploy to staging first")
            mitigations.append("Ensure rollback procedure is ready")

        if not mitigations and risk_level != RiskLevel.LOW.value:
            mitigations.append("Review the action carefully before proceeding")

        return mitigations

    # ── Recommendation ──────────────────────────────────────────────

    def _recommend(
        self, risk_level: str, scenarios: list[Scenario]
    ) -> str:
        """Make a recommendation based on risk and scenarios."""
        if risk_level == RiskLevel.CRITICAL.value:
            return Recommendation.SEEK_APPROVAL.value

        if risk_level == RiskLevel.HIGH.value:
            worst = next((s for s in scenarios if s.label == "worst_case"), None)
            if worst and not worst.reversible:
                return Recommendation.SEEK_APPROVAL.value
            return Recommendation.PROCEED_WITH_CAUTION.value

        if risk_level == RiskLevel.MEDIUM.value:
            return Recommendation.PROCEED_WITH_CAUTION.value

        return Recommendation.PROCEED.value

    def _calculate_confidence(
        self, risk_level: str, scenarios: list[Scenario]
    ) -> float:
        """Calculate confidence in the simulation."""
        base = {
            RiskLevel.LOW.value: 0.9,
            RiskLevel.MEDIUM.value: 0.7,
            RiskLevel.HIGH.value: 0.5,
            RiskLevel.CRITICAL.value: 0.3,
        }.get(risk_level, 0.5)
        return base


# ── Module singleton ────────────────────────────────────────────────

_GLOBAL_ENGINE = CounterfactualEngine()


def get_counterfactual_engine() -> CounterfactualEngine:
    global _GLOBAL_ENGINE
    if _GLOBAL_ENGINE is None:
        _GLOBAL_ENGINE = CounterfactualEngine()
    return _GLOBAL_ENGINE


def reset_counterfactual_engine_for_tests() -> None:
    """Drop the cached singleton.  Tests use this between
    cases so the module state doesn't leak across tests."""
    global _GLOBAL_ENGINE
    _GLOBAL_ENGINE = None
