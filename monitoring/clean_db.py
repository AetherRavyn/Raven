from src.db import initDB
import logging

logging.basicConfig(level=logging.INFO)
db = initDB()

if db.neo4j.driver:
    with db.neo4j.driver.session() as session:
        # Delete all persons with 1000-dimensional embeddings (from the old model)
        result = session.run("MATCH (p:Person) WHERE size(p.features) = 1000 DETACH DELETE p RETURN count(p) as deleted_count")
        deleted = result.single()["deleted_count"]
        print(f"Deleted {deleted} old Person nodes from Neo4j.")

if db.sqlite.engine:
    with db.sqlite.engine.begin() as conn:
        from sqlalchemy import text
        # Optionally delete old events, but let's just clean up the Neo4j nodes for now
        pass

db.close()
