"""Public types for the verifier.

The verifier evaluates whether a :class:`TaskPlan` execution met its
declared success criteria.  It runs deterministic checks first (cheap,
O(1) to O(text length)) and falls back to an LLM-as-judge for soft
criteria.  Reports are structured so callers (the executor, the
replanner, the UI) can act on the verdict without re-parsing text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Severity(str, Enum):
    """How bad is a failed check?

    ``BLOCKING`` means the plan cannot be marked successful.
    ``WARNING`` is logged but does not flip the verdict.
    ``INFO`` is purely diagnostic.
    """

    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


class CheckKind(str, Enum):
    """The kind of check that was run."""

    NON_EMPTY = "non_empty"
    SUBSTRING = "substring"
    REGEX = "regex"
    FILE_EXISTS = "file_exists"
    FILE_WRITTEN = "file_written"
    EXIT_CODE = "exit_code"
    JSON_VALID = "json_valid"
    MARKDOWN_VALID = "markdown_valid"
    URL_REACHABLE = "url_reachable"
    STRUCTURE = "structure"
    LLM_JUDGE = "llm_judge"
    CUSTOM = "custom"


@dataclass(slots=True)
class CheckResult:
    """Result of a single check."""

    name: str
    kind: CheckKind
    passed: bool
    severity: Severity = Severity.BLOCKING
    message: str = ""
    actual: Any = None
    expected: Any = None
    confidence: float = 1.0  # 0..1, used by LLM-as-judge
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "passed": self.passed,
            "severity": self.severity.value,
            "message": self.message,
            "actual": self.actual if _safe_to_serialize(self.actual) else str(self.actual),
            "expected": self.expected,
            "confidence": self.confidence,
            "duration_ms": self.duration_ms,
        }


@dataclass(slots=True)
class VerificationReport:
    """Verdict for one :class:`TaskPlan` execution."""

    plan_id: str
    step_id: str
    passed: bool
    checks: list[CheckResult] = field(default_factory=list)
    blocking_failures: int = 0
    warnings: int = 0
    notes: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_checks(
        cls, plan_id: str, step_id: str, checks: list[CheckResult]
    ) -> "VerificationReport":
        blocking = sum(1 for c in checks if not c.passed and c.severity == Severity.BLOCKING)
        warns = sum(1 for c in checks if not c.passed and c.severity == Severity.WARNING)
        passed = blocking == 0
        return cls(
            plan_id=plan_id,
            step_id=step_id,
            passed=passed,
            checks=checks,
            blocking_failures=blocking,
            warnings=warns,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "step_id": self.step_id,
            "passed": self.passed,
            "blocking_failures": self.blocking_failures,
            "warnings": self.warnings,
            "notes": list(self.notes),
            "checks": [c.to_dict() for c in self.checks],
            "timestamp": self.timestamp.isoformat(),
        }


class VerificationFailed(RuntimeError):
    """Raised by the executor when a step's report is BLOCKING-failed."""


def _safe_to_serialize(value: Any) -> bool:
    """Best-effort: is this value JSON-friendly?"""
    if value is None:
        return True
    if isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, (list, tuple)):
        return all(_safe_to_serialize(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _safe_to_serialize(v) for k, v in value.items())
    return False


__all__ = [
    "Severity",
    "CheckKind",
    "CheckResult",
    "VerificationReport",
    "VerificationFailed",
]
