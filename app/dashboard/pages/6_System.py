"""System Status page — metrics, platform health, scheduler, tool registry."""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="SARAS - System", page_icon="📊", layout="wide")

st.title("System Status")
st.caption("Monitor metrics, view the tool registry, and check system health.")

from app.dashboard.utils import (
    check_port_open,
    get_agent_instances,
    get_tool_info_list,
    read_env_file,
)

# ---------------------------------------------------------------------------
# System metrics (Prometheus)
# ---------------------------------------------------------------------------
st.subheader("Prometheus Metrics")

env = read_env_file()

try:
    from app.core.metrics import (
        requests_blocked,
        requests_total,
        tool_calls_total,
        llm_calls_total,
        llm_latency_seconds,
    )

    st.success("Prometheus metrics module loaded successfully.")
    st.markdown(
        """
Available metric counters:
- `saras_requests_total` — Total incoming requests (by platform, source_kind)
- `saras_requests_blocked` — Blocked requests (by reason: security, rate_limit)
- `saras_tool_calls_total` — Tool invocations (by tool_name, success/failure)
- `saras_llm_calls_total` — LLM API calls (by provider, model)
- `saras_llm_latency_seconds` — LLM call latency histogram
"""
    )

    # Check if Prometheus scrape endpoint is up
    prom_reachable = check_port_open("localhost", 9090)
    if prom_reachable:
        st.success("Prometheus server is reachable at `localhost:9090`")
    else:
        st.info(
            "Prometheus server not detected at `localhost:9090`. "
            "Metrics are still collected in-process — just not scraped externally."
        )
except ImportError:
    st.warning("Prometheus metrics module (`app.core.metrics`) could not be imported.")

st.divider()

# ---------------------------------------------------------------------------
# Resource usage
# ---------------------------------------------------------------------------
st.subheader("Resource Usage")

try:
    import psutil

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("CPU Usage", f"{psutil.cpu_percent(interval=0.5)}%")
    with col2:
        mem = psutil.virtual_memory()
        st.metric("RAM Usage", f"{mem.percent}%")
    with col3:
        disk = psutil.disk_usage("/")
        st.metric("Disk Usage", f"{disk.percent}%")
    with col4:
        import os

        pid = os.getpid()
        proc = psutil.Process(pid)
        rss_mb = proc.memory_info().rss / (1024 * 1024)
        st.metric("Dashboard RSS", f"{rss_mb:.0f} MB")

    # CPU per-core
    with st.expander("CPU per-core usage"):
        per_cpu = psutil.cpu_percent(percpu=True, interval=0.5)
        for i, pct in enumerate(per_cpu):
            bar_width = int(pct / 5)  # scale to ~20 chars
            st.markdown(
                f"Core {i:2d}: `{'█' * bar_width}{'░' * (20 - bar_width)}` {pct:.1f}%"
            )

except ImportError:
    st.info("Install `psutil` for resource usage monitoring.")

st.divider()

# ---------------------------------------------------------------------------
# Tool Registry
# ---------------------------------------------------------------------------
st.subheader("Tool Registry")

tools = get_tool_info_list()
if tools:
    # Summary
    loadable = sum(1 for t in tools if t["status"] == "loadable")
    st.markdown(f"**{loadable}/{len(tools)}** tools loadable (class importable)")

    # Table
    tool_data = []
    for t in tools:
        status_icon = "🟢" if t["status"] == "loadable" else "🔴"
        tool_data.append(
            {
                "Status": status_icon,
                "Tool Class": t["class"],
                "Module": t["module"],
                "Error": t["status"] if t["status"] != "loadable" else "",
            }
        )
    st.dataframe(tool_data, use_container_width=True, hide_index=True)

    # Agent-Tool mapping
    st.divider()
    st.subheader("Agent-Tool Mapping")
    agents = get_agent_instances()
    if agents:
        mapping_data = []
        for agent_name, inst in sorted(agents.items()):
            try:
                tool_names = [t.get_name() for t in inst.tools]
                mapping_data.append(
                    {
                        "Agent": agent_name,
                        "Tool Count": len(tool_names),
                        "Tools": ", ".join(sorted(tool_names)),
                    }
                )
            except Exception:
                mapping_data.append(
                    {
                        "Agent": agent_name,
                        "Tool Count": 0,
                        "Tools": "(failed to load)",
                    }
                )
        st.dataframe(mapping_data, use_container_width=True, hide_index=True)

        # Orphan check — tools not used by any agent
        all_agent_tools = set()
        for agent_name, inst in agents.items():
            try:
                for t in inst.tools:
                    all_agent_tools.add(t.get_name())
            except Exception:
                pass

        all_tool_classes = {t["class"] for t in tools}
        # Note: tool class names and get_name() results may differ.
        # This is a best-effort check.
        st.markdown(f"**Unique tools used across all agents**: {len(all_agent_tools)}")
else:
    st.warning("No tools found in registry.")

st.divider()

# ---------------------------------------------------------------------------
# Scheduler status
# ---------------------------------------------------------------------------
st.subheader("Scheduler")
st.markdown(
    """
The SARAS scheduler uses **APScheduler** with a SQLite job store (`workspace/scheduler.db`).

Configured routines:
- **Morning Briefing** — Daily at the configured hour
- **Agent Heartbeats** — Per-agent intervals (when `heartbeat_interval > 0`)
- **Reminders** — User-created via `ReminderTool`
"""
)

from pathlib import Path

scheduler_db = Path("workspace/scheduler.db")
if scheduler_db.exists():
    size_kb = scheduler_db.stat().st_size / 1024
    st.success(f"Scheduler database exists: `{scheduler_db}` ({size_kb:.1f} KB)")
else:
    st.info("Scheduler database not found — it is created on first run.")

# Morning briefing config
briefing_users = env.get("MORNING_BRIEFING_USERS", "")
briefing_hour = env.get("MORNING_BRIEFING_HOUR", "8")
briefing_minute = env.get("MORNING_BRIEFING_MINUTE", "0")
if briefing_users:
    st.markdown(
        f"**Morning briefing**: `{briefing_hour}:{briefing_minute:>2}` UTC for `{briefing_users}`"
    )
else:
    st.info("Morning briefing not configured (`MORNING_BRIEFING_USERS` is empty).")

st.divider()

# ---------------------------------------------------------------------------
# Architecture diagram (text)
# ---------------------------------------------------------------------------
st.subheader("Architecture Overview")
st.code(
    """
    ┌──────────────────────────────────────────────────────────┐
    │                    SARAS Architecture                     │
    ├──────────────────────────────────────────────────────────┤
    │                                                          │
    │  Platforms:  Telegram │ Discord │ Slack │ WhatsApp │ Web  │
    │       │         │         │         │          │         │
    │       └─────────┴─────────┴─────────┴──────────┘         │
    │                         │                                │
    │                    BotSignal (router)                     │
    │                         │                                │
    │              MessageOrchestrator                         │
    │              ┌──────────┴──────────┐                     │
    │         System 1              System 2                   │
    │        MiniEngine           AgentRuntime                 │
    │       (fast reflex)        (ReAct loop)                  │
    │                                 │                        │
    │                          SwarmManager                    │
    │                    ┌────────────┼────────────┐           │
    │                    │            │            │           │
    │              14 Specialist Agents                        │
    │        (WorkerAgent wrappers with tools)                 │
    │                                                          │
    │  Memory: ChromaDB / PgVector + Markdown workspace        │
    │  Infra:  Redis │ PostgreSQL │ Prometheus │ Docker         │
    └──────────────────────────────────────────────────────────┘
    """,
    language=None,
)

if st.button("Refresh", key="system_refresh"):
    st.rerun()
