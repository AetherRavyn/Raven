"""SSE live events and event history routes."""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.requests import Request

from monitoring.src import state

logger = logging.getLogger(__name__)
router = APIRouter(tags=["events"])


@router.get("/events/live")
async def sse_events(request: Request):
    async def generator():
        try:
            yield "retry: 1000\n\n"
            while not state._shutdown_event.is_set():
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(state._sse_queue.get(), timeout=2)
                    yield f"data: {json.dumps(ev)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(generator(), media_type="text/event-stream")


@router.get("/events/history")
async def get_history(camera_id: Optional[str] = None, risk_level: Optional[str] = None, event_type: Optional[str] = None, limit: int = 100):
    if not state.db:
        raise HTTPException(503, "DB not ready")
    events = state.db.sqlite.get_events(camera_id=camera_id, risk_level=risk_level, event_type=event_type, limit=limit)
    for e in events:
        if isinstance(e.get("timestamp"), datetime):
            e["timestamp"] = e["timestamp"].isoformat()
        if isinstance(e.get("created_at"), datetime):
            e["created_at"] = e["created_at"].isoformat()
    return JSONResponse({"events": events})
