"""Vision analytics configuration and semantic search routes."""

import io
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image

from monitoring.src import state

logger = logging.getLogger(__name__)
router = APIRouter(tags=["analytics"])


@router.post("/api/analytics/configure")
async def configure_analytics(tool_name: str = Form(...), enabled: str = Form(...)):
    if state.bus:
        is_enabled = enabled.lower() == "true"
        state.bus.publish("configure_analytics", {"tool_name": tool_name, "enabled": is_enabled})
        return JSONResponse({"status": f"{tool_name} {'on' if is_enabled else 'off'}"})
    raise HTTPException(503, "Bus not ready")


@router.post("/api/search/semantic")
async def semantic_search_api(file: UploadFile = File(...), top_k: int = Form(5)):
    if not state.semantic_search_engine:
        raise HTTPException(503, "Semantic Search not ready")
    raw = await file.read()
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    results = state.semantic_search_engine.search(img, top_k=top_k)
    return JSONResponse({"results": results})
