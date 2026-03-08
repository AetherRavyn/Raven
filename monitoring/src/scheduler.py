import time
import logging
import threading
from typing import Dict, Any, Optional

try:
    import psutil
except ImportError:
    psutil = None

logger = logging.getLogger(__name__)

class EdgeAIScheduler:
    """
    Monitors system resources (CPU, RAM) and regulates processing intensity
    (FPS limits, resolution scaling) to ensure stability on edge nodes.
    """
    
    def __init__(self, bus=None, config: Dict[str, Any] = None):
        from monitoring.config.settings import scheduler_config
        self.bus = bus
        self.config = config or scheduler_config
        
        self.max_cpu_percent = self.config.get("max_cpu_percent", 75.0)
        self.max_ram_gb = self.config.get("max_ram_gb", 6.0)
        self.check_interval = self.config.get("check_interval_seconds", 5)
        
        self.current_state = "NORMAL" # NORMAL, THROTTLED, CRITICAL
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if not psutil:
            logger.warning("psutil not installed. EdgeAIScheduler cannot monitor resources.")
            return

        if self._running:
            return
            
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info(f"Edge AI Scheduler started (Max CPU: {self.max_cpu_percent}%, Max RAM: {self.max_ram_gb}GB)")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        logger.info("Edge AI Scheduler stopped")

    def _monitor_loop(self):
        """Continuously checks system resources and publishes state changes."""
        while self._running:
            try:
                cpu_usage = psutil.cpu_percent(interval=1.0)
                mem = psutil.virtual_memory()
                ram_used_gb = mem.used / (1024 ** 3)
                
                new_state = "NORMAL"
                
                # Critical condition: RAM critically high or CPU pinned
                if ram_used_gb > self.max_ram_gb or cpu_usage > 90.0:
                    new_state = "CRITICAL"
                # Throttled condition: Approaching limits
                elif cpu_usage > self.max_cpu_percent or ram_used_gb > (self.max_ram_gb * 0.85):
                    new_state = "THROTTLED"

                if new_state != self.current_state:
                    logger.warning(f"Resource State Change: {self.current_state} -> {new_state} | CPU: {cpu_usage}% RAM: {ram_used_gb:.1f}GB")
                    self.current_state = new_state
                    self._publish_state()
                    
            except Exception as e:
                logger.error(f"Error in scheduler monitor loop: {e}")
                
            time.sleep(self.check_interval)

    def _publish_state(self):
        """Notifies other components to adapt their workloads via the message bus."""
        if not self.bus:
            return
            
        payload = {
            "state": self.current_state,
            "timestamp": time.time(),
            "recommendations": self._get_recommendations(self.current_state)
        }
        
        self.bus.publish("system.state", payload)

    def _get_recommendations(self, state: str) -> Dict[str, Any]:
        if state == "CRITICAL":
            return {
                "max_fps": 1,
                "resolution": "320x240",
                "enable_tracking": False, 
                "enable_reid": False
            }
        elif state == "THROTTLED":
            return {
                "max_fps": 5,
                "resolution": "640x480",
                "enable_tracking": True,
                "enable_reid": False # Disable heavy embeds
            }
        else: # NORMAL
            return {
                "max_fps": 15,
                "resolution": "1280x720",
                "enable_tracking": True,
                "enable_reid": True
            }

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from monitoring.src.message_bus import MessageBus
    bus = MessageBus()
    scheduler = EdgeAIScheduler(bus)
    scheduler.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        scheduler.stop()
