import logging
from typing import Any, Dict, List, Optional

try:
    from neo4j import AsyncDriver, AsyncGraphDatabase
except ImportError:
    AsyncGraphDatabase = None

from app.settings.config import Config
from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class KnowledgeGraphTool(BaseTool):
    """
    Knowledge graph with two interchangeable backends:

    * **neo4j** (default) — the original implementation, uses the
      official Neo4j Python driver.
    * **helix** — the Phase B replacement backed by HelixDB
      (``app.db.knowledge_graph_helix.HelixKnowledgeGraph``).  Same
      ``add_relationship`` / ``query_entity`` / ``find_path`` API
      and the same return shape, so callers don't change.

    Select with ``KG_BACKEND=helix`` in the environment.  The
    Neo4j driver is imported lazily and the connection is only
    opened on first use, so installing the package isn't required
    when running on the HelixDB backend.
    """

    def __init__(self, uri: str = None, user: str = None, password: str = None):
        self.uri = uri or getattr(Config, "NEO4J_URI", "bolt://localhost:7687")
        self.user = user or getattr(Config, "NEO4J_USER", "neo4j")
        self.password = password or getattr(Config, "NEO4J_PASSWORD", "password")
        self._driver: Optional[AsyncDriver] = None
        self._helix_kg: Any = None
        # Re-read the env var on every construction so tests using
        # ``monkeypatch.setenv("KG_BACKEND", "helix")`` work even
        # after the Config module has been imported.
        import os as _os

        self.backend: str = (
            _os.getenv("KG_BACKEND")
            or getattr(Config, "KG_BACKEND", "neo4j")
            or "neo4j"
        ).lower()

    @property
    def is_helix(self) -> bool:
        return self.backend == "helix"

    async def _get_helix_kg(self) -> Any:
        if self._helix_kg is None:
            from app.db.knowledge_graph_helix import HelixKnowledgeGraph

            self._helix_kg = HelixKnowledgeGraph()
        return self._helix_kg

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
        if self.is_helix:
            return await self._execute_helix(**kwargs)
        return await self._execute_neo4j(**kwargs)

    async def _execute_helix(self, **kwargs: Any) -> Dict[str, Any]:
        """Delegate to the HelixDB-backed implementation."""
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

    async def _execute_neo4j(self, **kwargs: Any) -> Dict[str, Any]:
        if not AsyncGraphDatabase:
            return {
                "success": False,
                "error": "Neo4j driver is not installed. Run `pip install neo4j`.",
            }

        driver = await self._get_driver()
        if not driver:
            return {
                "success": False,
                "error": "Could not connect to the Neo4j database. Ensure it is running.",
            }

        operation = kwargs.get("operation")

        try:
            if operation == "add_relationship":
                e1 = kwargs.get("entity1")
                rel = kwargs.get("relation", "RELATED_TO").upper().replace(" ", "_")
                e2 = kwargs.get("entity2")

                if not e1 or not e2:
                    return {
                        "success": False,
                        "error": "entity1 and entity2 are required to add a relationship.",
                    }

                query = (
                    "MERGE (a:Entity {name: $e1}) "
                    "MERGE (b:Entity {name: $e2}) "
                    f"MERGE (a)-[r:{rel}]->(b) "
                    "RETURN a.name, type(r), b.name"
                )
                async with driver.session() as session:
                    result = await session.run(query, e1=e1, e2=e2)
                    record = await result.single()
                    if record:
                        return {
                            "success": True,
                            "message": f"Added: [{record[0]}] -> [{record[1]}] -> [{record[2]}]",
                        }
                return {"success": False, "error": "Failed to merge relationship."}

            elif operation == "query_entity":
                query_name = kwargs.get("query")
                if not query_name:
                    return {"success": False, "error": "query parameter is required."}

                query = (
                    "MATCH (a:Entity {name: $name})-[r]-(b) "
                    "RETURN a.name, type(r), b.name, startNode(r) = a as is_outgoing "
                    "LIMIT 50"
                )
                connections: List[str] = []
                async with driver.session() as session:
                    result = await session.run(query, name=query_name)
                    async for record in result:
                        if record["is_outgoing"]:
                            connections.append(
                                f"[{record[0]}] --({record[1]})--> [{record[2]}]"
                            )
                        else:
                            connections.append(
                                f"[{record[2]}] --({record[1]})--> [{record[0]}]"
                            )

                return {
                    "success": True,
                    "entity": query_name,
                    "connections": connections
                    or ["No connections found in the graph."],
                }

            elif operation == "find_path":
                e1 = kwargs.get("entity1")
                e2 = kwargs.get("entity2")
                if not e1 or not e2:
                    return {
                        "success": False,
                        "error": "entity1 and entity2 are required to find a path.",
                    }

                query = (
                    "MATCH p=shortestPath((a:Entity {name: $e1})-[:*1..4]-(b:Entity {name: $e2})) "
                    "RETURN [n in nodes(p) | n.name] as path"
                )
                async with driver.session() as session:
                    result = await session.run(query, e1=e1, e2=e2)
                    record = await result.single()
                    if record:
                        return {"success": True, "path": record["path"]}
                return {
                    "success": True,
                    "message": f"No direct path found between {e1} and {e2} within 4 hops.",
                }

            return {"success": False, "error": f"Unknown operation {operation}"}

        except Exception as e:  # noqa: BLE001
            logger.error(f"Neo4j Execution Error: {e}")
            return {"success": False, "error": str(e)}

    async def _get_driver(self) -> Optional[AsyncDriver]:
        if not self._driver and AsyncGraphDatabase:
            try:
                self._driver = AsyncGraphDatabase.driver(
                    self.uri, auth=(self.user, self.password)
                )
            except Exception as e:
                logger.error(f"Failed to connect to Neo4j: {e}")
        return self._driver
