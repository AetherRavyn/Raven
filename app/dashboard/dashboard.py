"""Streamlit Admin Dashboard — system overview and management.

Provides a visual interface for:
- System status and health
- Agent management
- Memory statistics
- Active workflows
- Live event stream
"""

import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def main():
    import streamlit as st

    st.set_page_config(
        page_title="Raven Admin Dashboard",
        page_icon="🐦",
        layout="wide",
    )

    st.title("🐦 Raven Admin Dashboard")
    st.markdown("---")

    # Sidebar
    with st.sidebar:
        st.header("Navigation")
        page = st.radio(
            "Go to",
            ["System Status", "Agents", "Memory", "Workflows", "Modules"],
            index=0,
        )

    if page == "System Status":
        show_system_status()
    elif page == "Agents":
        show_agents()
    elif page == "Memory":
        show_memory()
    elif page == "Workflows":
        show_workflows()
    elif page == "Modules":
        show_modules()


def show_system_status():
    """Show system status and health."""
    st.header("System Status")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Status", "🟢 Online")
    with col2:
        try:
            from app.core.memory import get_memory_store
            store = get_memory_store()
            total, tools = store.count()
            st.metric("Memories", total)
        except Exception:
            st.metric("Memories", "N/A")
    with col3:
        try:
            from app.core.self_evolution import SelfEvolutionSystem
            system = SelfEvolutionSystem()
            goals = system.get_active_goals()
            st.metric("Active Goals", len(goals))
        except Exception:
            st.metric("Active Goals", "N/A")

    st.markdown("---")

    # Recent activity
    st.subheader("Recent Activity")
    try:
        from app.core.proactive_intelligence import ProactiveIntelligence
        pi = ProactiveIntelligence()
        insights = pi.get_recent_insights(5)
        if insights:
            for insight in insights:
                st.info(f"**{insight.title}**: {insight.description[:100]}")
        else:
            st.info("No recent insights")
    except Exception:
        st.info("Activity feed not available")


def show_agents():
    """Show agent management."""
    st.header("Agents")

    try:
        from raven_protocol import get_registry
        registry = get_registry()
        cards = registry.list_modules()

        if cards:
            for card in cards:
                with st.expander(f"🤖 {card.name} — {card.description[:60]}"):
                    st.write(f"**Skills:** {', '.join(s.name for s in card.skills)}")
                    st.write(f"**Transport:** {card.transport}")
                    st.write(f"**Version:** {card.version}")
        else:
            st.info("No agents registered")
    except Exception as e:
        st.error(f"Error loading agents: {e}")


def show_memory():
    """Show memory statistics."""
    st.header("Memory System")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Semantic Memory")
        try:
            from app.core.memory import get_memory_store
            store = get_memory_store()
            total, tools = store.count()
            st.metric("Total Memories", total)
            st.metric("Tool Guides", tools)
        except Exception as e:
            st.error(f"Error: {e}")

    with col2:
        st.subheader("Knowledge Graph")
        try:
            from app.core.knowledge_manager import get_knowledge_manager
            km = get_knowledge_manager()
            stats = km.get_stats() if hasattr(km, 'get_stats') else {}
            st.metric("Entities", stats.get("entity_count", "N/A"))
            st.metric("Relationships", stats.get("relationship_count", "N/A"))
        except Exception as e:
            st.error(f"Error: {e}")

    st.markdown("---")

    # Memory search
    st.subheader("Search Memory")
    query = st.text_input("Search query")
    if query:
        try:
            from app.core.memory_facade import get_memory_facade
            facade = get_memory_facade()
            results = facade.recall(query, top_k=5)
            for r in results:
                st.write(f"- {r.content[:100]}")
        except Exception as e:
            st.error(f"Search error: {e}")


def show_workflows():
    """Show active workflows."""
    st.header("Workflows")

    try:
        from app.core.cron_engine import CronEngine
        engine = CronEngine()
        jobs = engine.get_jobs()

        if jobs:
            for job in jobs:
                status = "🟢" if job.get("enabled") else "🔴"
                st.write(f"{status} **{job.get('name', 'Unnamed')}** — {job.get('schedule_type', 'unknown')}")
        else:
            st.info("No scheduled jobs")
    except Exception as e:
        st.error(f"Error: {e}")


def show_modules():
    """Show A2A modules."""
    st.header("A2A Modules")

    try:
        from raven_protocol import get_registry
        registry = get_registry()
        summary = registry.get_registry_summary()

        st.metric("Registered Modules", summary["total_modules"])

        for m in summary["modules"]:
            with st.expander(f"📦 {m['name']} — {m['description'][:60]}"):
                st.write(f"**Skills:** {', '.join(m['skills'])}")
                st.write(f"**Transport:** {m['transport']}")
    except Exception as e:
        st.error(f"Error: {e}")


if __name__ == "__main__":
    main()
