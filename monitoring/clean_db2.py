from src.db import initDB
import logging

logging.basicConfig(level=logging.INFO)
db = initDB()

if db.neo4j.driver:
    with db.neo4j.driver.session() as session:
        result = session.run("MATCH (p:Person) WHERE size(p.features) <> 512 DETACH DELETE p RETURN count(p) as deleted_count")
        deleted = result.single()["deleted_count"]
        print(f"Deleted {deleted} other invalid Person nodes from Neo4j.")

db.close()
