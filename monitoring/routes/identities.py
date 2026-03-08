"""Identity management routes — identify, register, promote, list visitors."""

import io
import logging

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image

from monitoring.src import state

logger = logging.getLogger(__name__)
router = APIRouter(tags=["identities"])


@router.get("/api/visitors")
async def get_visitors():
    if not state.reid:
        raise HTTPException(503, "ReID not ready")
    known = [{"id": k, "type": "known"} for k in state.reid.known_db.keys()]
    unknown = [
        {
            "id": uid,
            "label": m["label"],
            "visit_count": m["visit_count"],
            "first_seen": m.get("first_seen", ""),
            "last_seen": m.get("last_seen", ""),
            "type": "unknown",
        }
        for uid, m in state.reid.unknown_db.items()
    ]
    return JSONResponse({"known": known, "unknown": unknown})


@router.post("/api/identity")
async def add_identity(name: str = Form(...), file: UploadFile = File(...)):
    if not state.reid:
        raise HTTPException(503, "ReID not ready")
    raw = await file.read()
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    result = state.reid.add_identity(np.array(img), name)
    return JSONResponse({"result": result})


@router.post("/api/promote/{uid}")
async def promote(uid: str, name: str = Form(...)):
    if not state.reid:
        raise HTTPException(503, "ReID not ready")
    result = state.reid.promote_unknown(uid, name)
    return JSONResponse({"result": result})


@router.post("/api/identify")
async def identify(file: UploadFile = File(...)):
    if not state.reid:
        raise HTTPException(503, "ReID not ready")
    raw = await file.read()
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    label, score = state.reid.match(np.array(img), camera_id="web_upload")
    return JSONResponse({"label": label, "score": round(float(score), 4)})
