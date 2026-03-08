# app/sensors/webhook_server.py
"""Minimal FastAPI webhook receiver for camera/sensor alerts from monitoring/."""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, Request
import uvicorn

logger = logging.getLogger(__name__)

app = FastAPI(title="SARAS Internal Webhook")

# Mount Prometheus /metrics endpoint
try:
    from prometheus_client import make_asgi_app as _make_asgi_app

    app.mount("/metrics", _make_asgi_app())
except ImportError:
    logger.debug("prometheus_client not installed — /metrics endpoint unavailable")


@app.post("/internal/camera-alert")
async def camera_alert(request: Request):
    data = await request.json()
    from app.sensors.camera_bridge import handle_camera_alert

    asyncio.create_task(handle_camera_alert(data))
    return {"status": "queued"}


@app.get("/health")
async def health():
    return {"status": "ok"}


async def run_webhook_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    """Run the webhook server until cancelled."""
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()
