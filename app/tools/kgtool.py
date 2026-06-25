import logging
from typing import Any, Dict, List

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class KnowledgeGraphTool(BaseTool):
    """Knowledge graph backed by HelixDB.

    Provides add_relationship / query_entity / find_path operations
    on the HelixDB-backed knowledge graph.
    """

    def __init__(self):
        self._helix_kg: Any = None

    async def _get_helix_kg(self) -> Any:
        if self._helix_kg is None:
            from app.db.knowledge_graph_helix import HelixKnowledgeGraph

            self._helix_kg = HelixKnowledgeGraph()
        return self._helix_kg

    # ------------------------------------------------------------------
    # Dashboard helpers (v35)
    # ------------------------------------------------------------------

    async def list_entities(self, limit: int = 500) -> List[Dict[str, Any]]:
        """Return every entity in the graph."""
        kg = await self._get_helix_kg()
        return await kg.list_entities(limit=limit)

    async def get_stats(self) -> Dict[str, Any]:
        """Return entity + relationship counts and backend health."""
        kg = await self._get_helix_kg()
        return await kg.get_stats()

    async def search_entities(self, query: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Search entities by name substring."""
        all_ents = await self.list_entities(limit=10_000)
        q = query.lower().strip()
        if not q:
            return all_ents[:limit]
        return [e for e in all_ents if q in (e.get("name") or "").lower() or
                q in (e.get("kind") or "").lower()][:limit]

    def get_name(self) -> str:
        return "knowledge_graph_ops"

    def get_description(self) -> str:
        return (
            "The Detective's Evidence Board (Knowledge Graph). "
            "Use this to permanently store relationships between entities (e.g., [User]->[owns]->[Server]) "
            "or to query the graph to deduce hidden connections across different case studies."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="The operation to perform: 'add_relationship', 'query_entity', 'find_path'.",
                    required=True,
                    enum=["add_relationship", "query_entity", "find_path"],
                ),
                ToolParameter(
                    name="entity1",
                    type="string",
                    description="The source entity (e.g., 'Swadhin', '192.168.1.50'). Required for add_relationship.",
                    required=False,
                ),
                ToolParameter(
                    name="relation",
                    type="string",
                    description="The relationship verb (e.g., 'OWNS', 'HOSTS_SERVICE', 'VULNERABLE_TO').",
                    required=False,
                ),
                ToolParameter(
                    name="entity2",
                    type="string",
                    description="The target entity (e.g., 'Laptop', 'OpenSSH').",
                    required=False,
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="The name of the entity to query. Required for query_entity.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        kg = await self._get_helix_kg()
        operation = kwargs.get("operation")

        try:
            if operation == "add_relationship":
                e1 = kwargs.get("entity1")
                rel = kwargs.get("relation", "RELATED_TO")
                e2 = kwargs.get("entity2")
                user_id = kwargs.get("user_id")
                if not e1 or not e2:
                    return {
                        "success": False,
                        "error": "entity1 and entity2 are required to add a relationship.",
                    }
                return await kg.add_relationship(e1, rel, e2, user_id=user_id)

            if operation == "query_entity":
                query_name = kwargs.get("query")
                if not query_name:
                    return {"success": False, "error": "query parameter is required."}
                return await kg.query_entity(query_name)

            if operation == "find_path":
                e1 = kwargs.get("entity1")
                e2 = kwargs.get("entity2")
                if not e1 or not e2:
                    return {
                        "success": False,
                        "error": "entity1 and entity2 are required to find a path.",
                    }
                return await kg.find_path(e1, e2)

            return {"success": False, "error": f"Unknown operation {operation}"}
        except Exception as e:  # noqa: BLE001
            logger.error("HelixDB KG Execution Error: %s", e)
            return {"success": False, "error": str(e)}
