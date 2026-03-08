# app/tools/systemstatstool.py
"""SystemStatsTool — monitor system resources: CPU, RAM, disk, processes."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)

try:
    import psutil
except ImportError:
    psutil = None


class SystemStatsTool(BaseTool):
    """Monitor system resources: CPU, memory, disk, processes, network."""

    def get_name(self) -> str:
        return "system_stats"

    def get_description(self) -> str:
        return (
            "Get system statistics: CPU usage, memory usage, disk usage, "
            "process list, network connections, battery status, and system uptime. "
            "Can filter by specific metric or list top processes by CPU/memory."
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
                        "cpu",
                        "memory",
                        "disk",
                        "processes",
                        "network",
                        "battery",
                        "uptime",
                        "all",
                        "top_cpu",
                        "top_memory",
                    ],
                ),
                ToolParameter(
                    name="path",
                    type="string",
                    description="Disk path to check (default: /)",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Number of processes to return for top operations",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        if psutil is None:
            return {
                "success": False,
                "error": "psutil not installed. Install with: pip install psutil",
            }

        operation = kwargs.get("operation", "all")
        path = kwargs.get("path", "/")
        limit = kwargs.get("limit", 10)

        try:
            if operation == "cpu" or operation == "all":
                cpu = psutil.cpu_percent(interval=0.1, percpu=True)
                cpu_count = psutil.cpu_count()
                cpu_freq = psutil.cpu_freq()
                load_avg = os.getloadavg() if hasattr(os, "getloadavg") else None
                result = {
                    "cpu_percent": cpu,
                    "cpu_count": cpu_count,
                    "cpu_freq_current": cpu_freq.current if cpu_freq else None,
                    "load_average": load_avg,
                }
                if operation == "all":
                    result = {"cpu": result}

            if operation == "memory" or operation == "all":
                mem = psutil.virtual_memory()
                swap = psutil.swap_memory()
                mem_result = {
                    "total_gb": round(mem.total / (1024**3), 2),
                    "available_gb": round(mem.available / (1024**3), 2),
                    "used_gb": round(mem.used / (1024**3), 2),
                    "percent": mem.percent,
                    "swap_total_gb": round(swap.total / (1024**3), 2),
                    "swap_used_gb": round(swap.used / (1024**3), 2),
                    "swap_percent": swap.percent,
                }
                if operation == "all":
                    result["memory"] = mem_result
                else:
                    result = mem_result

            if operation == "disk" or operation == "all":
                disk = psutil.disk_usage(path)
                disk_result = {
                    "path": path,
                    "total_gb": round(disk.total / (1024**3), 2),
                    "used_gb": round(disk.used / (1024**3), 2),
                    "free_gb": round(disk.free / (1024**3), 2),
                    "percent": disk.percent,
                }
                if operation == "all":
                    result["disk"] = disk_result
                else:
                    result = disk_result

            if operation == "processes" or operation == "all":
                processes = []
                for p in psutil.process_iter(
                    ["pid", "name", "username", "cpu_percent", "memory_percent"]
                ):
                    try:
                        processes.append(
                            {
                                "pid": p.info["pid"],
                                "name": p.info["name"],
                                "username": p.info["username"],
                                "cpu_percent": p.info["cpu_percent"],
                                "memory_percent": p.info["memory_percent"],
                            }
                        )
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                if operation == "all":
                    result["processes"] = processes[:50]
                else:
                    result = processes[:50]

            if operation == "top_cpu":
                processes = []
                for p in psutil.process_iter(
                    ["pid", "name", "cpu_percent", "memory_percent"]
                ):
                    try:
                        processes.append(
                            {
                                "pid": p.info["pid"],
                                "name": p.info["name"],
                                "cpu_percent": p.info["cpu_percent"] or 0,
                                "memory_percent": p.info["memory_percent"] or 0,
                            }
                        )
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                processes.sort(key=lambda x: x["cpu_percent"], reverse=True)
                result = {"top_cpu_processes": processes[:limit]}

            if operation == "top_memory":
                processes = []
                for p in psutil.process_iter(
                    ["pid", "name", "cpu_percent", "memory_percent"]
                ):
                    try:
                        processes.append(
                            {
                                "pid": p.info["pid"],
                                "name": p.info["name"],
                                "cpu_percent": p.info["cpu_percent"] or 0,
                                "memory_percent": p.info["memory_percent"] or 0,
                            }
                        )
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                processes.sort(key=lambda x: x["memory_percent"], reverse=True)
                result = {"top_memory_processes": processes[:limit]}

            if operation == "network" or operation == "all":
                net = psutil.net_io_counters()
                connections = len(psutil.net_connections())
                net_result = {
                    "bytes_sent_mb": round(net.bytes_sent / (1024**2), 2),
                    "bytes_recv_mb": round(net.bytes_recv / (1024**2), 2),
                    "packets_sent": net.packets_sent,
                    "packets_recv": net.packets_recv,
                    "connections": connections,
                }
                if operation == "all":
                    result["network"] = net_result
                else:
                    result = net_result

            if operation == "battery" or operation == "all":
                battery = psutil.sensors_battery()
                if battery:
                    bat_result = {
                        "percent": battery.percent,
                        "plugged_in": battery.power_plugged,
                        "time_left_minutes": (
                            battery.secsleft / 60
                            if battery.secsleft != psutil.POWER_TIME_UNLIMITED
                            else None
                        ),
                    }
                else:
                    bat_result = {"error": "No battery detected"}
                if operation == "all":
                    result["battery"] = bat_result
                else:
                    result = bat_result

            if operation == "uptime" or operation == "all":
                boot_time = psutil.boot_time()
                import time

                uptime_seconds = time.time() - boot_time
                days = int(uptime_seconds // 86400)
                hours = int((uptime_seconds % 86400) // 3600)
                minutes = int((uptime_seconds % 3600) // 60)
                up_result = {
                    "seconds": int(uptime_seconds),
                    "readable": f"{days}d {hours}h {minutes}m",
                }
                if operation == "all":
                    result["uptime"] = up_result
                else:
                    result = up_result

            return {"success": True, **result}

        except Exception as exc:
            logger.exception("SystemStatsTool error")
            return {"success": False, "error": str(exc)}
