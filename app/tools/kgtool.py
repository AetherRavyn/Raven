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
    Interfaces with Neo4j to store and query the Detective's 'Evidence Board'.
    Allows the agent to perform Graph-RAG deductive reasoning.
    """

    def __init__(self, uri: str = None, user: str = None, password: str = None):
        self.uri = uri or getattr(Config, "NEO4J_URI", "bolt://localhost:7687")
        self.user = user or getattr(Config, "NEO4J_USER", "neo4j")
        self.password = password or getattr(Config, "NEO4J_PASSWORD", "password")
        self._driver: Optional[AsyncDriver] = None

    async def _get_driver(self):
        if not self._driver and AsyncGraphDatabase:
            try:
                self._driver = AsyncGraphDatabase.driver(
                    self.uri, auth=(self.user, self.password)
                )
            except Exception as e:
                logger.error(f"Failed to connect to Neo4j: {e}")
        return self._driver

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
                connections = []
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

        except Exception as e:
            logger.error(f"Neo4j Execution Error: {e}")
            return {"success": False, "error": str(e)}
