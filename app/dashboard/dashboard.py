"""SARAS Admin Dashboard — Streamlit entry point.

Run with:
    streamlit run app/dashboard/dashboard.py --server.port 8501

Or automatically via main.py when STREAMLIT_DASHBOARD_ENABLED=true.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="SARAS Control Center",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("SARAS")
    st.caption("Sentient Autonomous Reasoning & Action System")
    st.divider()
    st.markdown(
        """
**Navigation** (use sidebar pages)

- **Home** — System overview
- **Environment** — Edit .env config
- **Agents** — Manage 14 agents
- **Models** — LLM provider config
- **Memory** — Agent memory viewer
- **System** — Metrics & tools
"""
    )
    st.divider()
    st.caption("Dashboard v1.0 — Phase 7")

# ---------------------------------------------------------------------------
# Main page (Home)
# ---------------------------------------------------------------------------
st.title("SARAS Control Center")
st.markdown("### Welcome to the admin dashboard")
st.markdown(
    "Use the **sidebar pages** to manage your SARAS instance. "
    "This dashboard lets you configure environment variables, manage agents, "
    "tune LLM models, browse agent memories, and monitor system health."
)

# Quick stats
from app.dashboard.utils import (
    get_agent_instances,
    get_memory_stats,
    get_platform_status,
    get_tool_info_list,
)

col1, col2, col3, col4 = st.columns(4)

# Agent count
try:
    agents = get_agent_instances()
    agent_count = len(agents)
except Exception:
    agent_count = 0

# Tool count
try:
    tools = get_tool_info_list()
    tool_count = len(tools)
    loadable = sum(1 for t in tools if t["status"] == "loadable")
except Exception:
    tool_count = 0
    loadable = 0

# Memory stats
try:
    mem = get_memory_stats()
except Exception:
    mem = {"agent_workspaces": 0, "total_files": 0, "total_size_kb": 0}

# Platform status
try:
    platforms = get_platform_status()
    configured_platforms = sum(1 for p in platforms if p["configured"])
except Exception:
    platforms = []
    configured_platforms = 0

with col1:
    st.metric("Active Agents", agent_count)
with col2:
    st.metric("Tools", f"{loadable}/{tool_count}")
with col3:
    st.metric("Memory Files", mem["total_files"])
with col4:
    st.metric("Platforms", f"{configured_platforms}/{len(platforms)}")

st.divider()

# Platform status table
st.subheader("Platform Connectivity")
if platforms:
    for p in platforms:
        status_icon = "🟢" if p["configured"] else "🔴"
        st.markdown(
            f"{status_icon} **{p['platform']}** — "
            f"{'Configured' if p['configured'] else 'Not configured'} "
            f"(requires: `{', '.join(p['required_keys'])}`)"
        )
else:
    st.info("Could not check platform status.")

st.divider()

# Agent summary
st.subheader("Registered Agents")
if agent_count > 0:
    agent_data = []
    for name, inst in sorted(agents.items()):
        tool_count_per_agent = 0
        try:
            tool_count_per_agent = len(inst.tools)
        except Exception:
            pass
        agent_data.append(
            {
                "Agent": name,
                "Provider": getattr(inst, "provider_name", "killo"),
                "Model": getattr(inst, "model_name", ""),
                "Tools": tool_count_per_agent,
                "Perfectness": getattr(inst, "perfectness", 0.5),
                "Heartbeat (s)": getattr(inst, "heartbeat_interval", 0),
            }
        )
    st.dataframe(agent_data, use_container_width=True, hide_index=True)
else:
    st.warning("No agents could be loaded.")

st.divider()

# Memory overview
st.subheader("Memory System")
mcol1, mcol2, mcol3 = st.columns(3)
with mcol1:
    st.metric("Agent Workspaces", mem["agent_workspaces"])
with mcol2:
    st.metric("Total Memory Files", mem["total_files"])
with mcol3:
    st.metric("Total Size", f"{mem['total_size_kb']} KB")
