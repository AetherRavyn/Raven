import docker
import asyncio
from typing import Any, Dict
from app.tools.base import BaseTool, ToolSchema, ToolParameter, ToolCapability

class DockerExecTool(BaseTool):
    group = "development"

    def get_name(self) -> str:
        return "docker_exec"

    def get_description(self) -> str:
        return "Spins up an ephemeral Docker container to execute arbitrary code safely."

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name="docker_exec",
            description="Spins up an ephemeral Docker container to execute arbitrary code safely.",
            parameters=[
                ToolParameter(
                    name="command",
                    type="string",
                    description="The code or script to run.",
                    required=True
                ),
                ToolParameter(
                    name="image",
                    type="string",
                    description="The Docker image to use. Default is python:3.11-slim.",
                    required=False
                ),
                ToolParameter(
                    name="timeout",
                    type="integer",
                    description="Execution timeout in seconds. Default is 30.",
                    required=False
                ),
                ToolParameter(
                    name="workdir_mount",
                    type="string",
                    description="Optional host directory to mount at /workspace.",
                    required=False
                )
            ]
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        command = kwargs.get("command")
        image = kwargs.get("image", "python:3.11-slim")
        timeout = int(kwargs.get("timeout", 30))
        workdir_mount = kwargs.get("workdir_mount")

        if not command:
            return {"error": "command is required"}

        try:
            client = docker.from_env()
        except Exception as e:
            return {"error": f"Failed to initialize Docker client: {str(e)}"}

        volumes = {}
        working_dir = None
        if workdir_mount:
            volumes[workdir_mount] = {"bind": "/workspace", "mode": "rw"}
            working_dir = "/workspace"

        try:
            # Run in a separate thread to prevent blocking the async loop, but for simplicity we can run synchronously
            # or use asyncio.to_thread
            container = client.containers.run(
                image=image,
                command=["sh", "-c", command],
                detach=True,
                volumes=volumes,
                working_dir=working_dir
            )

            # Polling for container to finish or timeout
            for _ in range(timeout):
                container.reload()
                if container.status == "exited":
                    break
                await asyncio.sleep(1)

            container.reload()
            if container.status != "exited":
                container.stop(timeout=1)
                container.remove(force=True)
                return {"error": f"Execution timed out after {timeout} seconds."}

            result = container.wait()
            logs = container.logs()
            container.remove(v=True, force=True)

            status_code = result.get("StatusCode", -1)
            output = logs.decode("utf-8", errors="replace")

            return {
                "status_code": status_code,
                "output": output
            }

        except Exception as e:
            return {"error": f"Error during container execution: {str(e)}"}
