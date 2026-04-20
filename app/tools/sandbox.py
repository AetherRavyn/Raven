import asyncio
import os
import tempfile
import uuid
import shutil
from typing import Any, Dict, List

from app.tools.base import BaseTool, ToolSchema, ToolParameter, ToolCapability
from app.settings.config import Config

class SandboxExecTool(BaseTool):
    """
    Executes shell commands safely.
    If ALLOW_HOST_SHELL_EXECUTION is False (default), forces execution inside
    an ephemeral Docker container with only the workspace directory mounted.
    If True, it can fall back to local host execution (with high risk warnings).
    """

    def __init__(self, workspace_dir: str = "workspace"):
        self.workspace_dir = os.path.abspath(workspace_dir)
        os.makedirs(self.workspace_dir, exist_ok=True)

    def get_name(self) -> str:
        return "sandbox_exec"

    def get_description(self) -> str:
        return (
            "Safely execute arbitrary shell commands (bash/python/node/etc). "
            "Runs inside a secure ephemeral Docker container by default. "
            "Only the workspace directory is accessible. Use this for ALL code execution."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="command",
                    type="string",
                    description="The shell command to run (e.g., 'python script.py', 'npm run build')",
                    required=True,
                ),
                ToolParameter(
                    name="image",
                    type="string",
                    description="Optional Docker image to use (default: 'ubuntu:latest' or 'python:3.11-slim'). Use specific images if you need specific runtimes.",
                    required=False,
                ),
                ToolParameter(
                    name="timeout",
                    type="integer",
                    description="Timeout in seconds (default: 60)",
                    required=False,
                )
            ]
        )

    def get_capabilities(self) -> ToolCapability:
        return ToolCapability(
            required_permissions=["shell.exec", "fs.read", "fs.write"],
            risk_level="high",
            confirmation_policy="always" if not Config.ALLOW_HOST_SHELL_EXECUTION else "confirm",
            readonly=False
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        command = kwargs.get("command", "").strip()
        if not command:
            return {"success": False, "error": "Command is required."}

        image = kwargs.get("image", "ubuntu:22.04")
        timeout = int(kwargs.get("timeout", 60))

        # If host execution is explicitly allowed and we want to bypass docker
        # (Usually we still want docker, but for the sake of the flag)
        if Config.ALLOW_HOST_SHELL_EXECUTION and kwargs.get("force_host"):
            return await self._run_host(command, timeout)

        return await self._run_docker(command, image, timeout)

    async def _run_docker(self, command: str, image: str, timeout: int) -> Dict[str, Any]:
        """Runs the command inside an ephemeral docker container."""
        
        # Make sure docker is installed locally (using subprocess to call docker cli is easiest for async)
        if not shutil.which("docker"):
            return {"success": False, "error": "Docker is not installed or not in PATH on the host system."}

        container_name = f"saras_sandbox_{uuid.uuid4().hex[:8]}"

        # Mount workspace read-write to /workspace inside container
        # Run command inside /workspace
        docker_cmd = [
            "docker", "run", "--rm",
            "--name", container_name,
            "-v", f"{self.workspace_dir}:/workspace",
            "-w", "/workspace",
            "--network", "none", # Restrict network by default for pure sandboxing
            image,
            "sh", "-c", command
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                # Kill docker container
                kill_proc = await asyncio.create_subprocess_exec("docker", "rm", "-f", container_name, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await kill_proc.wait()
                return {"success": False, "error": f"Execution timed out after {timeout} seconds."}

            return {
                "success": proc.returncode == 0,
                "output": stdout.decode("utf-8", errors="replace"),
                "error": stderr.decode("utf-8", errors="replace"),
                "exit_code": proc.returncode,
                "sandbox": "docker"
            }

        except Exception as e:
            return {"success": False, "error": f"Failed to run docker container: {str(e)}"}

    async def _run_host(self, command: str, timeout: int) -> Dict[str, Any]:
        """Runs directly on the host (Only if explicitly permitted)."""
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=self.workspace_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return {"success": False, "error": f"Execution timed out after {timeout} seconds."}

            return {
                "success": proc.returncode == 0,
                "output": stdout.decode("utf-8", errors="replace"),
                "error": stderr.decode("utf-8", errors="replace"),
                "exit_code": proc.returncode,
                "sandbox": "none (HOST)"
            }
        except Exception as e:
            return {"success": False, "error": f"Host execution failed: {str(e)}"}

