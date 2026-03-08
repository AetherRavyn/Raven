import asyncio
import io
import json
import logging
from typing import Any, Dict

from mcp.server.fastmcp import FastMCP
from mcp.types import ResourceTemplate

# Import SARAS configuration and components
from monitoring.config.settings import llm_config
from monitoring.src.message_bus import MessageBus

logger = logging.getLogger(__name__)

# Create the MCP Server instance
mcp_server = FastMCP("SARAS_Higher_Intelligence_Uplink")

# We hold a global reference to the message bus so MCP tools can query the living system
_global_bus = None
_recent_critical_events = []

def init_llm_uplink(bus: MessageBus):
    """Initializes the MCP server context with the live message bus."""
    global _global_bus
    _global_bus = bus
    logger.info("SARAS Higher Intelligence Uplink (MCP) Initialized.")

    # Subscribe to alerts to catch CRITICAL events for potential proactive push
    bus.subscribe("alerts.generated", _handle_alerts)


def _handle_alerts(payload: Dict[str, Any]):
    """Stores recent critical events and handles proactive escalation."""
    global _recent_critical_events
    severity = payload.get("severity", "LOW")
    
    if severity == "CRITICAL" and llm_config.get("escalate_on_critical", True):
        # Keep a rolling window of the last 5 critical events
        _recent_critical_events.insert(0, payload)
        if len(_recent_critical_events) > 5:
            _recent_critical_events.pop()
            
        logger.warning(f"[MCP] Escalate queued for CRITICAL event: {payload.get('event_id')}")
        # In a fully integrated MCP client environment, this is where we'd trigger 
        # a notification or a webhook to wake up the LLM agent.

# ─── MCP RESOURCES ─────────────────────────────────────────────────────────────

@mcp_server.resource("saras://system/status")
def get_system_status() -> str:
    """Returns the current operational status of the SARAS Node."""
    return json.dumps({"status": "Online", "mode": "Central Master", "role": "Surveillance Node"})

@mcp_server.resource("saras://events/critical/recent")
def get_recent_critical_events() -> str:
    """Returns the payload of the most recent CRITICAL alerts for LLM context."""
    return json.dumps(_recent_critical_events, indent=2)

# ─── MCP TOOLS ─────────────────────────────────────────────────────────────────

@mcp_server.tool()
def query_camera_status(camera_id: str) -> str:
    """Queries the status of a specific camera connected to the SARAS node."""
    # In reality, this would query Neo4j or SQLite
    return json.dumps({
        "camera_id": camera_id,
        "status": "Online",
        "last_ping": "few seconds ago",
        "location": "Unknown"
    })

@mcp_server.tool()
def actuate_esp_device(target_esp: str, command: str, value: Any = None) -> str:
    """
    Commands the SARAS central node to dispatch an actuation command to a 
    specific IoT ESP device (e.g., locking a door, turning on a light).
    """
    if not _global_bus:
        return "Error: Message bus not connected."
        
    payload = {
        "target": target_esp,
        "command": command,
        "value": value
    }
    # We use the bus to trigger the P2P node's actuation
    _global_bus.publish("actuation_command", payload)
    
    return f"Success: Dispatched '{command}' to '{target_esp}'."

@mcp_server.tool()
def configure_vision_analytics(tool_name: str, enabled: bool) -> str:
    """
    Toggles advanced vision analytics overlays on the live video stream.
    Valid `tool_name` options:
    - 'blur': Anonymizes and blurs detected people/faces/plates.
    - 'heatmap': Generates spatial heatmaps indicating movement density.
    - 'counter': Counts objects/people crossing specific tripwires.
    - 'speed': Estimates velocity/speed of tracked objects.
    - 'workout': Tracks human pose and counts AIGym exercises (e.g., curls).
    """
    if not _global_bus:
        return "Error: Message bus not connected."
        
    _global_bus.publish("configure_analytics", {"tool_name": tool_name, "enabled": enabled})
    state = "enabled" if enabled else "disabled"
    return f"Success: Vision Analytics tool '{tool_name}' has been {state}."


# ─── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # If run autonomously, start the FastMCP StdIO server processing loop.
    # LLMs (like Claude via Cursor or Claude Desktop) connect to this via standard I/O streams.
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting SARAS MCP Server via stdio...")
    mcp_server.run(transport=llm_config.get("mcp_server_binding", "stdio"))
