"""Memory Viewer page — browse agent memory files and PgVector search."""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="SARAS - Memory", page_icon="💾", layout="wide")

st.title("Memory Viewer")
st.caption(
    "Browse and edit per-agent memory files. Search memories with PgVector (when available)."
)

from app.dashboard.utils import (
    MEMORY_FILES,
    WORKSPACE_AGENTS,
    get_memory_stats,
    list_agent_workspaces,
    read_agent_memory_file,
    read_env_file,
    write_agent_memory_file,
)

# ---------------------------------------------------------------------------
# Memory stats
# ---------------------------------------------------------------------------
stats = get_memory_stats()

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Agent Workspaces", stats["agent_workspaces"])
with col2:
    st.metric("Total Files", stats["total_files"])
with col3:
    st.metric("Total Size", f"{stats['total_size_kb']} KB")

env = read_env_file()
backend = env.get("MEMORY_BACKEND", "chroma")
st.markdown(f"**Memory backend**: `{backend}`")

st.divider()

# ---------------------------------------------------------------------------
# File browser
# ---------------------------------------------------------------------------
st.subheader("Agent Memory Browser")

workspaces = list_agent_workspaces()
if not workspaces:
    st.info(
        "No agent workspaces found. They are created lazily when agents first run. "
        "You can initialize them from the Agents page."
    )
    st.stop()

selected_ws = st.selectbox("Select agent workspace", workspaces, key="mem_ws_select")

ws_path = WORKSPACE_AGENTS / selected_ws
available_files = sorted(f.name for f in ws_path.iterdir() if f.is_file())

if not available_files:
    st.warning(f"Workspace `{selected_ws}` is empty.")
else:
    selected_file = st.selectbox("Select file", available_files, key="mem_file_select")

    content = read_agent_memory_file(selected_ws, selected_file)
    file_size = len(content.encode("utf-8"))

    st.markdown(f"**File**: `{selected_ws}/{selected_file}` ({file_size} bytes)")

    edited = st.text_area(
        f"Contents of {selected_file}",
        value=content,
        height=400,
        key=f"mem_edit_{selected_ws}_{selected_file}",
    )

    col_save, col_clear = st.columns(2)
    with col_save:
        if edited != content:
            if st.button("Save", type="primary", key="mem_save"):
                write_agent_memory_file(selected_ws, selected_file, edited)
                st.success(f"Saved `{selected_file}`!")
                st.rerun()
        else:
            st.button("Save", disabled=True, key="mem_save_disabled")
    with col_clear:
        if st.button("Clear file", key="mem_clear"):
            # Reset to header only
            header = f"# {selected_file.replace('.md', '').title()} — {selected_ws}\n\n"
            write_agent_memory_file(selected_ws, selected_file, header)
            st.success(f"Cleared `{selected_file}`!")
            st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# PgVector semantic search
# ---------------------------------------------------------------------------
st.subheader("Semantic Memory Search")

if backend != "pgvector":
    st.info(
        f"Semantic search requires `MEMORY_BACKEND=pgvector` (currently `{backend}`). "
        "File-based memory is always available above."
    )
else:
    search_query = st.text_input(
        "Search query",
        placeholder="e.g. 'TSLA stock analysis' or 'Docker deployment issues'",
        key="pgvec_search",
    )

    search_agent = st.selectbox(
        "Scope to agent (optional)",
        ["(all agents)"] + workspaces,
        key="pgvec_agent",
    )

    top_k = st.slider("Max results", 1, 20, 8, key="pgvec_topk")

    if st.button("Search", key="pgvec_go") and search_query:
        try:
            from app.core.memory import get_memory_store

            store = get_memory_store()
            user_id = None
            if search_agent != "(all agents)":
                user_id = f"agent_{search_agent}"

            results = store.retrieve(
                query=search_query,
                top_k=top_k,
                user_id=user_id,
            )

            if results:
                st.success(f"Found {len(results)} result(s).")
                for i, r in enumerate(results):
                    st.markdown(f"**{i + 1}.** {r}")
            else:
                st.info("No results found.")
        except Exception as e:
            st.error(f"PgVector search failed: {e}")

st.divider()

# ---------------------------------------------------------------------------
# Bulk workspace overview
# ---------------------------------------------------------------------------
st.subheader("Workspace Overview")

ws_data = []
for ws in workspaces:
    ws_path = WORKSPACE_AGENTS / ws
    file_count = sum(1 for f in ws_path.iterdir() if f.is_file())
    total_bytes = sum(f.stat().st_size for f in ws_path.iterdir() if f.is_file())
    ws_data.append(
        {
            "Agent": ws,
            "Files": file_count,
            "Size (KB)": round(total_bytes / 1024, 1),
        }
    )

if ws_data:
    st.dataframe(ws_data, use_container_width=True, hide_index=True)
