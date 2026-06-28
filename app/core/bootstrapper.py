import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class Bootstrapper:
    """Handles File-Injected Context Strategy for Dynamic System Prompts."""

    def __init__(self, workspace_dir: str | None = None):
        from app.settings.config import Config

        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path(Config.MEMORY_ROOT)
        # Create default template files if they don't exist
        self._ensure_file_exists(
            "SOUL.md",
            "You are RAVEN, an advanced, highly capable AI assistant. Be helpful, concise, and professional.",
        )
        self._ensure_file_exists(
            "AGENTS.md",
            "Core Operating Instructions:\n- You have access to various tools.\n- Analyze context before acting.",
        )
        self._ensure_file_exists(
            "TOOLS.md",
            "Tool Guidance:\n- Prefer specific tools for the job.\n- Output tool names precisely.",
        )
        self._ensure_file_exists(
            "standing_orders.md",
            "Rollback on Failure | If your code changes break tests, use the 'rollback' operation in file_operations or 'git checkout' to restore the file and try again.",
        )

    def _ensure_file_exists(self, filename: str, default_content: str):
        filepath = self.workspace_dir / filename
        if not filepath.exists():
            filepath.parent.mkdir(parents=True, exist_ok=True)
            try:
                filepath.write_text(default_content, encoding="utf-8")
            except Exception as e:
                logger.error(f"Failed to create default {filename}: {e}")

    def _read_and_truncate(self, filename: str, max_chars: int = 5000) -> str:
        filepath = self.workspace_dir / filename
        if not filepath.exists():
            return f"\n--- [Missing File: {filename}] ---\n"

        try:
            content = filepath.read_text(encoding="utf-8")
            if len(content) > max_chars:
                content = content[:max_chars] + "\n...[Content Truncated due to size limit]..."
            return f"\n--- [{filename}] ---\n{content}\n"
        except Exception as e:
            logger.error(f"Failed to read {filename}: {e}")
            return f"\n--- [Error reading {filename}] ---\n"

    def build_dynamic_context(self, user_id: str | None = None) -> str:
        """Return a short string describing the current date/time context.

        Injected into every system prompt so RAVEN is always temporally aware.
        Zero compute cost — pure datetime math.
        """
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        hour = now.hour
        if 5 <= hour < 12:
            time_of_day = "morning"
        elif 12 <= hour < 17:
            time_of_day = "afternoon"
        elif 17 <= hour < 21:
            time_of_day = "evening"
        else:
            time_of_day = "night"

        return (
            f"Current UTC time: {now.strftime('%Y-%m-%d %H:%M')} ({time_of_day})\n"
            f"Day of week: {now.strftime('%A')}"
        )

    def build_system_prompt(self, query: str | None = None, user_id: str | None = None) -> str:
        """Injects SOUL, AGENTS, TOOLS, live context, and relevant memories."""
        try:
            from app.core.memory_facade import get_memory_facade

            facade = get_memory_facade()
            soul_context = facade.recall(
                "RAVEN core persona instructions", user_id=user_id, top_k=1
            )
            agents_context = facade.recall(
                "available agents and behavior", user_id=user_id, top_k=1
            )
            tools_context = facade.recall("available tools and usage", user_id=user_id, top_k=1)

            soul = (
                "\n".join(m.content for m in soul_context)
                if soul_context
                else self._read_and_truncate("SOUL.md", max_chars=1000)
            )
            agents = (
                "\n".join(m.content for m in agents_context)
                if agents_context
                else self._read_and_truncate("AGENTS.md", max_chars=500)
            )
            tools = (
                "\n".join(m.content for m in tools_context)
                if tools_context
                else self._read_and_truncate("TOOLS.md", max_chars=500)
            )
        except Exception:
            soul = self._read_and_truncate("SOUL.md")
            agents = self._read_and_truncate("AGENTS.md", max_chars=1000)
            tools = self._read_and_truncate("TOOLS.md", max_chars=1000)

        # Dynamic context — always injected, zero cost
        dynamic = self.build_dynamic_context(user_id)
        dynamic_section = f"\n--- [Current Context] ---\n{dynamic}\n"

        profile_section = ""
        if user_id:
            try:
                from app.core.user_profile import UserProfileStore

                store = UserProfileStore(str(self.workspace_dir))
                profile = store.load(user_id)
                rendered = store.render(profile)
                if rendered.strip() != "--- [User Profile] ---":
                    profile_section = f"\n{rendered}\n"
            except Exception as exc:
                logger.warning("Profile retrieval failed: %s", exc)

        memory_section = ""
        if query:
            try:
                from app.core.memory_facade import get_memory_facade

                facade = get_memory_facade()
                memories = facade.recall(query, user_id=user_id, top_k=8)
                if memories:
                    bullets = "\n".join(f"- {m.content}" for m in memories)
                    memory_section = f"\n--- [Relevant Memories] ---\n{bullets}\n"
            except Exception as exc:
                logger.warning("Memory retrieval failed: %s", exc)

        profile_summary_section = ""
        if user_id:
            try:
                from app.core.memory_facade import get_memory_facade

                facade = get_memory_facade()
                profile = facade.profile(user_id)
                profile_lines = []
                if profile.get("preferences"):
                    profile_lines.append("preferences:")
                    profile_lines.extend(f"- {item}" for item in profile["preferences"])
                if profile.get("facts"):
                    profile_lines.append("facts:")
                    profile_lines.extend(f"- {item}" for item in profile["facts"])
                if profile_lines:
                    profile_summary_section = (
                        "\n--- [User Profile Summary] ---\n" + "\n".join(profile_lines) + "\n"
                    )
            except Exception as exc:
                logger.warning("Profile summary retrieval failed: %s", exc)

        graph_section = ""
        if user_id:
            try:
                from app.core.workspace_graph import WorkspaceGraph

                graph = WorkspaceGraph(str(self.workspace_dir))
                evidence = graph.evidence_for_prompt(user_id, query=query)
                if evidence:
                    graph_section = (
                        "\n--- [Workspace Graph] ---\n"
                        + "\n".join(f"- {item}" for item in evidence[:10])
                        + "\n"
                    )
            except Exception as exc:
                logger.warning("Graph evidence retrieval failed: %s", exc)

        standing_orders_section = ""
        try:
            from app.core.standing_orders import StandingOrderStore

            store = StandingOrderStore(str(self.workspace_dir))
            orders = store.parse()
            if orders:
                order_lines = [
                    f"- {order.title}: {order.rule}" for order in orders[:10] if order.enabled
                ]
                if order_lines:
                    standing_orders_section = (
                        "\n--- [Standing Orders] ---\n" + "\n".join(order_lines) + "\n"
                    )
        except Exception as exc:
            logger.warning("Standing order retrieval failed: %s", exc)

        active_skills_section = ""
        try:
            from app.core.skill_registry import SkillRegistry

            registry = SkillRegistry()
            texts = registry.get_active_skill_texts()
            if texts:
                active_skills_section = f"\n--- [Active Skills] ---\n{texts}\n"
        except Exception as exc:
            logger.warning("Skill text retrieval failed: %s", exc)

        # --- LEARNED KNOWLEDGE SECTION (unified FTS5 retrieval) ---
        learning_section = ""
        if query:
            try:
                from app.core.learning_retrieval import IntelligentRetriever

                retriever = IntelligentRetriever()
                learning_section = retriever.get_injection_block(
                    query,
                    max_items=6,
                    min_confidence=0.35,
                )
                if learning_section:
                    learning_section = f"\n{learning_section}\n"
            except Exception as exc:
                logger.debug("Intelligent retrieval failed: %s", exc)

        if not learning_section:
            try:
                from app.core.learning_db import get_learning_store

                store = get_learning_store()
                stats = store.get_stats()
                if stats.get("total", 0) > 0:
                    recent = store.get_recent(limit=5, min_confidence=0.5)
                    if recent:
                        items = [
                            f"- [{r['type'].replace('_', ' ').title()}] {r['content'][:120]}"
                            for r in recent
                        ]
                        learning_section = (
                            "\n--- [Recent Learnings] ---\n" + "\n".join(items) + "\n"
                        )
            except Exception as exc:
                logger.debug("Recent learnings fallback failed: %s", exc)

        if not learning_section:
            try:
                from app.core.correction_learner import CorrectionStore

                store = CorrectionStore(str(self.workspace_dir))
                recents = store.get_recent(5)
                if recents:
                    facts = [f"- {c.corrected_claim[:120]}" for c in recents]
                    if facts:
                        learning_section = (
                            "\n--- [Learned Facts (legacy)] ---\n" + "\n".join(facts) + "\n"
                        )
            except Exception:
                pass

        # --- RLHF Preference Section ---
        rlhf_section = ""
        try:
            from app.core.rlhf import RlhfCrystallizer

            rlhf_text = RlhfCrystallizer().build_preference_prompt()
            if rlhf_text.strip():
                rlhf_section = f"\n{rlhf_text}\n"
        except Exception as exc:
            logger.debug("RLHF preference injection failed: %s", exc)

        # --- Supervisor Routing Section ---
        supervisor_section = ""
        if query:
            try:
                from app.core.supervisor import get_supervisor

                agent_id = get_supervisor().select_agent(query)
                if agent_id != "assistant":
                    supervisor_section = (
                        f"\n--- [Agent Routing] ---\n"
                        f"This request is classified as a {agent_id} task. "
                        f"Route to the {agent_id} specialist if appropriate.\n"
                    )
            except Exception as exc:
                logger.debug("Supervisor routing failed: %s", exc)

        return (
            f"System Bootstrapped Context:\n"
            f"{soul}{dynamic_section}{profile_section}{profile_summary_section}{graph_section}{standing_orders_section}{active_skills_section}{learning_section}{rlhf_section}{supervisor_section}{agents}{tools}{memory_section}"
        )
