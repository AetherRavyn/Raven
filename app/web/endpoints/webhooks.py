"""Webhooks dashboard endpoint — full CRUD implementation.

Routes:

* ``GET  /webhooks/list``   → list all webhooks
* ``POST /webhooks/test``   → test a webhook by sending a test payload
* ``POST /webhooks/add``    → add a new webhook
* ``POST /webhooks/remove`` → remove a webhook
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Mapping

import httpx

logger = logging.getLogger(__name__)


class WebhooksDashboardRouter:
    """Full webhook CRUD implementation."""

    def __init__(self, workspace_dir: str = "workspace") -> None:
        self._dir = Path(workspace_dir) / "webhooks"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "webhooks.json"
        self._routes: dict[str, Callable[..., dict[str, Any]]] = {
            "GET /webhooks/list": self.list_webhooks,
            "POST /webhooks/test": self.test_webhook,
            "POST /webhooks/add": self.add_webhook,
            "POST /webhooks/remove": self.remove_webhook,
        }

    @property
    def routes(self) -> Mapping[str, Callable[..., dict[str, Any]]]:
        return dict(self._routes)

    # ── Persistence ──────────────────────────────────────────────

    def _load(self) -> list[dict[str, Any]]:
        if not self._file.exists():
            return []
        try:
            return json.loads(self._file.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save(self, webhooks: list[dict[str, Any]]) -> None:
        self._file.write_text(
            json.dumps(webhooks, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ── Handlers ─────────────────────────────────────────────────

    def list_webhooks(self) -> dict[str, Any]:
        webhooks = self._load()
        return {"ok": True, "webhooks": webhooks, "count": len(webhooks)}

    def test_webhook(self, *, webhook_id: str) -> dict[str, Any]:
        webhooks = self._load()
        webhook = next((w for w in webhooks if w.get("id") == webhook_id), None)
        if not webhook:
            return {"ok": False, "error": f"Webhook '{webhook_id}' not found"}

        # Send test payload
        try:
            payload = {
                "event": "test",
                "timestamp": time.time(),
                "data": {"message": "Test webhook from RAVEN"},
            }
            with httpx.Client(timeout=10) as client:
                resp = client.post(webhook["url"], json=payload)
                return {
                    "ok": resp.status_code < 400,
                    "status_code": resp.status_code,
                    "response": resp.text[:500],
                }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def add_webhook(
        self,
        *,
        url: str,
        events: list[str] | None = None,
        secret: str | None = None,
        name: str = "",
    ) -> dict[str, Any]:
        webhooks = self._load()
        webhook_id = f"wh_{int(time.time())}"

        webhook = {
            "id": webhook_id,
            "name": name or f"Webhook {len(webhooks) + 1}",
            "url": url,
            "events": events or ["*"],
            "secret": secret,
            "enabled": True,
            "created_at": time.time(),
            "last_triggered": None,
            "trigger_count": 0,
        }
        webhooks.append(webhook)
        self._save(webhooks)
        return {"ok": True, "webhook": webhook}

    def remove_webhook(self, *, webhook_id: str) -> dict[str, Any]:
        webhooks = self._load()
        original_len = len(webhooks)
        webhooks = [w for w in webhooks if w.get("id") != webhook_id]
        if len(webhooks) < original_len:
            self._save(webhooks)
            return {"ok": True, "removed": webhook_id}
        return {"ok": False, "error": f"Webhook '{webhook_id}' not found"}

    async def trigger_webhooks(self, event: str, data: dict[str, Any]) -> int:
        """Trigger all webhooks subscribed to an event. Returns count triggered."""
        webhooks = self._load()
        triggered = 0

        for webhook in webhooks:
            if not webhook.get("enabled"):
                continue
            if "*" not in webhook.get("events", []) and event not in webhook.get("events", []):
                continue

            try:
                payload = {"event": event, "timestamp": time.time(), "data": data}
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = client.post(webhook["url"], json=payload)
                    if resp.status_code < 400:
                        triggered += 1
                        webhook["last_triggered"] = time.time()
                        webhook["trigger_count"] = webhook.get("trigger_count", 0) + 1
            except Exception as exc:
                logger.debug("Webhook trigger failed for %s: %s", webhook.get("id"), exc)

        if triggered > 0:
            self._save(webhooks)
        return triggered

    # ── Dispatch ────────────────────────────────────────────────────

    def dispatch(self, route: str, **kwargs: Any) -> dict[str, Any]:
        handler = self._routes.get(route)
        if handler is None:
            return {"ok": False, "error": "unknown_route", "route": route}
        try:
            return handler(**kwargs)
        except Exception as e:
            logger.exception("webhooks route %s raised: %s", route, e)
            return {"ok": False, "error": str(e), "route": route}


_router_singleton: WebhooksDashboardRouter | None = None


def get_webhooks_dashboard_router() -> WebhooksDashboardRouter:
    global _router_singleton
    if _router_singleton is None:
        _router_singleton = WebhooksDashboardRouter()
    return _router_singleton


def reset_webhooks_dashboard_router_for_tests() -> None:
    global _router_singleton
    _router_singleton = None
