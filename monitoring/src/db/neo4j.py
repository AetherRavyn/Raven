"""SQLite-backed graph storage for monitoring (replaces Neo4j).

Stores persons, cameras, and their relationships in a local SQLite
database. Same API as the old Neo4jGraph so callers don't change.
"""

import sqlite3
import json
import logging
from typing import List, Dict, Optional
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class Neo4jGraph:
    """SQLite-backed graph (drop-in replacement for Neo4j)."""

    def __init__(self, config: Dict):
        self.config = config.get("database", {}).get("neo4j", {})
        self.driver = None  # kept for API compat — always None
        self._db_path = self.config.get(
            "db_path",
            str(Path(__file__).resolve().parent.parent.parent / "workspace" / "monitoring.sqlite"),
        )
        self._init_db()

    def _init_db(self):
        try:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS persons (
                    person_id TEXT PRIMARY KEY,
                    features TEXT,
                    metadata TEXT,
                    created_at TEXT,
                    last_seen TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cameras (
                    camera_id TEXT PRIMARY KEY,
                    location TEXT,
                    created_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sightings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    person_id TEXT NOT NULL,
                    camera_id TEXT NOT NULL,
                    timestamp TEXT,
                    metadata TEXT,
                    count INTEGER DEFAULT 1,
                    FOREIGN KEY (person_id) REFERENCES persons(person_id),
                    FOREIGN KEY (camera_id) REFERENCES cameras(camera_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS same_as (
                    person_id1 TEXT NOT NULL,
                    person_id2 TEXT NOT NULL,
                    confidence REAL,
                    metadata TEXT,
                    PRIMARY KEY (person_id1, person_id2)
                )
            """)
            conn.commit()
            conn.close()
            self.driver = "sqlite"  # truthy for compat checks
            logger.info("SQLite graph initialized: %s", self._db_path)
        except Exception as e:
            logger.error(f"Failed to initialize SQLite graph: {e}")
            self.driver = None

    def add_person(
        self, person_id: str, features: Optional[List[float]] = None,
        metadata: Optional[Dict] = None,
    ) -> bool:
        if self.driver is None:
            return False
        try:
            conn = sqlite3.connect(self._db_path)
            now = datetime.now().isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO persons (person_id, features, metadata, created_at, last_seen) "
                "VALUES (?, ?, ?, COALESCE((SELECT created_at FROM persons WHERE person_id=?), ?), ?)",
                (person_id, json.dumps(features or []), json.dumps(metadata or {}),
                 person_id, now, now),
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Failed to add person: {e}")
            return False

    def add_camera(self, camera_id: str, location: Optional[str] = None) -> bool:
        if self.driver is None:
            return False
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "INSERT OR IGNORE INTO cameras (camera_id, location, created_at) VALUES (?, ?, ?)",
                (camera_id, location, datetime.now().isoformat()),
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Failed to add camera: {e}")
            return False

    def add_relationship(
        self, person_id: str, camera_id: str, timestamp: datetime,
        relationship_type: str = "SEEN_IN", metadata: Optional[Dict] = None,
    ) -> bool:
        if self.driver is None:
            return False
        try:
            conn = sqlite3.connect(self._db_path)
            # Update existing or insert new
            cur = conn.execute(
                "SELECT id, count FROM sightings WHERE person_id=? AND camera_id=?",
                (person_id, camera_id),
            )
            row = cur.fetchone()
            if row:
                conn.execute(
                    "UPDATE sightings SET timestamp=?, metadata=?, count=? WHERE id=?",
                    (timestamp.isoformat(), json.dumps(metadata or {}), row[1] + 1, row[0]),
                )
            else:
                conn.execute(
                    "INSERT INTO sightings (person_id, camera_id, timestamp, metadata, count) "
                    "VALUES (?, ?, ?, ?, 1)",
                    (person_id, camera_id, timestamp.isoformat(), json.dumps(metadata or {})),
                )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Failed to add relationship: {e}")
            return False

    def add_same_as(
        self, person_id1: str, person_id2: str, confidence: float,
        metadata: Optional[Dict] = None,
    ) -> bool:
        if self.driver is None:
            return False
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "INSERT OR REPLACE INTO same_as (person_id1, person_id2, confidence, metadata) "
                "VALUES (?, ?, ?, ?)",
                (person_id1, person_id2, confidence, json.dumps(metadata or {})),
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Failed to add SAME_AS: {e}")
            return False

    def find_similar_persons(self, person_id: str, threshold: float = 0.8) -> List[Dict]:
        if self.driver is None:
            return []
        try:
            conn = sqlite3.connect(self._db_path)
            rows = conn.execute(
                "SELECT person_id2, confidence FROM same_as "
                "WHERE person_id1=? AND confidence>=?",
                (person_id, threshold),
            ).fetchall()
            conn.close()
            return [{"person_id": r[0], "confidence": r[1]} for r in rows]
        except Exception as e:
            logger.error(f"Failed to find similar persons: {e}")
            return []

    def get_person_history(self, person_id: str) -> List[Dict]:
        if self.driver is None:
            return []
        try:
            conn = sqlite3.connect(self._db_path)
            rows = conn.execute(
                "SELECT camera_id, timestamp, metadata FROM sightings "
                "WHERE person_id=? ORDER BY timestamp DESC LIMIT 50",
                (person_id,),
            ).fetchall()
            conn.close()
            return [{"camera_id": r[0], "timestamp": r[1], "metadata": r[2]} for r in rows]
        except Exception as e:
            logger.error(f"Failed to get person history: {e}")
            return []

    def get_cameras_for_person(self, person_id: str) -> List[str]:
        if self.driver is None:
            return []
        try:
            conn = sqlite3.connect(self._db_path)
            rows = conn.execute(
                "SELECT DISTINCT camera_id FROM sightings WHERE person_id=?",
                (person_id,),
            ).fetchall()
            conn.close()
            return [r[0] for r in rows]
        except Exception as e:
            logger.error(f"Failed to get cameras: {e}")
            return []

    def close(self):
        self.driver = None
        logger.info("SQLite graph closed")
