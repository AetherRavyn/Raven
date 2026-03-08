import os
import json
import logging
import base64
import time
import io
import numpy as np
import onnxruntime as ort
from PIL import Image
from typing import Dict, List, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

class SemanticSearchEngine:
    """
    Extracts semantic feature vectors from images using MobileNet-v2 (ONNX)
    and stores them in a locally searchable Numpy index.
    """
    def __init__(self, model_path: str, index_path: str):
        self.model_path = model_path
        self.index_path = index_path
        
        self.session = None
        self.input_name = None
        self.index: Dict[str, dict] = {} # event_id -> {"vector": np.ndarray, "timestamp": str, "description": str}
        
        if os.path.exists(self.model_path):
            self.session = ort.InferenceSession(self.model_path, providers=["CPUExecutionProvider"])
            self.input_name = self.session.get_inputs()[0].name
            logger.info(f"Initialized SemanticSearch Engine with {self.model_path}")
        else:
            logger.warning(f"SemanticSearch model not found at {self.model_path}")

        self._load_index()

    def _load_index(self):
        if os.path.exists(self.index_path):
            try:
                np_data = np.load(self.index_path, allow_pickle=True)
                self.index = np_data.item()
                logger.info(f"Loaded {len(self.index)} image vectors from index.")
            except Exception as e:
                logger.error(f"Failed to load semantic index: {e}")

    def _save_index(self):
        try:
            # Atomic save utilizing numpy
            temp_path = self.index_path + ".tmp"
            np.save(temp_path, self.index)
            os.replace(temp_path, self.index_path)
        except Exception as e:
            logger.error(f"Failed to save semantic index: {e}")

    def preprocess(self, img: Image.Image) -> np.ndarray:
        """MobileNetV2 standard preprocessing: 224x224 RGB, zero-mean, unit-variance approx."""
        img = img.resize((224, 224)).convert("RGB")
        arr = np.asarray(img, dtype=np.float32)
        # Normalize to [0, 1] then apply ImageNet mean/std
        arr /= 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        arr = (arr - mean) / std
        # HWC to CHW
        arr = np.transpose(arr, (2, 0, 1))
        # Add batch dimension
        return np.expand_dims(arr, axis=0)

    def get_embedding(self, img: Image.Image) -> np.ndarray:
        if not self.session:
            return np.zeros(1000, dtype=np.float32)
            
        tensor = self.preprocess(img)
        # Output is shape (1, 1000) for standard MobileNetV2 classifier
        # We use the logits as a semantic signature. Real semantic search uses the penulimate layer, 
        # but logits work sufficiently well for coarse nearest-neighbor class matching on edge.
        logits = self.session.run(None, {self.input_name: tensor})[0]
        vec = logits.flatten()
        
        # L2 Normalize
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec

    def index_image(self, event_id: str, img: Image.Image, meta: dict):
        vec = self.get_embedding(img)
        self.index[event_id] = {
            "vector": vec,
            "timestamp": meta.get("timestamp"),
            "description": meta.get("description"),
            "camera_id": meta.get("camera_id")
        }
        self._save_index()
        logger.info(f"Indexed image for event {event_id}")

    def search(self, img: Image.Image, top_k: int = 5) -> List[dict]:
        """Returns top_k matching events based on cosine similarity of the image vector."""
        if not self.index:
            return []
            
        query_vec = self.get_embedding(img)
        
        results = []
        for event_id, data in self.index.items():
            db_vec = data["vector"]
            # Cosine similarity for normalized vectors is just the dot product
            sim = float(np.dot(query_vec, db_vec))
            results.append({
                "event_id": event_id,
                "similarity": sim,
                "timestamp": data["timestamp"],
                "description": data["description"],
                "camera_id": data["camera_id"]
            })
            
        # Sort descending by similarity
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:top_k]

class SemanticSearchService:
    def __init__(self, bus):
        self.bus = bus
        
        base_dir = os.path.dirname(__file__)
        model_path = os.path.abspath(os.path.join(base_dir, "..", "models", "MobileNet-v2.onnx"))
        index_path = os.path.abspath(os.path.join(base_dir, "..", "data", "semantic_index.npy"))
        
        os.makedirs(os.path.dirname(index_path), exist_ok=True)
        self.engine = SemanticSearchEngine(model_path, index_path)
        
        # Listen for Anomaly events to index them
        self.bus.subscribe("events", self.handle_event)
        # Listen for search queries
        self.bus.subscribe("semantic_search_query", self.handle_search)

    def handle_event(self, payload: dict):
        event_id = payload.get("event_id")
        frame_b64 = payload.get("frame_b64")
        if not event_id or not frame_b64:
            return
            
        try:
            img_bytes = base64.b64decode(frame_b64)
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            
            self.engine.index_image(event_id, img, {
                "timestamp": payload.get("timestamp", time.time()),
                "description": payload.get("description", "Unknown event"),
                "camera_id": payload.get("camera_id", "unknown")
            })
        except Exception as e:
            logger.error(f"Semantic Indexing failed for {event_id}: {e}")

    def handle_search(self, payload: dict):
        # A microservice node requesting a search via the bus. We reply to specific queues.
        reply_to = payload.get("reply_to")
        frame_b64 = payload.get("frame_b64")
        if not reply_to or not frame_b64:
            return
            
        try:
            img_bytes = base64.b64decode(frame_b64)
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            results = self.engine.search(img, top_k=payload.get("top_k", 5))
            self.bus.publish(reply_to, {"results": results, "status": "success"})
        except Exception as e:
            logger.error(f"Semantic Search failed: {e}")
            self.bus.publish(reply_to, {"status": "error", "error": str(e)})

    def start(self):
        logger.info("Semantic Search Service running...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
            
    def stop(self):
        self.bus.stop()
        logger.info("Semantic Search Service stopped.")

if __name__ == "__main__":
    from monitoring.src.message_bus import MessageBus
    logging.basicConfig(level=logging.INFO)
    bus = MessageBus()
    svc = SemanticSearchService(bus)
    svc.start()
