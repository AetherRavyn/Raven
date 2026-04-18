import asyncio
import json
import os
import shlex
import shutil
from typing import Any, Dict

from app.core.security import get_security_guard
from app.tools.base import BaseTool, ToolCapability, ToolParameter, ToolSchema


class ExecTool(BaseTool):
    def __init__(self, default_workdir: str = "."):
        self.default_workdir = os.path.abspath(default_workdir)
        self.MAX_OUTPUT_LENGTH = 8000

        # === NUCLEAR CHECK ===
        if not shutil.which("bwrap"):
            raise RuntimeError(
                "bubblewrap (bwrap) is REQUIRED for Nuclear mode!\n"
                "Install it:\n"
                "   Ubuntu: sudo apt install bubblewrap\n"
                "   Fedora: sudo dnf install bubblewrap\n"
                "   Arch:   sudo pacman -S bubblewrap"
            )

    def get_name(self) -> str:
        return "exec"

    def get_description(self) -> str:
        return (
            "Nuclear sandboxed shell executor (bubblewrap). "
            "Read-only FS everywhere except workspace. "
            "Cannot touch or destroy anything outside workdir. "
            "Safe for git, npm, python, docker builds, etc."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="command",
                    type="string",
                    description="Full shell command (pipes, &&, redirects, wildcards all work)",
                    required=True,
                ),
                ToolParameter(
                    name="workdir",
                    type="string",
                    description="Relative or absolute path inside workspace (default = workspace root)",
                    required=False,
                ),
                ToolParameter(
                    name="timeout",
                    type="integer",
                    description="Timeout in seconds (default: 180)",
                    required=False,
                ),
                ToolParameter(
                    name="allow_network",
                    type="boolean",
                    description="Enable internet (git clone, pip install, curl...). Default: False (safer)",
                    required=False,
                ),
                ToolParameter(
                    name="extra_env",
                    type="string",
                    description='Extra env vars as JSON e.g. {"DEBUG":"1","NODE_ENV":"production"}',
                    required=False,
                ),
            ],
        )

    def get_capabilities(self) -> ToolCapability:
        return ToolCapability(
            required_permissions=["shell.exec"],
            risk_level="high",
            cost_tier="medium",
            confirmation_policy="always",
            readonly=False,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        command = kwargs.get("command", "").strip()
        if not command:
            return self._error("Command is required.")

        # === SECURITY GUARD CHECK ===
        guard = get_security_guard()
        is_safe, reason = guard.analyze_command(command)
        if not is_safe:
            return self._error(f"Security Policy Violation: {reason}")

        # === WORKDIR SAFETY ===
        workdir_param = kwargs.get("workdir")
        if workdir_param is None:
            workdir = self.default_workdir
        else:
            workdir = os.path.abspath(os.path.join(self.default_workdir, workdir_param))

        if not workdir.startswith(self.default_workdir):
            return self._error(
                f"Workdir must stay inside workspace: {self.default_workdir}"
            )

        if not os.path.isdir(workdir):
            return self._error(f"Workdir does not exist: {workdir}")

        timeout = int(kwargs.get("timeout", 180))
        allow_network = kwargs.get("allow_network", False)

        # Build env
        env = os.environ.copy()
        extra_env_str = kwargs.get("extra_env")
        if extra_env_str:
            try:
                extra = json.loads(extra_env_str)
                env.update({k: str(v) for k, v in extra.items()})
            except Exception:
                return self._error("extra_env must be valid JSON")

        result = await self._run_nuclear_command(
            command, workdir, env, allow_network, timeout
        )
        result["command"] = command
        result["workdir"] = workdir
        result["sandbox"] = "bubblewrap-nuclear"
        result["network_allowed"] = allow_network
        return result

    async def _run_nuclear_command(
        self,
        command: str,
        cwd: str,
        env: Dict[str, str],
        allow_network: bool,
        timeout: int,
    ) -> Dict[str, Any]:
        try:
            bwrap_args = [
                "bwrap",
                "--ro-bind",
                "/",
                "/",  # Entire system read-only
                "--bind",
                cwd,
                cwd,  # Only workspace is writable
                "--tmpfs",
                "/tmp",
                "--tmpfs",
                "/run",
                "--tmpfs",
                "/dev/shm",
                "--dev",
                "/dev",
                "--proc",
                "/proc",
                "--die-with-parent",
                "--new-session",
                "--cap-drop",
                "ALL",
                "--unshare-pid",
                "--unshare-ipc",
                "--unshare-cgroup",
                "--unshare-uts",
                "--chdir",
                cwd,
                "--setenv",
                "HOME",
                "/tmp/home",
                "--tmpfs",
                "/tmp/home",
            ]

            if not allow_network:
                bwrap_args.append("--unshare-net")

            # Full shell inside sandbox
            full_cmd = bwrap_args + ["--", "sh", "-c", command]

            proc = await asyncio.create_subprocess_exec(
                *full_cmd,
                env=env,  # inherits your env + extra_env
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout or None
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return {
                    "success": False,
                    "output": "",
                    "error": f"Timed out after {timeout}s",
                }

            stdout_str = stdout.decode("utf-8", errors="replace").strip()
            stderr_str = stderr.decode("utf-8", errors="replace").strip()

            output = stdout_str
            if stderr_str:
                output += "\n\n[STDERR]\n" + stderr_str if output else stderr_str

            if len(output) > self.MAX_OUTPUT_LENGTH:
                output = (
                    output[: self.MAX_OUTPUT_LENGTH]
                    + f"\n... [Truncated. Total: {len(output)} chars]"
                )

            if proc.returncode != 0:
                return {
                    "success": False,
                    "output": output,
                    "return_code": proc.returncode,
                    "error": f"Exited with code {proc.returncode}",
                }

            return {
                "success": True,
                "output": output or f"Success: {command}",
                "return_code": 0,
            }

        except Exception as e:
            return self._error(f"Sandbox error: {str(e)}")

    def _error(self, msg: str) -> Dict[str, Any]:
        return {"success": False, "output": f"Error: {msg}", "error": msg}
