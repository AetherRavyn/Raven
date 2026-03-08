import json
import logging
import time
from datetime import datetime
from src.message_bus import MessageBus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_pipeline():
    bus = MessageBus()
    
    # 1. Simulate an event from AnomalyDetector (publishing to events.detected)
    dummy_event = {
        "event_id": f"test_weapon_cam1_{int(time.time())}",
        "timestamp": time.time(),
        "camera_id": "cam_1",
        "location": "main_entrance",
        "track_id": 999,
        "identity": "unknown_42",
        "confidence": 0.85,
        "anomaly_type": "weapon_detected",
        "severity": "CRITICAL",
        "description": "Test weapon detected",
        "frame_b64": "" # empty for test
    }
    
    logger.info("Publishing mock event to events.detected...")
    bus.publish("events.detected", dummy_event)
    
    # Wait a moment for services to process
    time.sleep(2)
    logger.info("Test complete. Check service logs for Risk Analysis, Storage, and Alert components.")
    bus.stop()

if __name__ == "__main__":
    test_pipeline()
