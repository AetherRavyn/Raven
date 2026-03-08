# app/tools/dockertool.py
"""DockerTool — monitor Docker containers and images."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)

try:
    import docker
except ImportError:
    docker = None


class DockerTool(BaseTool):
    """Monitor and manage Docker containers, images, volumes, and networks."""

    def __init__(self):
        self._client = None
        if docker:
            try:
                self._client = docker.from_env()
            except Exception:
                pass

    def get_name(self) -> str:
        return "docker"

    def get_description(self) -> str:
        return (
            "Monitor and manage Docker: list containers (running/all), "
            "get container stats, inspect containers, start/stop/restart containers, "
            "list images, pull images, list volumes, and get system info."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Operation to perform",
                    required=True,
                    enum=[
                        "list_containers",
                        "container_stats",
                        "inspect_container",
                        "start_container",
                        "stop_container",
                        "restart_container",
                        "list_images",
                        "pull_image",
                        "list_volumes",
                        "list_networks",
                        "system_info",
                        "prune",
                    ],
                ),
                ToolParameter(
                    name="container_id",
                    type="string",
                    description="Container name or ID (partial name works)",
                    required=False,
                ),
                ToolParameter(
                    name="image",
                    type="string",
                    description="Image name to pull (e.g., 'nginx:latest')",
                    required=False,
                ),
                ToolParameter(
                    name="all",
                    type="boolean",
                    description="Include stopped containers in list",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        if docker is None:
            return {
                "success": False,
                "error": "docker not installed. Install with: pip install docker",
            }

        if self._client is None:
            return {
                "success": False,
                "error": "Docker not available. Is Docker running?",
            }

        operation = kwargs.get("operation", "")
        container_id = kwargs.get("container_id", "")
        image = kwargs.get("image", "")
        show_all = kwargs.get("all", False)

        try:
            if operation == "list_containers":
                containers = self._client.containers.list(all=show_all)
                return {
                    "success": True,
                    "containers": [
                        {
                            "id": c.id[:12],
                            "name": c.name,
                            "image": c.image.tags[0]
                            if c.image.tags
                            else c.image.short_id,
                            "status": c.status,
                            "created": str(c.attrs.get("Created", "")),
                        }
                        for c in containers
                    ],
                }

            if operation == "container_stats":
                if not container_id:
                    return {"success": False, "error": "container_id required"}
                container = self._client.containers.get(container_id)
                stats = container.stats(stream=False)
                cpu_delta = (
                    stats["cpu_stats"]["cpu_usage"]["total_usage"]
                    - stats["precpu_stats"]["cpu_usage"]["total_usage"]
                )
                system_delta = (
                    stats["cpu_stats"]["system_cpu_usage"]
                    - stats["precpu_stats"]["system_cpu_usage"]
                )
                cpu_percent = (
                    (cpu_delta / system_delta * 100.0) if system_delta > 0 else 0
                )
                mem_usage = stats["memory_stats"]["usage"] / (1024**2)
                mem_limit = stats["memory_stats"]["limit"] / (1024**2)
                mem_percent = (mem_usage / mem_limit * 100.0) if mem_limit > 0 else 0
                return {
                    "success": True,
                    "container": container_id,
                    "cpu_percent": round(cpu_percent, 2),
                    "memory_mb": round(mem_usage, 2),
                    "memory_percent": round(mem_percent, 2),
                    "network_rx_mb": round(
                        stats["networks"].get("eth0", {}).get("rx_bytes", 0)
                        / (1024**2),
                        2,
                    )
                    if stats.get("networks")
                    else 0,
                    "network_tx_mb": round(
                        stats["networks"].get("eth0", {}).get("tx_bytes", 0)
                        / (1024**2),
                        2,
                    )
                    if stats.get("networks")
                    else 0,
                }

            if operation == "inspect_container":
                if not container_id:
                    return {"success": False, "error": "container_id required"}
                container = self._client.containers.get(container_id)
                return {
                    "success": True,
                    "id": container.id[:12],
                    "name": container.name,
                    "image": container.image.tags[0]
                    if container.image.tags
                    else container.image.short_id,
                    "status": container.status,
                    "ports": container.ports,
                    "volumes": container.attrs.get("Mounts", []),
                    "env": [
                        e
                        for e in container.attrs.get("Config", {}).get("Env", [])
                        if not e.startswith("PATH=")
                    ][:10],
                }

            if operation == "start_container":
                if not container_id:
                    return {"success": False, "error": "container_id required"}
                container = self._client.containers.get(container_id)
                container.start()
                return {"success": True, "action": "started", "container": container_id}

            if operation == "stop_container":
                if not container_id:
                    return {"success": False, "error": "container_id required"}
                container = self._client.containers.get(container_id)
                container.stop(timeout=10)
                return {"success": True, "action": "stopped", "container": container_id}

            if operation == "restart_container":
                if not container_id:
                    return {"success": False, "error": "container_id required"}
                container = self._client.containers.get(container_id)
                container.restart(timeout=10)
                return {
                    "success": True,
                    "action": "restarted",
                    "container": container_id,
                }

            if operation == "list_images":
                images = self._client.images.list()
                return {
                    "success": True,
                    "images": [
                        {
                            "id": i.id[:12],
                            "tags": i.tags,
                            "size_mb": round(i.attrs["Size"] / (1024**2), 2),
                            "created": str(i.attrs.get("Created", "")),
                        }
                        for i in images
                    ],
                }

            if operation == "pull_image":
                if not image:
                    return {"success": False, "error": "image name required"}
                self._client.images.pull(image)
                return {"success": True, "action": "pulled", "image": image}

            if operation == "list_volumes":
                volumes = self._client.volumes.list()
                return {
                    "success": True,
                    "volumes": [
                        {
                            "name": v.name,
                            "driver": v.driver,
                            "mountpoint": v.attrs.get("Mountpoint", ""),
                        }
                        for v in volumes
                    ],
                }

            if operation == "list_networks":
                networks = self._client.networks.list()
                return {
                    "success": True,
                    "networks": [
                        {
                            "id": n.id[:12],
                            "name": n.name,
                            "driver": n.attrs.get("Driver", ""),
                        }
                        for n in networks
                    ],
                }

            if operation == "system_info":
                info = self._client.info()
                return {
                    "success": True,
                    "containers": info.get("Containers", 0),
                    "running": info.get("ContainersRunning", 0),
                    "paused": info.get("ContainersPaused", 0),
                    "stopped": info.get("ContainersStopped", 0),
                    "images": info.get("Images", 0),
                    "memory_total_gb": round(info.get("MemTotal", 0) / (1024**3), 2),
                    "cpu_count": info.get("NCPU", 0),
                    "docker_version": info.get("ServerVersion", ""),
                }

            if operation == "prune":
                self._client.containers.prune()
                self._client.images.prune()
                self._client.volumes.prune()
                self._client.networks.prune()
                return {
                    "success": True,
                    "action": "pruned",
                    "message": "Cleaned up unused containers, images, volumes, and networks",
                }

            return {"success": False, "error": f"Unknown operation: {operation}"}

        except docker.errors.NotFound:
            return {"success": False, "error": f"Container '{container_id}' not found"}
        except Exception as exc:
            logger.exception("DockerTool error")
            return {"success": False, "error": str(exc)}
