from __future__ import annotations

import hashlib
import logging
from typing import Any

from app.core.memory_manager import MemoryManager
from app.core.user_profile import UserProfileStore

logger = logging.getLogger(__name__)


class WorkspaceGraph:
    """Small local view of the user's workspace graph."""

    def __init__(
        self, workspace_dir: str | None = None, graph_tool: Any | None = None
    ) -> None:
        from app.settings.config import Config
        self.workspace_dir = workspace_dir if workspace_dir else Config.MEMORY_ROOT
        self.graph_tool = graph_tool
        self.profile_store = UserProfileStore(workspace_dir)
        self.memory_manager = MemoryManager()

    @staticmethod
    def _safe_name(value: str) -> str:
        return value.strip().replace("\n", " ")[:160]

    @staticmethod
    def _node(name: str, kind: str, **metadata: Any) -> dict[str, Any]:
        return {"name": name, "kind": kind, "metadata": metadata}

    @staticmethod
    def _edge(
        source: str, relation: str, target: str, **metadata: Any
    ) -> dict[str, Any]:
        return {
            "source": source,
            "relation": relation,
            "target": target,
            "metadata": metadata,
        }

    @staticmethod
    def _stable_id(*parts: str) -> str:
        data = "|".join(parts)
        return hashlib.sha1(data.encode("utf-8")).hexdigest()[:12]

    def build_for_user(
        self, user_id: str, *, query: str | None = None
    ) -> dict[str, list[dict[str, Any]]]:
        profile = self.profile_store.load(user_id)
        profile_summary = self.memory_manager.build_profile_summary(user_id)
        memories = self.memory_manager.retrieve_context(
            query or user_id, user_id=user_id, top_k=8
        )

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        user_name = profile.display_name or user_id
        nodes.append(
            self._node(
                user_name,
                "user",
                user_id=user_id,
                timezone=profile.timezone,
                preferred_language=profile.preferred_language,
            )
        )

        for category, values, relation in (
            ("preference", profile.preferences, "PREFERS"),
            ("fact", profile.facts, "KNOWS"),
            ("task", profile.tasks, "TRACKS"),
            ("project", profile.projects, "OWNS_PROJECT"),
            ("file", profile.files, "USES_FILE"),
            ("device", profile.devices, "USES_DEVICE"),
            ("decision", profile.decisions, "MADE_DECISION"),
        ):
            for value in values[:5]:
                name = self._safe_name(value)
                nodes.append(self._node(name, category, user_id=user_id))
                edges.append(self._edge(user_name, relation, name, user_id=user_id))

        for mem in memories[:5]:
            mem_name = self._safe_name(mem)
            nodes.append(self._node(mem_name, "memory", user_id=user_id))
            edges.append(self._edge(user_name, "REMEMBERS", mem_name, user_id=user_id))

        for item in profile_summary.get("preferences", [])[:3]:
            pref_name = self._safe_name(item)
            edges.append(
                self._edge(user_name, "PROFILE_HINT", pref_name, user_id=user_id)
            )

        return {"nodes": nodes, "edges": edges}

    async def sync_user(
        self, user_id: str, *, query: str | None = None
    ) -> dict[str, int]:
        graph = self.build_for_user(user_id, query=query)
        synced = {"nodes": 0, "edges": 0}
        if self.graph_tool is None:
            try:
                from app.tools.kgtool import KnowledgeGraphTool

                self.graph_tool = KnowledgeGraphTool()
            except Exception as exc:
                logger.debug("Knowledge graph tool unavailable: %s", exc)
                return synced

        for node in graph["nodes"]:
            try:
                result = await self.graph_tool.execute(
                    operation="add_relationship",
                    entity1=node["name"],
                    relation="IS_A",
                    entity2=node["kind"],
                )
                if result.get("success"):
                    synced["nodes"] += 1
            except Exception as exc:
                logger.debug("Graph node sync failed: %s", exc)

        for edge in graph["edges"]:
            try:
                result = await self.graph_tool.execute(
                    operation="add_relationship",
                    entity1=edge["source"],
                    relation=edge["relation"],
                    entity2=edge["target"],
                )
                if result.get("success"):
                    synced["edges"] += 1
            except Exception as exc:
                logger.debug("Graph edge sync failed: %s", exc)

        return synced

    def evidence_for_prompt(
        self, user_id: str, *, query: str | None = None
    ) -> list[str]:
        graph = self.build_for_user(user_id, query=query)
        lines: list[str] = []
        for node in graph["nodes"][:8]:
            lines.append(f"{node['kind']}: {node['name']}")
        for edge in graph["edges"][:8]:
            lines.append(f"{edge['source']} --{edge['relation']}--> {edge['target']}")
        return lines
