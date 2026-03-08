import os
from pathlib import Path
from typing import Dict

import yaml

# Try YOLO (optional)
try:
    from ultralytics import YOLO

    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False


def load_yaml_config(name: str, folder: str = "config") -> Dict:
    path = Path(folder) / name
    if not path.exists():
        # Fallback for when running from different directories
        # Try looking relative to this file
        current_dir = Path(__file__).parent
        path = current_dir / name

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r") as file:
        return yaml.safe_load(file) or {}


class Config:
    def __init__(self, folder: str = "config"):
        self.folder = folder
        self._cache = {}

    def get(self, name: str) -> Dict:
        if name not in self._cache:
            self._cache[name] = load_yaml_config(name, self.folder)
        return self._cache[name]


config = Config()
db_config = config.get("dbconfig.yaml")
camera_config = config.get("cameras.yaml")
prompts_config = config.get("prompts.yaml")
zone_config = config.get("zones.yaml")
threshold_config = config.get("thresholds.yaml")

# Global Settings Exports
p2p_config = threshold_config.get("network", {})
scheduler_config = threshold_config.get("scheduler", {})
llm_config = threshold_config.get("higher_intelligence", {})



