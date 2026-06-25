"""Health_Monitor — module health checks and failure isolation.

The ``HealthMonitor`` reuses the existing health-report mechanism (the same
manifest-format, dependency, and required-secret checks the ``SkillRegistry``
applies) to record a module's latest :class:`HealthStatus` at registration time,
and tracks consecutive runtime failures so a faulty module can be auto-disabled
before it destabilises the core process.

Responsibilities (Requirement 9):

* ``check_registration`` — manifest-format + dependency-status + required-secret
  presence check, recorded as the module's latest health status. Secret *values*
  are never read or revealed; only key names appear in any check (Req 9.1, 9.2).
* ``record_success`` — reset a module's consecutive-failure count (Req 9.4).
* ``record_failure`` — increment the count and, on reaching the configurable
  threshold, notify the operator at HIGH priority through ``OutputRouter`` and
  signal the caller to auto-disable the module (Req 9.5, 9.6, 9.7).
* ``guard`` — run module-contributed code so an unhandled error is caught and
  never propagates to core; failures are counted, successes reset (Req 9.3, 9.4).
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, TypeVar

from app.core.audit import AuditEvent
from app.core.output_router import Priority
from app.modules.models import HealthStatus

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from app.core.audit import ActionLogger
    from app.core.output_router import OutputRouter
    from app.modules.models import ModuleRecord

logger = logging.getLogger(__name__)

T = TypeVar("T")

_DEFAULT_FAILURE_THRESHOLD = 3
_MODULE_ID_RE = re.compile(r"^[a-z0-9]+([._][a-z0-9]+)*$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

# Health-report state values, mirroring the SkillRegistry health report.
_HEALTHY = "healthy"
_DEGRADED = "degraded"
_UNHEALTHY = "unhealthy"


class HealthMonitor:
    """Runs module health checks and tracks consecutive execution failures.

    The consecutive-failure threshold is configurable and must be an integer of
    at least 1; it defaults to 3 (Req 9.7).
    """

    def __init__(
        self,
        router: OutputRouter,
        audit: ActionLogger,
        failure_threshold: int = _DEFAULT_FAILURE_THRESHOLD,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError(
                f"failure_threshold must be an integer >= 1, got {failure_threshold!r}"
            )
        self._router = router
        self._audit = audit
        self._failure_threshold = int(failure_threshold)
        self._failures: dict[str, int] = {}

    @property
    def failure_threshold(self) -> int:
        """The configured consecutive-failure threshold (Req 9.7)."""
        return self._failure_threshold

    def consecutive_failures(self, module_id: str) -> int:
        """The current consecutive execution-failure count for a module."""
        return self._failures.get(module_id, 0)

    # ── Registration health check (Req 9.1, 9.2) ───────────────────────

    async def check_registration(self, record: ModuleRecord) -> HealthStatus:
        """Run the registration health check and record it on the module.

        Covers manifest-format validity, dependency status, and required-secret
        presence, reusing the same health-report checks the ``SkillRegistry``
        applies. The result is stored as the module's latest health status. No
        secret value is read or revealed — only secret key names ever appear in a
        check message (Req 9.1, 9.2).
        """
        module_id = record.module_id
        checks: list[dict[str, Any]] = []
        errors = 0
        warnings = 0

        errors += self._check_manifest_format(record, checks)
        dep_errors, dep_warnings = self._check_dependencies(record, checks)
        errors += dep_errors
        warnings += dep_warnings
        errors += self._check_required_secrets(record, checks)

        if errors:
            state = _UNHEALTHY
        elif warnings:
            state = _DEGRADED
        else:
            state = _HEALTHY

        display_name = self._display_name(record)
        if state == _HEALTHY:
            summary = f"{display_name} passed its registration health check"
        elif state == _DEGRADED:
            summary = f"{display_name} registered with health warnings"
        else:
            summary = f"{display_name} failed its registration health check"

        status = HealthStatus(
            module_id=module_id,
            state=state,
            checks=checks,
            consecutive_failures=self.consecutive_failures(module_id),
            summary=summary,
            has_run=True,
        )
        record.health = status
        logger.debug(
            "Registration health for %s: state=%s checks=%d",
            module_id,
            state,
            len(checks),
        )
        return status

    # ── Consecutive-failure tracking (Req 9.3-9.6) ─────────────────────

    def record_success(self, module_id: str) -> None:
        """Reset a module's consecutive execution-failure count to zero (Req 9.4)."""
        if self._failures.get(module_id):
            logger.debug("Resetting failure count for module %s", module_id)
        self._failures[module_id] = 0

    async def record_failure(self, module_id: str) -> bool:
        """Record one consecutive failure; return True when the module hit the threshold.

        On reaching the configured threshold the operator is notified at HIGH
        priority through the ``OutputRouter`` and the auto-disable is audited.
        Returning True signals the caller to auto-disable the module
        (Req 9.5, 9.6, 9.7).
        """
        count = self._failures.get(module_id, 0) + 1
        self._failures[module_id] = count
        logger.debug(
            "Module %s failure count=%d (threshold=%d)",
            module_id,
            count,
            self._failure_threshold,
        )
        if count >= self._failure_threshold:
            self._notify_auto_disable(module_id, count)
            return True
        return False

    # ── Error isolation (Req 9.3, 9.4) ─────────────────────────────────

    async def guard(self, module_id: str, coro: Awaitable[T]) -> T | None:
        """Run module-contributed code, isolating any unhandled error from core.

        If the awaited code raises, the error is caught so it never propagates to
        the core process, one consecutive failure is recorded against the module,
        and ``None`` is returned. On success the failure count is reset and the
        result is returned (Req 9.3, 9.4).
        """
        try:
            result = await coro
        except Exception:
            logger.exception(
                "Module %s raised an unhandled error; isolated from core", module_id
            )
            await self.record_failure(module_id)
            return None
        self.record_success(module_id)
        return result

    # ── Internal helpers ───────────────────────────────────────────────

    def _notify_auto_disable(self, module_id: str, count: int) -> None:
        """Notify the operator (HIGH priority) and audit a module auto-disable."""
        message = (
            f"Module {module_id} auto-disabled after {count} consecutive "
            "execution failures."
        )
        try:
            self._router.route(
                message,
                source="module_health",
                explicit_priority=Priority.HIGH,
            )
        except Exception:  # pragma: no cover - delivery must never reach core
            logger.exception(
                "Failed to notify operator about auto-disable of %s", module_id
            )
        self._audit.record(
            AuditEvent(
                kind="module_health",
                action="auto_disable",
                success=True,
                detail=message,
                metadata={
                    "module_id": module_id,
                    "consecutive_failures": count,
                    "threshold": self._failure_threshold,
                },
            )
        )

    def _check_manifest_format(
        self, record: ModuleRecord, checks: list[dict[str, Any]]
    ) -> int:
        """Append the manifest-format check; return the number of errors found."""
        manifest = record.manifest
        problems: list[str] = []

        module_id = str(getattr(manifest, "module_id", "") or "")
        if not _MODULE_ID_RE.fullmatch(module_id):
            problems.append("module_id")

        version = str(getattr(manifest, "version", "") or "")
        if not _SEMVER_RE.fullmatch(version):
            problems.append("version")

        if not str(getattr(manifest, "schema_version", "") or ""):
            problems.append("schema_version")
        if not str(getattr(manifest, "display_name", "") or ""):
            problems.append("display_name")
        if not str(getattr(manifest, "description", "") or ""):
            problems.append("description")

        if problems:
            _add_check(
                checks,
                "manifest_format",
                "fail",
                "error",
                f"Invalid or missing manifest fields: {', '.join(sorted(problems))}",
            )
            return 1
        _add_check(
            checks,
            "manifest_format",
            "pass",
            "info",
            "Manifest format is valid",
        )
        return 0

    def _check_dependencies(
        self, record: ModuleRecord, checks: list[dict[str, Any]]
    ) -> tuple[int, int]:
        """Append dependency checks; return (errors, warnings).

        A required dependency that is not ``satisfied`` is an error; an
        unsatisfied optional dependency is a warning (Req 9.1).
        """
        errors = 0
        warnings = 0
        unmet_required: list[str] = []
        unmet_optional: list[str] = []
        for dep in record.resolved_dependencies:
            if dep.status == "satisfied":
                continue
            if dep.required:
                unmet_required.append(f"{dep.name} ({dep.status})")
            else:
                unmet_optional.append(f"{dep.name} ({dep.status})")

        if unmet_required:
            _add_check(
                checks,
                "dependencies",
                "fail",
                "error",
                f"Unmet required dependencies: {', '.join(unmet_required)}",
            )
            errors += 1
        elif unmet_optional:
            _add_check(
                checks,
                "dependencies",
                "warn",
                "warning",
                f"Unsatisfied optional dependencies: {', '.join(unmet_optional)}",
            )
            warnings += 1
        else:
            _add_check(
                checks,
                "dependencies",
                "pass",
                "info",
                "All declared dependencies are satisfied",
            )
        return errors, warnings

    def _check_required_secrets(
        self, record: ModuleRecord, checks: list[dict[str, Any]]
    ) -> int:
        """Append the required-secret presence check; return the number of errors.

        Only secret key *names* are recorded — never any secret value (Req 9.2).
        """
        absent = sorted(
            key for key, present in record.secret_presence.items() if not present
        )
        if absent:
            _add_check(
                checks,
                "required_secrets",
                "fail",
                "error",
                f"Missing required secrets: {', '.join(absent)}",
            )
            return 1
        _add_check(
            checks,
            "required_secrets",
            "pass",
            "info",
            "All required secrets are present",
        )
        return 0

    @staticmethod
    def _display_name(record: ModuleRecord) -> str:
        """Best-effort human label for a module, falling back to its id."""
        name = str(getattr(record.manifest, "display_name", "") or "")
        return name or record.module_id


def _add_check(
    checks: list[dict[str, Any]],
    name: str,
    status: str,
    severity: str,
    message: str,
) -> None:
    """Append a single health check entry, mirroring the SkillRegistry shape."""
    checks.append(
        {
            "name": name,
            "status": status,
            "severity": severity,
            "message": message,
        }
    )
