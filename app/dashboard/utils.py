import os
import psutil
from datetime import datetime
from typing import Dict, Any


def get_system_mode() -> str:
    """Returns the current operating mode of the SARAS AI OS."""
    return "Autonomous" if os.getenv("AUTONOMY_MODE", "0") == "1" else "Interactive"


def get_daily_brief(user_id: str = "default") -> Dict[str, Any]:
    """Generates a high-level summary of the system state for the morning briefing."""
    return {
        "timestamp": datetime.now().isoformat(),
        "user_id": user_id,
        "mode": get_system_mode(),
        "cpu_usage": f"{psutil.cpu_percent()}%",
        "memory_usage": f"{psutil.virtual_memory().percent}%",
        "disk_usage": f"{psutil.disk_usage('/').percent}%",
        "active_edge_nodes": 0,
        "alerts": [],
    }
