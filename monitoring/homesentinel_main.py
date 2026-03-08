import asyncio
import json
import logging
import signal
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Optional

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from monitoring.src.homesentinel import CameraConfig, HomeSentinelSystem

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


class CameraCreateRequest(BaseModel):
    camera_id: str
    camera_name: str
    location: str
    protocol: str
    stream_url: str
    enabled: bool = True


def _load_yaml(path: Path) -> Dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_system_config() -> Dict:
    base = Path(__file__).resolve().parent
    cameras_cfg = _load_yaml(base / "config" / "cameras.yaml")
    thresholds_cfg = _load_yaml(base / "config" / "thresholds.yaml")

    merged = {}
    merged.update(cameras_cfg)
    merged["thresholds"] = thresholds_cfg.get("thresholds", {}) | {
        "pose": thresholds_cfg.get("pose", {})
    }

    merged.setdefault(
        "alerts",
        {
            "webhook_url": "",
            "telegram_token": "",
            "telegram_chat_id": "",
        },
    )
    merged.setdefault("captures_dir", str(base / "captures"))

    return merged


system: Optional[HomeSentinelSystem] = None
shutdown_event = asyncio.Event()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global system
    cfg = load_system_config()
    system = HomeSentinelSystem(cfg)
    system.start()
    logger.info("HomeSentinel started with %d camera(s)", len(system.list_cameras()))
    yield
    if system:
        system.stop()


app = FastAPI(title="HomeSentinel AI", version="2.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "HomeSentinel AI"}


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    template_path = Path(__file__).resolve().parent / "templates" / "dashboard.html"
    if not template_path.exists():
        return HTMLResponse(content="Dashboard template not found", status_code=404)

    with open(template_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    return HTMLResponse(content=html_content)


@app.get("/cameras")
async def list_cameras():
    if not system:
        raise HTTPException(503, "System not ready")
    return {"cameras": system.list_cameras()}


@app.post("/cameras")
async def add_camera(req: CameraCreateRequest):
    if not system:
        raise HTTPException(503, "System not ready")
    cam = CameraConfig(
        camera_id=req.camera_id,
        camera_name=req.camera_name,
        location=req.location,
        protocol=req.protocol,
        stream_url=req.stream_url,
        enabled=req.enabled,
    )
    system.add_camera(cam)
    return JSONResponse({"status": "added", "camera": req.model_dump()})


@app.delete("/cameras/{camera_id}")
async def remove_camera(camera_id: str):
    if not system:
        raise HTTPException(503, "System not ready")
    system.remove_camera(camera_id)
    return {"status": "removed", "camera_id": camera_id}


@app.get("/events/recent")
async def recent_events(limit: int = 100):
    if not system:
        raise HTTPException(503, "System not ready")
    return {"events": system.get_recent_events(limit=limit)}


# Compatibility endpoints for old UI
@app.get("/events")
async def old_events(limit: int = 100):
    if not system:
        raise HTTPException(503, "System not ready")
    events = system.get_recent_events(limit=limit)
    # Map to old format if needed, or just return as is
    return {"events": events}


@app.get("/stream")
async def old_stream(request: Request):
    if not system:
        raise HTTPException(503, "System not ready")

    # Just pick the first camera for the old /stream endpoint
    cameras = system.list_cameras()
    if not cameras:
        raise HTTPException(404, "No cameras configured")

    camera_id = cameras[0]["camera_id"]
    return await video(camera_id, request)


@app.get("/video/{camera_id}")
async def video(camera_id: str, request: Request):
    if not system:
        raise HTTPException(503, "System not ready")

    async def generator():
        while True:
            if await request.is_disconnected():
                break
            frame = system.get_latest_jpeg(camera_id)
            if frame:
                yield (
                    b"--frame\r\n" b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                )
            await asyncio.sleep(0.06)

    return StreamingResponse(
        generator(), media_type="multipart/x-mixed-replace; boundary=frame"
    )


def _force_exit(signum, frame):
    logger.info("Force shutdown signal received")
    if system:
        try:
            system.stop()
        except Exception:
            pass
    raise SystemExit(0)


signal.signal(signal.SIGINT, _force_exit)
signal.signal(signal.SIGTERM, _force_exit)


if __name__ == "__main__":
    uvicorn.run(
        "monitoring.homesentinel_main:app", host="0.0.0.0", port=8100, reload=False
    )
