"""Home / Status overview page.

This is a lightweight redirect — the main app.py already serves as the home page.
This page provides additional system health details.
"""

from __future__ import annotations

import platform
import sys
from datetime import datetime, timezone

import streamlit as st

st.set_page_config(page_title="SARAS - Home", page_icon="🏠", layout="wide")

st.title("System Overview")

from app.dashboard.utils import (
    check_port_open,
    get_agent_instances,
    get_memory_stats,
    get_platform_status,
    read_env_file,
)

# ---------------------------------------------------------------------------
# System Info
# ---------------------------------------------------------------------------
st.subheader("Host Information")
col1, col2, col3 = st.columns(3)
with col1:
    st.markdown(f"**Python**: `{sys.version.split()[0]}`")
    st.markdown(f"**Platform**: `{platform.platform()}`")
with col2:
    st.markdown(f"**Architecture**: `{platform.machine()}`")
    st.markdown(f"**Hostname**: `{platform.node()}`")
with col3:
    st.markdown(
        f"**UTC Time**: `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}`"
    )
    try:
        import psutil

        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        st.markdown(
            f"**CPU**: `{cpu}%` | **RAM**: `{mem.percent}%` ({round(mem.used / 1e9, 1)}/{round(mem.total / 1e9, 1)} GB)"
        )
    except ImportError:
        st.markdown("**CPU/RAM**: psutil not available")

st.divider()

# ---------------------------------------------------------------------------
# Service Health
# ---------------------------------------------------------------------------
st.subheader("Service Health Checks")

env = read_env_file()

services = [
    ("Redis", env.get("REDIS_URL", "redis://localhost:6379"), "localhost", 6379),
    ("PostgreSQL", env.get("DATABASE_URL", ""), "localhost", 5432),
    ("SearXNG", env.get("SEARXNG_URL", "http://localhost:8080"), "localhost", 8080),
    (
        "Ollama",
        env.get("OLLAMA_BASE_URL", "http://localhost:11434"),
        "localhost",
        11434,
    ),
    ("Home Assistant", env.get("HOME_ASSISTANT_URL", ""), "homeassistant.local", 8123),
    ("Web Dashboard", "", "localhost", int(env.get("WEB_DASHBOARD_PORT", "8090"))),
]

cols = st.columns(3)
for i, (name, url, host, port) in enumerate(services):
    with cols[i % 3]:
        reachable = check_port_open(host, port, timeout=1.0)
        icon = "🟢" if reachable else "🔴"
        st.markdown(
            f"{icon} **{name}** — `{host}:{port}` {'reachable' if reachable else 'unreachable'}"
        )

st.divider()

# ---------------------------------------------------------------------------
# Configuration Summary
# ---------------------------------------------------------------------------
st.subheader("Configuration Summary")

env_data = read_env_file()
configured_count = sum(
    1
    for v in env_data.values()
    if v
    and v
    not in (
        "your_telegram_bot_token_here",
        "your_discord_bot_token_here",
        "xoxb-...",
        "xapp-...",
    )
)
st.markdown(
    f"**Total env variables**: {len(env_data)} | **Configured (non-empty)**: {configured_count}"
)

# Memory backend
backend = env_data.get("MEMORY_BACKEND", "chroma")
st.markdown(f"**Memory backend**: `{backend}`")

# Voice
voice_enabled = env_data.get("ENABLE_LOCAL_VOICE", "false").lower() in (
    "true",
    "1",
    "yes",
)
st.markdown(f"**Voice pipeline**: {'Enabled' if voice_enabled else 'Disabled'}")

# MQTT
mqtt_url = env_data.get("MQTT_BROKER_URL", "")
st.markdown(f"**MQTT**: {'Configured' if mqtt_url else 'Not configured'}")

if st.button("Refresh"):
    st.rerun()
