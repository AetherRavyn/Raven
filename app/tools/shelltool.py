"""Unified Shell Tool — Single interface for all execution backends.

Routes through SandboxManager which supports Docker containers,
subprocess sandboxing, and host execution. Replaces the need to
choose between exec, sandbox_exec, and docker_exec manually.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.tools.base import BaseTool, ToolCapability, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)

_MAX_OUTPUT = 8000


class ShellTool(BaseTool):
    """Execute shell commands in an isolated sandbox.

    Routes through SandboxManager which automatically selects Docker
    (preferred) or subprocess isolation. Supports resource limits,
    network control, and workspace workdirs.
    """

    group = "development"

    def __init__(self, workspace_dir: str = "workspace") -> None:
        super().__init__()
        self._workspace_dir = workspace_dir

    def get_name(self) -> str:
        return "shell"

    def get_description(self) -> str:
        return (
            "Execute a shell command in an isolated sandbox. "
            "Automatically uses Docker when available, falls back to "
            "subprocess isolation. Set backend=docker, subprocess, or none "
            "to override. Supports pipes, redirects, chaining."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="command",
                    type="string",
                    description="Shell command to execute",
                    required=True,
                ),
                ToolParameter(
                    name="backend",
                    type="string",
                    description="Execution backend: docker (default), subprocess, none",
                    required=False,
                    enum=["docker", "subprocess", "none"],
                ),
                ToolParameter(
                    name="timeout",
                    type="integer",
                    description="Timeout in seconds (default 60)",
                    required=False,
                ),
                ToolParameter(
                    name="workdir",
                    type="string",
                    description="Working directory relative to workspace",
                    required=False,
                ),
                ToolParameter(
                    name="allow_network",
                    type="boolean",
                    description="Allow network access (default false)",
                    required=False,
                ),
                ToolParameter(
                    name="image",
                    type="string",
                    description="Docker image (only for docker backend, default python:3.12-slim)",
                    required=False,
                ),
                ToolParameter(
                    name="memory_mb",
                    type="integer",
                    description="Memory limit in MB (default 512)",
                    required=False,
                ),
                ToolParameter(
                    name="env",
                    type="string",
                    description="JSON dict of extra environment variables",
                    required=False,
                ),
            ],
        )

    def get_capability(self) -> ToolCapability:
        return ToolCapability(
            required_permissions=["shell.exec"],
            risk_level="high",
            cost_tier="medium",
            confirmation_policy="always",
            readonly=False,
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        command = kwargs.get("command", "").strip()
        if not command:
            return {"success": False, "error": "Empty command"}

        backend_str = kwargs.get("backend", "auto")
        timeout_val = kwargs.get("timeout", 60)
        workdir = kwargs.get("workdir", "")
        allow_network = kwargs.get("allow_network", False)
        image = kwargs.get("image")
        memory_mb = kwargs.get("memory_mb", 512)
        env_raw = kwargs.get("env", "{}")

        # Security guard check
        try:
            from app.core.security import get_security_guard

            guard = get_security_guard()
            is_safe, reason = guard.analyze_command(command)
            if not is_safe:
                return {
                    "success": False,
                    "error": f"Command rejected by security guard: {reason}",
                    "command": command,
                    "sandbox": "rejected",
                }
        except Exception:
            pass

        # Parse extra env
        extra_env: dict[str, str] = {}
        if env_raw:
            try:
                extra_env = json.loads(env_raw)
                if not isinstance(extra_env, dict):
                    extra_env = {}
            except json.JSONDecodeError:
                pass

        # Resolve working directory
        from pathlib import Path

        sandbox_workspace = Path(self._workspace_dir).resolve()
        if workdir:
            target = sandbox_workspace / workdir
            # Ensure it stays within workspace
            try:
                target = target.resolve()
                target.relative_to(sandbox_workspace)
            except (ValueError, FileNotFoundError):
                return {
                    "success": False,
                    "error": f"Workdir '{workdir}' is outside the workspace",
                    "command": command,
                }
            sandbox_workspace = target

        from app.core.sandbox_manager import (
            ResourceLimits,
            SandboxBackend,
            get_sandbox_manager,
        )

        manager = get_sandbox_manager(workspace_dir=str(sandbox_workspace))

        # Map backend string to SandboxBackend
        backend_map = {
            "docker": SandboxBackend.DOCKER,
            "subprocess": SandboxBackend.SUBPROCESS,
            "none": SandboxBackend.NONE,
        }
        backend = None
        if backend_str in backend_map:
            backend = backend_map[backend_str]
        elif backend_str == "auto":
            backend = None  # Use manager default

        limits = ResourceLimits(
            timeout_seconds=max(1, int(timeout_val or 60)),
            network_enabled=bool(allow_network),
            memory_mb=int(memory_mb),
            max_output_bytes=_MAX_OUTPUT,
        )

        try:
            result = await manager.execute(
                command=command,
                image=image,
                limits=limits,
                backend=backend,
                env=extra_env if extra_env else None,
            )
        except Exception as e:
            logger.exception("Shell execution failed")
            return {
                "success": False,
                "error": str(e),
                "command": command,
            }

        output = result.stdout
        if result.stderr:
            if output:
                output += "\n" + result.stderr
            else:
                output = result.stderr

        if len(output) > _MAX_OUTPUT:
            output = output[:_MAX_OUTPUT] + "\n... [output truncated]"

        response: dict[str, Any] = {
            "success": result.success,
            "output": output,
            "return_code": result.exit_code,
            "sandbox": result.backend,
            "command": command,
            "timed_out": result.timed_out,
        }
        if not result.success and not result.timed_out:
            response["error"] = f"Exited with code {result.exit_code}"

        return response
