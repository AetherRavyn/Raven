import logging
from typing import Optional

from .neo4j import Neo4jGraph
from .postgres import SQLiteDB

# Relative import: monitoring/src/db/ -> monitoring/src/ -> monitoring/ -> monitoring/config/settings
from ...config.settings import db_config

logger = logging.getLogger(__name__)


class initDB:
    """
    Central database handle.  Holds one SQLiteDB (events / tracks / clips)
    and one Neo4jGraph (person identities + sighting relationships).

    Both connections are created eagerly; if Neo4j is unreachable the
    driver is set to None inside Neo4jGraph and every write becomes a no-op,
    so the rest of the system can keep running on SQLite alone.

    Usage
    -----
    db = initDB()                  # uses dbconfig.yaml
    db = initDB(config=my_cfg)     # pass a custom dict {database: {sqlite: …, neo4j: …}}
    """

    def __init__(self, config: Optional[dict] = None):
        cfg = config if config is not None else db_config

        self.sqlite = SQLiteDB(cfg)
        logger.info(
            "SQLite ready: %s",
            cfg.get("database", {}).get("sqlite", {}).get("db_path", "?"),
        )

        self.neo4j = Neo4jGraph(cfg)
        if self.neo4j.driver is not None:
            logger.info(
                "Neo4j ready: %s",
                cfg.get("database", {}).get("neo4j", {}).get("uri", "?"),
            )
        else:
            logger.warning("Neo4j unavailable – running without graph storage")

    # ------------------------------------------------------------------
    # HEALTH
    # ------------------------------------------------------------------

    @property
    def neo4j_ok(self) -> bool:
        """True when the Neo4j driver is connected."""
        return self.neo4j.driver is not None

    @property
    def sqlite_ok(self) -> bool:
        """True when the SQLite engine is initialised."""
        return self.sqlite.engine is not None

    # ------------------------------------------------------------------
    # LIFECYCLE
    # ------------------------------------------------------------------

    def close(self):
        """Gracefully close both database connections."""
        try:
            self.sqlite.close()
        except Exception as e:
            logger.warning("Error closing SQLite: %s", e)
        try:
            self.neo4j.close()
        except Exception as e:
            logger.warning("Error closing Neo4j: %s", e)
        logger.info("initDB closed")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __repr__(self) -> str:
        return (
            f"<initDB sqlite={'ok' if self.sqlite_ok else 'err'} "
            f"neo4j={'ok' if self.neo4j_ok else 'unavailable'}>"
        )
