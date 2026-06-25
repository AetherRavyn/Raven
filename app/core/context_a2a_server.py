"""Context Module — A2A-compliant context awareness module.

Exposes context capabilities via the Raven Protocol.
Any module can query user context without importing app/ code.
"""

from __future__ import annotations

import logging
from typing import Any

from raven_protocol import AgentCard, Skill, ModuleServer

logger = logging.getLogger(__name__)


async def handle_get_mood(params: dict[str, Any]) -> dict[str, Any]:
    """Get user's current mood."""
    from app.core.life_context import get_life_context_engine
    engine = get_life_context_engine()
    ctx = engine.get_context(params.get("user_id", "default"))
    return {"mood": ctx.current_mood, "confidence": ctx.confidence}


async def handle_get_location(params: dict[str, Any]) -> dict[str, Any]:
    """Get user's current location."""
    from app.core.location_awareness import LocationAwareness
    from app.settings.config import Config
    loc = LocationAwareness(workspace_dir=Config.MEMORY_ROOT)
    location = loc.get_location()
    if location:
        return {"city": location.city, "timezone": location.timezone, "source": location.source}
    return {"city": "", "timezone": "UTC", "source": "unknown"}


async def handle_get_activity(params: dict[str, Any]) -> dict[str, Any]:
    """Get user's current activity."""
    from app.core.activity_detection import ActivityDetector
    from app.settings.config import Config
    detector = ActivityDetector(workspace_dir=Config.MEMORY_ROOT)
    activity = detector.get_current_activity()
    return {"activity": activity.activity, "confidence": activity.confidence, "source": activity.source}


async def handle_get_environment(params: dict[str, Any]) -> dict[str, Any]:
    """Get environmental sensor data."""
    from raven_iot.sensors.environmental import EnvironmentalSensor
    from app.settings.config import Config
    env = EnvironmentalSensor(workspace_dir=Config.MEMORY_ROOT)
    state = env.get_state()
    return {
        "temperature": state.temperature,
        "humidity": state.humidity,
        "light_level": state.light_level,
        "noise_level": state.noise_level,
        "air_quality": state.air_quality,
        "presence": state.presence,
    }


async def handle_build_context(params: dict[str, Any]) -> dict[str, Any]:
    """Build full context prompt for LLM injection."""
    from app.core.context_awareness import ContextAwareness
    from app.settings.config import Config
    ca = ContextAwareness(workspace_dir=Config.MEMORY_ROOT)
    prompt = ca.build_context_prompt(params.get("user_id", "default"))
    return {"context_prompt": prompt}


async def handle_get_life_context(params: dict[str, Any]) -> dict[str, Any]:
    """Get full life context for a user."""
    from app.core.life_context import get_life_context_engine
    from dataclasses import asdict
    engine = get_life_context_engine()
    ctx = engine.get_context(params.get("user_id", "default"))
    return asdict(ctx)


def create_context_server() -> ModuleServer:
    """Create and configure the Context module server."""
    card = AgentCard(
        name="context",
        description="User context: mood, location, activity, environment, life context",
        version="1.0.0",
        skills=[
            Skill(name="get_mood", description="Get user mood", tags=["mood", "emotion"]),
            Skill(name="get_location", description="Get user location", tags=["location", "geo"]),
            Skill(name="get_activity", description="Get user activity", tags=["activity", "behavior"]),
            Skill(name="get_environment", description="Get sensor data", tags=["environment", "sensor"]),
            Skill(name="build_context", description="Build LLM context", tags=["context", "prompt"]),
            Skill(name="get_life_context", description="Get full life context", tags=["life", "profile"]),
        ],
        transport="in-process",
    )

    server = ModuleServer(card)
    server.register_method("context.get_mood", handle_get_mood)
    server.register_method("context.get_location", handle_get_location)
    server.register_method("context.get_activity", handle_get_activity)
    server.register_method("context.get_environment", handle_get_environment)
    server.register_method("context.build_context", handle_build_context)
    server.register_method("context.get_life_context", handle_get_life_context)

    return server
