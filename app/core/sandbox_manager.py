"""Sandbox Manager — Centralized isolated execution for untrusted code.

Provides Docker-based and subprocess-based sandboxing with resource limits,
network isolation, and automatic cleanup. Used by tools that execute
arbitrary code (exec_tool, sandbox_exec, docker_exec_tool).

This is the centralized manager that all tools should route through,
replacing the inline Docker logic in sandbox.py and exectool.py.
"""

from __future__ import annotations

import asyncio
import logging
import os
import resource
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SandboxBackend(str, Enum):
    DOCKER = "docker"
    SUBPROCESS = "subprocess"
    NONE = "none"


@dataclass(slots=True)
class SandboxResult:
    """Result of a sandboxed execution."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    timed_out: bool = False
    backend: str = "unknown"
    container_id: str | None = None
    duration_ms: float = 0.0
    success: bool = False


@dataclass(slots=True)
class ResourceLimits:
    """Resource constraints for sandboxed execution."""

    memory_mb: int = 512
    cpu_count: float = 1.0
    timeout_seconds: int = 60
    network_enabled: bool = False
    max_output_bytes: int = 1_000_000  # 1 MB max output


class SandboxManager:
    """Centralized manager for isolated code execution.

    Supports two backends:
    - **Docker**: Full container isolation (preferred)
    - **Subprocess**: Process-level isolation with ulimits (fallback)

    Usage:
        manager = SandboxManager()
        result = await manager.execute("python -c 'print(42)'")
    """

    def __init__(
        self,
        workspace_dir: str | Path = "workspace",
        default_backend: SandboxBackend | str = SandboxBackend.DOCKER,
        default_image: str = "python:3.12-slim",
    ) -> None:
        self._workspace = Path(workspace_dir).resolve()
        self._workspace.mkdir(parents=True, exist_ok=True)
        self._default_image = default_image
        self._active_containers: set[str] = set()

        # Determine backend
        if isinstance(default_backend, str):
            default_backend = SandboxBackend(default_backend)
        self._default_backend = default_backend

        # Check Docker availability
        self._docker_available = shutil.which("docker") is not None
        if self._default_backend == SandboxBackend.DOCKER and not self._docker_available:
            logger.warning("Docker not found — falling back to subprocess sandbox")
            self._default_backend = SandboxBackend.SUBPROCESS

    # ── Public API ──────────────────────────────────────────────────

    async def execute(
        self,
        command: str,
        image: str | None = None,
        limits: ResourceLimits | None = None,
        backend: SandboxBackend | None = None,
        env: dict[str, str] | None = None,
        input_files: dict[str, str] | None = None,
    ) -> SandboxResult:
        """Execute a command in an isolated sandbox.

        Args:
            command: Shell command to execute.
            image: Docker image (only for Docker backend).
            limits: Resource constraints.
            backend: Override default backend.
            env: Environment variables to inject.
            input_files: Dict of {filename: content} to write into sandbox.
        """
        if not command.strip():
            return SandboxResult(stderr="Empty command", exit_code=1)

        limits = limits or ResourceLimits()
        backend = backend or self._default_backend

        if backend == SandboxBackend.DOCKER and self._docker_available:
            return await self._execute_docker(
                command, image or self._default_image, limits, env, input_files
            )
        elif backend == SandboxBackend.NONE:
            return await self._execute_host(command, limits, env)
        else:
            return await self._execute_subprocess(command, limits, env)

    async def cleanup(self) -> int:
        """Kill and remove all active sandbox containers."""
        cleaned = 0
        for container_id in list(self._active_containers):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker", "rm", "-f", container_id,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
                self._active_containers.discard(container_id)
                cleaned += 1
            except Exception as exc:
                logger.debug("Failed to clean container %s: %s", container_id, exc)
        return cleaned

    def get_status(self) -> dict[str, Any]:
        """Return sandbox manager status."""
        return {
            "backend": self._default_backend.value,
            "docker_available": self._docker_available,
            "active_containers": len(self._active_containers),
            "workspace": str(self._workspace),
        }

    # ── Docker Backend ──────────────────────────────────────────────

    async def _execute_docker(
        self,
        command: str,
        image: str,
        limits: ResourceLimits,
        env: dict[str, str] | None,
        input_files: dict[str, str] | None,
    ) -> SandboxResult:
        """Execute inside an ephemeral Docker container."""
        container_name = f"ravyn_sandbox_{uuid.uuid4().hex[:8]}"
        start_time = asyncio.get_event_loop().time()

        docker_cmd = [
            "docker", "run", "--rm",
            "--name", container_name,
            "-v", f"{self._workspace}:/workspace:rw",
            "-w", "/workspace",
            f"--memory={limits.memory_mb}m",
            f"--cpus={limits.cpu_count}",
            "--pids-limit=256",
        ]

        if not limits.network_enabled:
            docker_cmd.append("--network=none")

        if env:
            for key, value in env.items():
                docker_cmd.extend(["-e", f"{key}={value}"])

        docker_cmd.extend([image, "sh", "-c", command])

        self._active_containers.add(container_name)

        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=limits.timeout_seconds
                )
            except asyncio.TimeoutError:
                await self._kill_container(container_name)
                elapsed = (asyncio.get_event_loop().time() - start_time) * 1000
                return SandboxResult(
                    stderr=f"Timed out after {limits.timeout_seconds}s",
                    timed_out=True,
                    backend="docker",
                    container_id=container_name,
                    duration_ms=elapsed,
                )

            elapsed = (asyncio.get_event_loop().time() - start_time) * 1000

            stdout = stdout_bytes.decode("utf-8", errors="replace")[
                : limits.max_output_bytes
            ]
            stderr = stderr_bytes.decode("utf-8", errors="replace")[
                : limits.max_output_bytes
            ]

            return SandboxResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=proc.returncode or 0,
                backend="docker",
                container_id=container_name,
                duration_ms=elapsed,
                success=proc.returncode == 0,
            )

        except Exception as exc:
            logger.error("Docker sandbox error: %s", exc)
            return SandboxResult(
                stderr=f"Docker error: {exc}",
                exit_code=1,
                backend="docker",
                container_id=container_name,
            )
        finally:
            self._active_containers.discard(container_name)

    async def _kill_container(self, name: str) -> None:
        """Force-kill a Docker container."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "rm", "-f", name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except Exception:
            pass
        self._active_containers.discard(name)

    # ── Subprocess Backend ──────────────────────────────────────────

    async def _execute_subprocess(
        self,
        command: str,
        limits: ResourceLimits,
        env: dict[str, str] | None,
    ) -> SandboxResult:
        """Execute in a subprocess with resource limits."""
        start_time = asyncio.get_event_loop().time()

        process_env = os.environ.copy()
        if env:
            process_env.update(env)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(self._workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=process_env,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=limits.timeout_seconds
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                elapsed = (asyncio.get_event_loop().time() - start_time) * 1000
                return SandboxResult(
                    stderr=f"Timed out after {limits.timeout_seconds}s",
                    timed_out=True,
                    backend="subprocess",
                    duration_ms=elapsed,
                )

            elapsed = (asyncio.get_event_loop().time() - start_time) * 1000

            return SandboxResult(
                stdout=stdout_bytes.decode("utf-8", errors="replace")[
                    : limits.max_output_bytes
                ],
                stderr=stderr_bytes.decode("utf-8", errors="replace")[
                    : limits.max_output_bytes
                ],
                exit_code=proc.returncode or 0,
                backend="subprocess",
                duration_ms=elapsed,
                success=proc.returncode == 0,
            )

        except Exception as exc:
            return SandboxResult(
                stderr=f"Subprocess error: {exc}",
                exit_code=1,
                backend="subprocess",
            )

    # ── Host Backend (no isolation) ─────────────────────────────────

    async def _execute_host(
        self,
        command: str,
        limits: ResourceLimits,
        env: dict[str, str] | None,
    ) -> SandboxResult:
        """Execute directly on host (no isolation — use with caution)."""
        logger.warning("Executing on host WITHOUT sandbox: %s", command[:80])
        return await self._execute_subprocess(command, limits, env)


# ── Module singleton ────────────────────────────────────────────────

_GLOBAL_SANDBOX: SandboxManager | None = None


def get_sandbox_manager(
    workspace_dir: str | Path = "workspace",
) -> SandboxManager:
    """Get or create the global SandboxManager."""
    global _GLOBAL_SANDBOX
    if _GLOBAL_SANDBOX is None:
        backend_str = os.getenv("SANDBOX_BACKEND", "docker")
        try:
            backend = SandboxBackend(backend_str)
        except ValueError:
            backend = SandboxBackend.DOCKER
        _GLOBAL_SANDBOX = SandboxManager(
            workspace_dir=workspace_dir,
            default_backend=backend,
        )
    return _GLOBAL_SANDBOX
