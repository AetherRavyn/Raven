"""HTTP Transport — serve A2A modules over HTTP.

Enables external systems to call Raven modules via REST API.
Uses FastAPI (already in the project) for the HTTP layer.

Each registered module gets an endpoint:
  POST /module/{module_name}/{method_name}
  Body: JSON-RPC-style message
  Response: JSON-RPC-style response
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def create_module_routes(app: Any = None) -> Any:
    """Create FastAPI routes for all A2A modules.

    If app is None, creates a new FastAPI app.
    Returns the app with routes registered.
    """
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from raven_protocol import get_registry, Message

    if app is None:
        app = FastAPI(title="Raven Module API", version="1.0.0")

    @app.post("/module/{module_name}/{method_name}")
    async def call_module(module_name: str, method_name: str, request: Request) -> JSONResponse:
        """Call an A2A module method via HTTP."""
        try:
            body = await request.json()
        except Exception:
            body = {}

        # Build A2A message
        full_method = f"{module_name}.{method_name}"
        message = Message.request(
            method=full_method,
            params=body,
            source="http",
            target=module_name,
        )

        # Route through registry
        registry = get_registry()
        response = await registry.route_message(message)

        return JSONResponse(content=response.to_dict())

    @app.get("/modules")
    async def list_modules() -> JSONResponse:
        """List all registered A2A modules and their skills."""
        registry = get_registry()
        return JSONResponse(content=registry.get_registry_summary())

    @app.get("/modules/{module_name}")
    async def get_module(module_name: str) -> JSONResponse:
        """Get a specific module's Agent Card."""
        registry = get_registry()
        card = registry.get_card(module_name)
        if card is None:
            return JSONResponse(
                content={"error": f"Module '{module_name}' not found"},
                status_code=404,
            )
        return JSONResponse(content=card.to_dict())

    @app.get("/modules/discover/{tags}")
    async def discover_modules(tags: str) -> JSONResponse:
        """Discover modules by comma-separated tags."""
        registry = get_registry()
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        cards = registry.find_modules_by_skill(tag_list)
        return JSONResponse(content={
            "modules": [c.to_dict() for c in cards],
            "count": len(cards),
        })

    @app.get("/health")
    async def health() -> JSONResponse:
        """Health check endpoint."""
        registry = get_registry()
        summary = registry.get_registry_summary()
        return JSONResponse(content={
            "status": "healthy",
            "modules_registered": summary["total_modules"],
        })

    logger.info("Module API routes registered")
    return app
