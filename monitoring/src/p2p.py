import socket
import json
import threading
import logging
import time
from typing import Callable, Dict, Any, Optional

logger = logging.getLogger(__name__)

class P2PNetworkNode:
    """
    Decentralized Edge-to-Edge Network and Central ESP Hub utilizing UDP Broadcasting.
    """
    def __init__(self, node_id: str, bus=None):
        from monitoring.config.settings import p2p_config
        self.node_id = node_id
        self.bus = bus
        self.port = p2p_config.get("p2p_port", 54321)
        self.broadcast_ip = p2p_config.get("p2p_broadcast_ip", "<broadcast>")
        
        self.socket: Optional[socket.socket] = None
        self._running = False
        self._listener_thread: Optional[threading.Thread] = None
        self.callbacks: Dict[str, Callable[[Dict[str, Any]], None]] = {}
        
        # Register the ESP IoT bridge callback natively
        self.register_callback("iot_sensor", self._handle_iot_sensor)

    def _handle_iot_sensor(self, data: Dict[str, Any]):
        """Bridge ESP32 telemetry directly into the central Risk and Alert pipeline."""
        if not self.bus:
            logger.warning("P2P Node received IoT sensor data but has no MessageBus connected.")
            return
            
        # Example ESP payload: {"sensor_type": "door", "state": "opened", "device_id": "esp_main_door"}
        sensor_type = data.get("sensor_type", "unknown")
        
        # We wrap this simple IoT event into the complex `events.detected` schema
        # so RiskAnalysisService can score it.
        event_payload = {
            "event_id": f"iot_{sensor_type}_{int(time.time())}",
            "timestamp": time.time(),
            "camera_id": data.get("device_id", "external_sensor"),
            "location": data.get("location", "unknown_zone"),
            "track_id": None,
            "identity": "sensor",
            "confidence": 1.0,  # Hardware sensors are deterministic
            "anomaly_type": f"{sensor_type}_breach" if data.get("state") in ["opened", "tripped", "active"] else f"{sensor_type}_status",
            "severity": "MEDIUM", # Default risk for a basic trip, RiskService might bump it
            "description": f"IoT Sensor {sensor_type} state changed to {data.get('state')}",
            "frame_b64": None
        }
        
        self.bus.publish("events.detected", event_payload)
        logger.info(f"Bridged ESP IoT Sensor {sensor_type} -> events.detected")

    def dispatch_actuation(self, target_esp: str, command: str, value: Any = None):
        """Send a command from Central to a specific ESP (e.g. lock door)."""
        self.broadcast("actuation_command", {
            "target": target_esp,
            "command": command,
            "value": value
        })

    def start(self):
        if self._running:
            return
            
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Enable address reuse and broadcasting
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        try:
            # Bind to all interfaces to receive broadcasts
            self.socket.bind(('', self.port))
            self._running = True
            
            self._listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._listener_thread.start()
            
            logger.info(f"P2P Network Node '{self.node_id}' started on UDP port {self.port}")
            self.broadcast("discovery", {"status": "online"})
            
        except OSError as e:
            logger.error(f"Failed to bind P2P socket on port {self.port}: {e}")
            self.socket.close()

    def stop(self):
        self._running = False
        if self.socket:
            try:
                self.broadcast("discovery", {"status": "offline"})
            except:
                pass
            self.socket.close()
            
        if self._listener_thread and self._listener_thread.is_alive():
            self._listener_thread.join(timeout=2)
            
        logger.info(f"P2P Network Node '{self.node_id}' stopped")

    def register_callback(self, message_type: str, callback: Callable[[Dict[str, Any]], None]):
        """Register a handler function for specific P2P message types."""
        self.callbacks[message_type] = callback

    def broadcast(self, message_type: str, data: Dict[str, Any]):
        """Send a UDP broadcast to all peers on the sub-net."""
        if not self._running or not self.socket:
            return
            
        payload = {
            "type": message_type,
            "sender": self.node_id,
            "timestamp": time.time(),
            "data": data
        }
        
        try:
            message_bytes = json.dumps(payload).encode('utf-8')
            # 255.255.255.255 is the standard local broadcast address
            bcast = '255.255.255.255' if self.broadcast_ip == '<broadcast>' else self.broadcast_ip
            self.socket.sendto(message_bytes, (bcast, self.port))
            logger.debug(f"P2P broadcast sent: {message_type}")
        except Exception as e:
            logger.error(f"Error sending P2P broadcast: {e}")

    def share_identity(self, identity_id: str, embedding: list, match_name: str):
        """Immediately sync a newly recognized face embedding to other edges."""
        self.broadcast("sync_identity", {
            "identity_id": identity_id,
            "embedding": embedding,
            "match": match_name
        })

    def share_track(self, local_track_id: int, identity: str, bbox: list, confidence: float):
        """Share actively tracked objects so adjacent cameras can prep handoffs."""
        self.broadcast("sync_track", {
            "local_track": local_track_id,
            "identity": identity,
            "bbox": bbox,
            "confidence": confidence
        })
        
    def share_graph_update(self, node_a: str, edge: str, node_b: str, metadata: dict = None):
        """Broadcast Neo4j graph relationships so peers can trace behavior."""
        self.broadcast("graph_update", {
            "a": node_a,
            "a_type": "Node",
            "b": node_b,
            "b_type": "Node",
            "relationship": edge,
            "metadata": metadata or {}
        })

    def _listen_loop(self):
        while self._running:
            try:
                # 64k buffer (max UDP packet size)
                data, addr = self.socket.recvfrom(65535)
                
                if not data:
                    continue
                    
                payload = json.loads(data.decode('utf-8'))
                
                # Ignore our own broadcasts
                if payload.get("sender") == self.node_id:
                    continue
                    
                msg_type = payload.get("type", "unknown")
                msg_data = payload.get("data", {})
                
                logger.debug(f"P2P message received from {addr[0]}: {msg_type}")
                
                if msg_type in self.callbacks:
                    # Provide the payload data to the registered handler
                    self.callbacks[msg_type](msg_data)
                elif "all" in self.callbacks:
                    # Catch-all
                    self.callbacks["all"](payload)
                    
            except socket.error:
                # Happens when socket is closed during shutdown
                break
            except Exception as e:
                logger.error(f"Error handling P2P incoming message: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    
    node = P2PNetworkNode("test_edge_1")
    
    def on_discovery(data):
        print(f"Discovery payload: {data}")
        
    def on_sync(data):
        print(f"Sync received: {data['identity_id']} = {data['match']}")
        
    node.register_callback("discovery", on_discovery)
    node.register_callback("sync_identity", on_sync)
    
    node.start()
    
    try:
        # Simulate pushing an update to peers
        time.sleep(1)
        node.share_identity("unknown_101", [0.1, 0.2, -0.5], "John_Doe")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        node.stop()
