"""Agent Manager page — view and manage all 14 SARAS agents."""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="SARAS - Agents", page_icon="🤖", layout="wide")

st.title("Agent Manager")
st.caption("View, inspect, and edit agent properties, memory, and tool assignments.")

from app.dashboard.utils import (
    MEMORY_FILES,
    WORKSPACE_AGENTS,
    get_agent_info,
    get_agent_instances,
    list_agent_workspaces,
    read_agent_memory_file,
    write_agent_memory_file,
)

# ---------------------------------------------------------------------------
# Load agents
# ---------------------------------------------------------------------------
agents = get_agent_instances()

if not agents:
    st.error("No agents could be loaded. Check your imports and dependencies.")
    st.stop()

st.success(f"Loaded **{len(agents)}** agents successfully.")

# ---------------------------------------------------------------------------
# Agent selector
# ---------------------------------------------------------------------------
agent_names = sorted(agents.keys())
selected_name = st.selectbox("Select an agent", agent_names, key="agent_selector")

agent = agents[selected_name]
info = get_agent_info(agent)

# ---------------------------------------------------------------------------
# Agent detail tabs
# ---------------------------------------------------------------------------
tab_overview, tab_soul, tab_goals, tab_memory, tab_tools = st.tabs(
    ["Overview", "Soul & Personality", "Goals", "Memory Files", "Tools"]
)

with tab_overview:
    st.subheader(f"Agent: {info['name']}")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Provider**: `{info['provider_name']}`")
        st.markdown(f"**Model**: `{info['model_name']}`")
        st.markdown(f"**Perfectness**: `{info['perfectness']}`")
    with col2:
        st.markdown(f"**Heartbeat interval**: `{info['heartbeat_interval']}s`")
        st.markdown(f"**Memory directory**: `{info['memory_dir']}`")
        st.markdown(f"**Tool count**: `{len(info['tools'])}`")

    # Soul preview
    if info["soul"]:
        st.markdown("---")
        st.markdown("**Soul (core purpose):**")
        st.markdown(f"> {info['soul'][:300]}{'...' if len(info['soul']) > 300 else ''}")

    # Goals preview
    if info["goals"]:
        st.markdown("---")
        st.markdown("**Goals:**")
        for g in info["goals"]:
            st.markdown(f"- {g}")

with tab_soul:
    st.subheader("Soul & Personality")

    st.markdown("**Soul** (immutable core purpose — defined in code):")
    st.text_area(
        "Soul",
        value=info["soul"] or "(No soul defined)",
        height=150,
        disabled=True,
        key="soul_view",
    )

    st.markdown("**Personality** (communication style — defined in code):")
    st.text_area(
        "Personality",
        value=info["personality"] or "(No personality defined)",
        height=150,
        disabled=True,
        key="personality_view",
    )

    st.info(
        "Soul and personality are defined in the agent source code. "
        "To modify them, edit the agent's Python file in `app/agents/`."
    )

    # Show the soul.md file from workspace (runtime version)
    agent_dir = info["name"].lower().replace(" ", "_")
    soul_file = read_agent_memory_file(agent_dir, "soul.md")
    if soul_file:
        st.divider()
        st.markdown("**Runtime soul.md** (workspace file — editable):")
        edited_soul = st.text_area(
            "soul.md",
            value=soul_file,
            height=200,
            key="soul_md_edit",
        )
        if edited_soul != soul_file:
            if st.button("Save soul.md", key="save_soul"):
                write_agent_memory_file(agent_dir, "soul.md", edited_soul)
                st.success("soul.md saved!")
                st.rerun()

with tab_goals:
    st.subheader("Goals")

    st.markdown("**Code-defined goals:**")
    if info["goals"]:
        for i, g in enumerate(info["goals"]):
            st.markdown(f"{i + 1}. {g}")
    else:
        st.markdown("_(No goals defined in code)_")

    # Runtime goals.md
    agent_dir = info["name"].lower().replace(" ", "_")
    goals_file = read_agent_memory_file(agent_dir, "goals.md")
    if goals_file:
        st.divider()
        st.markdown("**Runtime goals.md** (editable):")
        edited_goals = st.text_area(
            "goals.md",
            value=goals_file,
            height=250,
            key="goals_md_edit",
        )
        if edited_goals != goals_file:
            if st.button("Save goals.md", key="save_goals"):
                write_agent_memory_file(agent_dir, "goals.md", edited_goals)
                st.success("goals.md saved!")
                st.rerun()

with tab_memory:
    st.subheader("Memory Files")

    agent_dir = info["name"].lower().replace(" ", "_")
    workspace_path = WORKSPACE_AGENTS / agent_dir

    if not workspace_path.exists():
        st.warning(
            f"No workspace directory found at `{workspace_path}`. "
            "Memory files are created lazily on the agent's first run."
        )
        if st.button("Initialize workspace now"):
            try:
                agent._ensure_memory_files()
                st.success("Workspace initialized!")
                st.rerun()
            except Exception as e:
                st.error(f"Failed: {e}")
    else:
        file_tabs = st.tabs(MEMORY_FILES)
        for ftab, fname in zip(file_tabs, MEMORY_FILES):
            with ftab:
                content = read_agent_memory_file(agent_dir, fname)
                edited = st.text_area(
                    fname,
                    value=content,
                    height=350,
                    key=f"memfile_{agent_dir}_{fname}",
                )
                if edited != content:
                    if st.button(f"Save {fname}", key=f"save_{agent_dir}_{fname}"):
                        write_agent_memory_file(agent_dir, fname, edited)
                        st.success(f"{fname} saved!")
                        st.rerun()

with tab_tools:
    st.subheader("Assigned Tools")

    if info["tools"]:
        for i, tool_name in enumerate(sorted(info["tools"])):
            st.markdown(f"{i + 1}. `{tool_name}`")
    else:
        st.warning("No tools assigned to this agent (or tools failed to load).")

    st.info(
        "Tool assignments are defined in the agent's Python source code. "
        "To add or remove tools, edit `app/agents/{agent_file}.py`."
    )

# ---------------------------------------------------------------------------
# Bulk workspace overview
# ---------------------------------------------------------------------------
st.divider()
st.subheader("All Agent Workspaces")

workspaces = list_agent_workspaces()
if workspaces:
    ws_data = []
    for ws in workspaces:
        files = []
        ws_path = WORKSPACE_AGENTS / ws
        for f in ws_path.iterdir():
            if f.is_file():
                files.append(f.name)
        ws_data.append(
            {
                "Workspace": ws,
                "Files": ", ".join(sorted(files)) if files else "(empty)",
                "Size (KB)": round(
                    sum(f.stat().st_size for f in ws_path.iterdir() if f.is_file())
                    / 1024,
                    1,
                ),
            }
        )
    st.dataframe(ws_data, use_container_width=True, hide_index=True)
else:
    st.info(
        "No agent workspaces created yet. They are created lazily on first agent run."
    )
