import cv2
import numpy as np
import torch
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    bbox: List[float]
    confidence: float
    class_id: int
    class_name: str
    mask: Optional[np.ndarray] = None


class YOLODetector:
    def __init__(self, config: Dict):
        self.config = config
        self.model_path = config.get("model_path", "yolov8n.pt")
        self.conf_threshold = config.get("conf_threshold", 0.25)
        self.iou_threshold = config.get("iou_threshold", 0.45)
        self.device = config.get(
            "device", "cuda" if torch.cuda.is_available() else "cpu"
        )
        self.half_precision = config.get("half_precision", True)

        self.class_names = {
            0: "person",
            1: "bicycle",
            2: "car",
            3: "motorcycle",
            4: "airplane",
            5: "bus",
            6: "train",
            7: "truck",
            8: "boat",
            9: "traffic light",
            10: "fire hydrant",
            11: "stop sign",
            12: "parking meter",
            13: "bench",
            14: "bird",
            15: "cat",
            16: "dog",
            17: "horse",
            18: "sheep",
            19: "cow",
            20: "elephant",
            21: "bear",
            22: "zebra",
            23: "giraffe",
            24: "backpack",
            25: "umbrella",
            26: "handbag",
            27: "tie",
            28: "suitcase",
            29: "frisbee",
            30: "skis",
            31: "snowboard",
            32: "sports ball",
            33: "kite",
            34: "baseball bat",
            35: "baseball glove",
            36: "skateboard",
            37: "surfboard",
            38: "tennis racket",
            39: "bottle",
            40: "wine glass",
            41: "cup",
            42: "fork",
            43: "knife",
            44: "spoon",
            45: "bowl",
            46: "banana",
            47: "apple",
            48: "sandwich",
            49: "orange",
            50: "broccoli",
            51: "carrot",
            52: "hot dog",
            53: "pizza",
            54: "donut",
            55: "cake",
            56: "chair",
            57: "couch",
            58: "potted plant",
            59: "bed",
            60: "dining table",
            61: "toilet",
            62: "tv",
            63: "laptop",
            64: "mouse",
            65: "remote",
            66: "keyboard",
            67: "cell phone",
            68: "microwave",
            69: "oven",
            70: "toaster",
            71: "sink",
            72: "refrigerator",
            73: "book",
            74: "clock",
            75: "vase",
            76: "scissors",
            77: "teddy bear",
            78: "hair drier",
            79: "toothbrush",
        }

        self.filter_classes = config.get(
            "classes",
            [
                "person",
                "car",
                "truck",
                "bus",
                "motorcycle",
                "bicycle",
                "dog",
                "bag",
                "suitcase",
            ],
        )
        self.class_ids_to_detect = [
            k for k, v in self.class_names.items() if v in self.filter_classes
        ]

        self._load_model()

    def _load_model(self):
        try:
            from ultralytics import YOLO

            self.model = YOLO(self.model_path)
            self.model.to(self.device)
            # NOTE: Don't call model.half() here — it breaks PIL/RGB input.
            # Instead, pass half=True in the predict call so ultralytics
            # handles both model and input dtype alignment.
            logger.info(f"YOLO model loaded on {self.device}")
        except ImportError:
            logger.warning("Ultralytics not installed, using mock detection")
            self.model = None

    def detect(self, frame: np.ndarray) -> List[Detection]:
        if self.model is None:
            return self._mock_detect(frame)

        # Wrap as PIL so ultralytics treats it as RGB (numpy is assumed BGR)
        from PIL import Image as _PILImage
        source = _PILImage.fromarray(frame) if isinstance(frame, np.ndarray) else frame

        results = self.model(
            source,
            conf=self.conf_threshold,
            iou=self.iou_threshold,
            device=self.device,
            half=self.half_precision and self.device == "cuda",
            verbose=False,
        )

        detections = []
        for result in results:
            boxes = result.boxes
            for i in range(len(boxes)):
                box = boxes[i]
                class_id = int(box.cls[0])

                if class_id not in self.class_ids_to_detect:
                    continue

                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                conf = float(box.conf[0])
                class_name = self.class_names.get(class_id, "unknown")

                detections.append(
                    Detection(
                        bbox=[float(x1), float(y1), float(x2), float(y2)],
                        confidence=conf,
                        class_id=class_id,
                        class_name=class_name,
                        mask=(
                            result.masks[i].data.cpu().numpy()
                            if result.masks is not None
                            else None
                        ),
                    )
                )

        return detections

    def _mock_detect(self, frame: np.ndarray) -> List[Detection]:
        h, w = frame.shape[:2]
        detections = []

        if np.random.random() > 0.7:
            x1, y1 = w * 0.3, h * 0.4
            x2, y2 = x1 + 80, y1 + 180
            detections.append(
                Detection(
                    bbox=[x1, y1, x2, y2],
                    confidence=0.85,
                    class_id=0,
                    class_name="person",
                )
            )

        return detections

    def detect_with_pose(
        self, frame: np.ndarray
    ) -> Tuple[List[Detection], Optional[Dict]]:
        if self.model is None:
            return self.detect(frame), None

        try:
            from ultralytics import YOLO

            pose_model = YOLO("yolov8n-pose.pt")
            results = pose_model(
                frame, conf=self.conf_threshold, device=self.device, verbose=False
            )

            pose_data = None
            if results[0].keypoints is not None:
                kpts = results[0].keypoints.data.cpu().numpy()
                pose_data = {"keypoints": kpts}

            return self.detect(frame), pose_data
        except Exception as e:
            logger.error(f"Pose detection error: {e}")
            return self.detect(frame), None

    def filter_by_roi(
        self, detections: List[Detection], roi_points: List[List[int]]
    ) -> List[Detection]:
        if not roi_points:
            return detections

        roi_mask = np.zeros((1000, 1000), dtype=np.uint8)
        roi_array = np.array(roi_points, dtype=np.int32)
        cv2.fillPoly(roi_mask, [roi_array], 1)

        filtered = []
        for det in detections:
            x1, y1, x2, y2 = det.bbox
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2

            if roi_mask.shape[0] > cy and roi_mask.shape[1] > cx:
                if roi_mask[int(cy), int(cx)] == 1:
                    filtered.append(det)

        return filtered

    def draw_detections(
        self, frame: np.ndarray, detections: List[Detection]
    ) -> np.ndarray:
        result = frame.copy()

        for det in detections:
            x1, y1, x2, y2 = map(int, det.bbox)
            color = (0, 255, 0) if det.class_name == "person" else (255, 0, 0)

            cv2.rectangle(result, (x1, y1), (x2, y2), color, 2)

            label = f"{det.class_name}: {det.confidence:.2f}"
            cv2.putText(
                result, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2
            )

        return result


class YOLODetectionService:
    """Microservice wrapper for YOLODetector using Redis MessageBus."""

    def __init__(self, bus, config: Dict = None):
        self.bus = bus
        self.detector = YOLODetector(config or {})
        self.bus.subscribe("raw_frames", self.process_frame)

    def process_frame(self, payload):
        try:
            frame_b64 = payload.get("frame_b64")
            if not frame_b64:
                return

            import base64
            import io
            from PIL import Image

            # Decode base64 to numpy array using PIL
            frame_bytes = base64.b64decode(frame_b64)
            image = Image.open(io.BytesIO(frame_bytes))
            frame = np.array(image)

            if frame is None:
                return

            # Run YOLO detection
            detections = self.detector.detect(frame)

            # Publish detections
            detection_payload = {
                "camera_id": payload["camera_id"],
                "camera_name": payload["camera_name"],
                "location": payload["location"],
                "timestamp": payload["timestamp"],
                "frame_b64": frame_b64,
                "detections": [
                    {
                        "class_id": d.class_id,
                        "class_name": d.class_name,
                        "confidence": d.confidence,
                        "bbox": d.bbox,
                    }
                    for d in detections
                ],
            }
            self.bus.publish("detections", detection_payload)
            logger.info(
                f"Published {len(detections)} detections for {payload['camera_id']}"
            )
        except Exception as e:
            logger.error(f"Error processing frame: {e}")

    def start(self):
        import time

        logger.info("YOLO Detection Service started")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        self.bus.stop()
        logger.info("YOLO Detection Service stopped")


if __name__ == "__main__":
    from monitoring.src.message_bus import MessageBus

    logging.basicConfig(level=logging.INFO)
    bus = MessageBus()
    service = YOLODetectionService(bus)
    service.start()
