"""Dependency resolution for the Modular Extension Platform (assumption A4).

``SkillRegistry`` normalizes declared dependencies into ``{name, status, required,
message}`` records but never runs their ``check`` shell command. This module closes
that gap: :class:`DependencyResolver` executes each declared ``check`` through the
shared :class:`~app.core.sandbox_manager.SandboxManager` and maps the outcome to a
resolved status of ``satisfied`` (exit 0), ``unsatisfied`` (non-zero exit), or
``unknown`` (execution error or timeout).

External execution is routed through the tool resilience layer
(``app.tools.resilience``) so transient failures are retried with backoff before a
dependency is reported as ``unknown``.
"""

from __future__ import annotations

import logging

from app.core.sandbox_manager import (
    ResourceLimits,
    SandboxBackend,
    SandboxManager,
    SandboxResult,
)
from app.modules.models import DependencySpec, ResolvedDependency
from app.tools.resilience import with_retry

logger = logging.getLogger(__name__)

STATUS_SATISFIED = "satisfied"
STATUS_UNSATISFIED = "unsatisfied"
STATUS_UNKNOWN = "unknown"

# Dependency checks probe the running environment (e.g. ``python -c 'import cv2'``),
# so they execute against the host environment via the subprocess backend rather than
# an isolated Docker container that would not reflect installed host packages.
_DEFAULT_BACKEND = SandboxBackend.SUBPROCESS
_DEFAULT_CHECK_TIMEOUT_S = 10


class DependencyResolver:
    """Resolve declared module dependencies by running their ``check`` commands."""

    def __init__(
        self,
        sandbox: SandboxManager,
        *,
        backend: SandboxBackend = _DEFAULT_BACKEND,
        check_timeout_s: int = _DEFAULT_CHECK_TIMEOUT_S,
    ) -> None:
        self._sandbox = sandbox
        self._backend = backend
        self._limits = ResourceLimits(
            timeout_seconds=check_timeout_s,
            network_enabled=False,
        )

    async def resolve(self, deps: list[DependencySpec]) -> list[ResolvedDependency]:
        """Resolve every declared dependency to ``satisfied``/``unsatisfied``/``unknown``.

        Each dependency's ``check`` command runs through ``SandboxManager``: exit 0 maps
        to ``satisfied``, a non-zero exit to ``unsatisfied``, and an execution error or
        timeout to ``unknown`` (Req 4.1, A4). A dependency without a ``check`` command
        cannot be probed and resolves to ``unknown``.
        """
        return [await self._resolve_one(dep) for dep in deps]

    async def _resolve_one(self, dep: DependencySpec) -> ResolvedDependency:
        if dep.check is None or not dep.check.strip():
            return ResolvedDependency(
                name=dep.name,
                required=dep.required,
                status=STATUS_UNKNOWN,
                message="no check command declared",
            )

        try:
            result = await self._run_check(dep.check)
        except Exception as exc:  # never let a check failure reach core
            logger.warning(
                "Dependency check for %r failed to execute: %s", dep.name, exc
            )
            return ResolvedDependency(
                name=dep.name,
                required=dep.required,
                status=STATUS_UNKNOWN,
                message=f"check failed to execute: {exc}",
            )

        if result.timed_out:
            return ResolvedDependency(
                name=dep.name,
                required=dep.required,
                status=STATUS_UNKNOWN,
                message="check timed out",
            )

        if result.exit_code == 0:
            return ResolvedDependency(
                name=dep.name,
                required=dep.required,
                status=STATUS_SATISFIED,
            )

        return ResolvedDependency(
            name=dep.name,
            required=dep.required,
            status=STATUS_UNSATISFIED,
            message=(result.stderr or result.stdout).strip(),
        )

    @with_retry(max_attempts=2, backoff_base=1.0)
    async def _run_check(self, command: str) -> SandboxResult:
        """Execute a single ``check`` command through the sandbox + resilience layer."""
        return await self._sandbox.execute(
            command,
            limits=self._limits,
            backend=self._backend,
        )

    @staticmethod
    def unmet_required(
        resolved: list[ResolvedDependency],
    ) -> list[ResolvedDependency]:
        """Return required dependencies whose resolved status is not ``satisfied``.

        These block registration of the module (Req 4.2).
        """
        return [
            dep for dep in resolved if dep.required and dep.status != STATUS_SATISFIED
        ]
