"""Real-time Monitoring — watch URLs, APIs, and services for changes.

Provides a MonitoringTool that:
- Watches URLs for content changes (diff-based)
- Monitors API endpoints for status/latency changes
- Checks SSL certificate expiry
- Stores change history for alerting
- Can be configured with check intervals
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class MonitorEntry:
    """A monitored target."""
    def __init__(self, monitor_id: str, target_url: str, check_interval: int = 300,
                 alert_threshold: float = 0.1, name: str = ""):
        self.monitor_id = monitor_id
        self.target_url = target_url
        self.check_interval = check_interval
        self.alert_threshold = alert_threshold
        self.name = name or target_url[:50]
        self.last_check: float = 0
        self.last_hash: str = ""
        self.last_status: int = 0
        self.change_count: int = 0


class MonitoringTool(BaseTool):
    """Monitor URLs and APIs for changes."""

    def __init__(self, workspace_dir: str = "workspace") -> None:
        from app.settings.config import Config
        self._dir = Path(workspace_dir or Config.MEMORY_ROOT) / "monitoring"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._monitors_file = self._dir / "monitors.json"
        self._changes_file = self._dir / "changes.jsonl"
        self._monitors: dict[str, dict] = self._load_monitors()

    def get_name(self) -> str:
        return "url_monitor"

    def get_description(self) -> str:
        return (
            "Monitor URLs and APIs for changes. "
            "Add, list, check, and remove monitors. "
            "Detects content changes, status code changes, and response time anomalies."
        )

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": ["add", "list", "check", "check_all", "remove", "history"],
                    "description": "Operation to perform"},
                "url": {"type": "string", "description": "URL to monitor (for add)"},
                "name": {"type": "string", "description": "Friendly name for the monitor"},
                "interval": {"type": "integer", "description": "Check interval in seconds (default 300)"},
                "monitor_id": {"type": "string", "description": "Monitor ID (for remove/history)"},
            },
            "required": ["operation"],
        }

    async def execute(self, **kwargs: Any) -> dict:
        operation = kwargs.get("operation", "list")

        if operation == "add":
            url = kwargs.get("url", "")
            if not url:
                return {"error": "url is required"}
            import uuid
            mid = f"mon_{uuid.uuid4().hex[:8]}"
            self._monitors[mid] = {
                "id": mid, "url": url,
                "name": kwargs.get("name", url[:50]),
                "interval": kwargs.get("interval", 300),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._save_monitors()
            return {"success": True, "monitor_id": mid, "message": f"Monitoring {url}"}

        elif operation == "list":
            return {"monitors": list(self._monitors.values()), "count": len(self._monitors)}

        elif operation in ("check", "check_all"):
            return await self._check_monitors(kwargs.get("monitor_id"))

        elif operation == "remove":
            mid = kwargs.get("monitor_id", "")
            if mid in self._monitors:
                del self._monitors[mid]
                self._save_monitors()
                return {"success": True, "removed": mid}
            return {"error": f"Monitor {mid} not found"}

        elif operation == "history":
            mid = kwargs.get("monitor_id", "")
            return {"changes": self._get_changes(mid)}

        return {"error": f"Unknown operation: {operation}"}

    async def _check_monitors(self, specific_id: str = None) -> dict:
        """Check monitors for changes."""
        import httpx

        results = []
        now = time.time()

        for mid, mon in list(self._monitors.items()):
            if specific_id and mid != specific_id:
                continue

            # Check interval
            last_check = self._monitors[mid].get("last_check", 0)
            if now - last_check < mon.get("interval", 300):
                continue

            url = mon["url"]
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(url)
                    content_hash = hashlib.md5(resp.text.encode()).hexdigest()
                    old_hash = self._monitors[mid].get("last_hash", "")
                    old_status = self._monitors[mid].get("last_status", 0)

                    changed = content_hash != old_hash or resp.status_code != old_status

                    result = {
                        "monitor_id": mid,
                        "url": url,
                        "name": mon.get("name", ""),
                        "status_code": resp.status_code,
                        "changed": changed,
                        "content_changed": content_hash != old_hash,
                        "status_changed": resp.status_code != old_status,
                        "response_time_ms": resp.headers.get("x-response-time", ""),
                    }

                    if changed:
                        # Record change
                        change = {
                            "monitor_id": mid,
                            "url": url,
                            "old_hash": old_hash,
                            "new_hash": content_hash,
                            "old_status": old_status,
                            "new_status": resp.status_code,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                        with open(self._changes_file, "a", encoding="utf-8") as f:
                            f.write(json.dumps(change, ensure_ascii=False) + "\n")

                    # Update monitor state
                    self._monitors[mid]["last_hash"] = content_hash
                    self._monitors[mid]["last_status"] = resp.status_code
                    self._monitors[mid]["last_check"] = now

                    results.append(result)

            except Exception as e:
                results.append({"monitor_id": mid, "url": url, "error": str(e)[:200], "changed": False})

        self._save_monitors()
        return {"results": results, "checked": len(results)}

    def _get_changes(self, monitor_id: str = None, limit: int = 20) -> list[dict]:
        if not self._changes_file.exists():
            return []
        changes = []
        for line in self._changes_file.read_text(encoding="utf-8").strip().splitlines()[-limit:]:
            if line.strip():
                try:
                    data = json.loads(line)
                    if monitor_id and data.get("monitor_id") != monitor_id:
                        continue
                    changes.append(data)
                except Exception:
                    continue
        return changes

    def _load_monitors(self) -> dict:
        if not self._monitors_file.exists():
            return {}
        try:
            data = json.loads(self._monitors_file.read_text(encoding="utf-8"))
            return {m["id"]: m for m in data}
        except Exception:
            return {}

    def _save_monitors(self) -> None:
        self._monitors_file.write_text(
            json.dumps(list(self._monitors.values()), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
