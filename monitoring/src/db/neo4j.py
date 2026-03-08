from neo4j import GraphDatabase
from typing import List, Dict, Optional
from datetime import datetime
import logging
import json

logger = logging.getLogger(__name__)


class Neo4jGraph:
    def __init__(self, config: Dict):
        self.config = config.get("database", {}).get("neo4j", {})
        self.driver = None
        self._init_driver()

    def _init_driver(self):
        try:
            self.driver = GraphDatabase.driver(
                self.config.get("uri"),
                auth=(
                    self.config.get("user"),
                    self.config.get("password"),
                ),
            )
            self._create_constraints()
            logger.info("Neo4j driver initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Neo4j driver: {e}")
            self.driver = None

    def _create_constraints(self):
        if self.driver is None:
            return

        with self.driver.session() as session:
            try:
                session.run("""
                    CREATE CONSTRAINT IF NOT EXISTS FOR (p:Person) 
                    REQUIRE p.person_id IS UNIQUE
                """)
                session.run("""
                    CREATE CONSTRAINT IF NOT EXISTS FOR (c:Camera) 
                    REQUIRE c.camera_id IS UNIQUE
                """)
            except Exception as e:
                logger.error(f"Failed to create constraints: {e}")

    def add_person(
        self,
        person_id: str,
        features: Optional[List[float]] = None,
        metadata: Optional[Dict] = None,
    ) -> bool:
        if self.driver is None:
            return False

        with self.driver.session() as session:
            try:
                session.run(
                    """
                    MERGE (p:Person {person_id: $person_id})
                    SET p.features = $features,
                        p.metadata = $metadata,
                        p.created_at = COALESCE(p.created_at, timestamp()),
                        p.last_seen = timestamp()
                """,
                    person_id=person_id,
                    features=features,
                    metadata=json.dumps(metadata or {}),
                )
                return True
            except Exception as e:
                logger.error(f"Failed to add person: {e}")
                return False

    def add_camera(self, camera_id: str, location: Optional[str] = None) -> bool:
        if self.driver is None:
            return False

        with self.driver.session() as session:
            try:
                session.run(
                    """
                    MERGE (c:Camera {camera_id: $camera_id})
                    SET c.location = $location,
                        c.created_at = COALESCE(c.created_at, timestamp())
                """,
                    camera_id=camera_id,
                    location=location,
                )
                return True
            except Exception as e:
                logger.error(f"Failed to add camera: {e}")
                return False

    def add_relationship(
        self,
        person_id: str,
        camera_id: str,
        timestamp: datetime,
        relationship_type: str = "SEEN_IN",
        metadata: Optional[Dict] = None,
    ) -> bool:
        if self.driver is None:
            return False

        with self.driver.session() as session:
            try:
                session.run(
                    f"""
                    MATCH (p:Person {{person_id: $person_id}})
                    MATCH (c:Camera {{camera_id: $camera_id}})
                    MERGE (p)-[r:{relationship_type}]->(c)
                    SET r.timestamp = $timestamp,
                        r.metadata = $metadata,
                        r.count = COALESCE(r.count, 0) + 1
                """,
                    person_id=person_id,
                    camera_id=camera_id,
                    timestamp=timestamp.isoformat(),
                    metadata=json.dumps(metadata or {}),
                )
                return True
            except Exception as e:
                logger.error(f"Failed to add relationship: {e}")
                return False

    def add_same_as(
        self,
        person_id1: str,
        person_id2: str,
        confidence: float,
        metadata: Optional[Dict] = None,
    ) -> bool:
        if self.driver is None:
            return False

        with self.driver.session() as session:
            try:
                session.run(
                    """
                    MATCH (p1:Person {person_id: $person_id1})
                    MATCH (p2:Person {person_id: $person_id2})
                    MERGE (p1)-[r:SAME_AS {confidence: $confidence, metadata: $metadata}]->(p2)
                """,
                    person_id1=person_id1,
                    person_id2=person_id2,
                    confidence=confidence,
                    metadata=json.dumps(metadata or {}),
                )
                return True
            except Exception as e:
                logger.error(f"Failed to add SAME_AS relationship: {e}")
                return False

    def find_similar_persons(
        self, person_id: str, threshold: float = 0.8
    ) -> List[Dict]:
        if self.driver is None:
            return []

        with self.driver.session() as session:
            try:
                result = session.run(
                    """
                    MATCH (p1:Person {person_id: $person_id})-[r:SAME_AS]->(p2:Person)
                    WHERE r.confidence >= $threshold
                    RETURN p2.person_id as person_id, r.confidence as confidence
                """,
                    person_id=person_id,
                    threshold=threshold,
                )
                return [
                    {"person_id": r["person_id"], "confidence": r["confidence"]}
                    for r in result
                ]
            except Exception as e:
                logger.error(f"Failed to find similar persons: {e}")
                return []

    def get_person_history(self, person_id: str) -> List[Dict]:
        if self.driver is None:
            return []

        with self.driver.session() as session:
            try:
                result = session.run(
                    """
                    MATCH (p:Person {person_id: $person_id})-[r:SEEN_IN]->(c:Camera)
                    RETURN c.camera_id as camera_id, r.timestamp as timestamp, r.metadata as metadata
                    ORDER BY r.timestamp DESC
                    LIMIT 50
                """,
                    person_id=person_id,
                )
                return [
                    {
                        "camera_id": r["camera_id"],
                        "timestamp": r["timestamp"],
                        "metadata": r["metadata"],
                    }
                    for r in result
                ]
            except Exception as e:
                logger.error(f"Failed to get person history: {e}")
                return []

    def get_cameras_for_person(self, person_id: str) -> List[str]:
        if self.driver is None:
            return []

        with self.driver.session() as session:
            try:
                result = session.run(
                    """
                    MATCH (p:Person {person_id: $person_id})-[r:SEEN_IN]->(c:Camera)
                    RETURN DISTINCT c.camera_id as camera_id
                """,
                    person_id=person_id,
                )
                return [r["camera_id"] for r in result]
            except Exception as e:
                logger.error(f"Failed to get cameras for person: {e}")
                return []

    def close(self):
        if self.driver:
            self.driver.close()
            logger.info("Neo4j driver closed")
