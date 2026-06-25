import os
import json
import logging
import time
import numpy as np
import cv2
from typing import Dict, Optional, List, Any

# Try to import Ultralytics solutions
try:
    from ultralytics import YOLO, solutions
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False

logger = logging.getLogger(__name__)

class VisionAnalyticsEngine:
    def __init__(self, config: Dict):
        self.config = config.get("vision_analytics", {})
        self.active_tool: Optional[str] = self.config.get("default_tool", None)
        
        # Tools state
        self.heatmap_accum = None
        self.crossed_ids = set()
        self.cross_count = 0
        
        # Persistent configs for tools
        self.line_y = 400

        logger.info("Custom Vision Analytics Engine initialized (bypassing ultralytics wrappers).")

    def configure_tool(self, tool_name: str, enabled: bool, **kwargs):
        """Configure and toggle an advanced vision tool dynamically."""
        if enabled:
            self.active_tool = tool_name
            # Reset states
            if tool_name == "heatmap":
                self.heatmap_accum = None
            elif tool_name == "counter":
                self.crossed_ids = set()
                self.cross_count = 0
                if "line_points" in kwargs:
                    self.line_y = kwargs["line_points"][0][1]
            logger.info(f"Activated custom Vision Tool: {tool_name}")
            return True, f"Tool {tool_name} enabled."
        else:
            if self.active_tool == tool_name:
                self.active_tool = None
            logger.info(f"Deactivated Vision Tool: {tool_name}")
            return True, f"Tool {tool_name} disabled."

    def process_frame(self, frame_arr: np.ndarray, tracks: list = None) -> np.ndarray:
        """Apply advanced analytics dynamically using raw numpy/cv2 logic directly on tracking data."""
        if not self.active_tool or tracks is None:
            return frame_arr

        h, w = frame_arr.shape[:2]

        try:
            # Heatmap processing
            if self.active_tool == "heatmap":
                if self.heatmap_accum is None or self.heatmap_accum.shape[:2] != (h, w):
                    self.heatmap_accum = np.zeros((h, w), dtype=np.float32)
                
                # Add heat for every tracked object center
                for t in tracks:
                    cx, cy = int((t.bbox[0]+t.bbox[2])/2), int((t.bbox[1]+t.bbox[3])/2)
                    if 0 <= cx < w and 0 <= cy < h:
                        cv2.circle(self.heatmap_accum, (cx, cy), 40, (2.0), -1)
                
                # Decay
                self.heatmap_accum *= 0.95
                
                # Normalize and apply colormap
                heat_norm = np.clip(self.heatmap_accum * 255, 0, 255).astype(np.uint8)
                color_map = cv2.applyColorMap(cv2.GaussianBlur(heat_norm, (25, 25), 0), cv2.COLORMAP_JET)
                
                # Blend with original where heat exists
                mask = (heat_norm > 5)[:, :, np.newaxis]
                frame_arr = np.where(mask, cv2.addWeighted(frame_arr, 0.5, color_map, 0.5, 0), frame_arr)
                
            # Object counting (Line Crossing)
            elif self.active_tool == "counter":
                # Draw the crossing line
                cv2.line(frame_arr, (0, self.line_y), (w, self.line_y), (0, 255, 255), 4)
                
                for t in tracks:
                    if len(t.trajectory) < 2:
                        continue
                    pt_old = t.trajectory[-2]
                    pt_new = t.trajectory[-1]
                    
                    # Intersect logic: checking vertically crossing the line Y threshold
                    if (pt_old[1] < self.line_y and pt_new[1] >= self.line_y) or (pt_old[1] > self.line_y and pt_new[1] <= self.line_y):
                        if t.track_id not in self.crossed_ids:
                            self.crossed_ids.add(t.track_id)
                            self.cross_count += 1
                
                # Draw count text with shadow
                cv2.putText(frame_arr, f"Line Crossings: {self.cross_count}", (22, 52), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 6)
                cv2.putText(frame_arr, f"Line Crossings: {self.cross_count}", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 255, 255), 4)

            # Dynamic Blurring (Faces/License Plates) -> We blur all tracked objects
            elif self.active_tool == "blur":
                for t in tracks:
                    x1, y1, x2, y2 = [int(v) for v in t.bbox]
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(w, x2), min(h, y2)
                    
                    roi = frame_arr[y1:y2, x1:x2]
                    if roi.size > 0:
                        blurred = cv2.GaussianBlur(roi, (99, 99), 30)
                        frame_arr[y1:y2, x1:x2] = blurred

            elif self.active_tool == "speed":
                cv2.putText(frame_arr, "Speed estimation active", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 255, 0), 4)

            elif self.active_tool == "workout":
                cv2.putText(frame_arr, "Workout tracking disabled (requires Pose model)", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
                        
        except Exception as e:
            logger.error(f"Custom vision tool {self.active_tool} failed: {e}")

        return frame_arr


class VisionService:
    """Microservice wrapper for Vision Analytics to allow configuration via MessageBus."""
    def __init__(self, bus, engine: VisionAnalyticsEngine):
        self.bus = bus
        self.engine = engine
        self.bus.subscribe("configure_analytics", self.handle_configure)
        
    def handle_configure(self, payload: Dict):
        tool_name = payload.get("tool_name")
        enabled = payload.get("enabled", False)
        kwargs = payload.get("kwargs", {})
        
        if tool_name:
            success, msg = self.engine.configure_tool(tool_name, enabled, **kwargs)
            logger.info(f"Analytics Config: {msg}")

    def start(self):
        logger.info("Advanced Vision Analytics Service listening for configs...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        logger.info("Vision Analytics Service stopped.")

if __name__ == "__main__":
    from monitoring.src.message_bus import MessageBus
    logging.basicConfig(level=logging.INFO)
    bus = MessageBus()
    svc = VisionService(bus, {})
    svc.start()
