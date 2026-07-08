# Graph Indexing System – Quick Reference Guide

> **Purpose**: This document provides a concise, high‑level overview of the indexing/graph subsystem used throughout the RAVEN codebase. It is intended for AI agents (or developers) that need to reason about the system without digging into every source file.

---

## 1. Core Concepts

| Concept | Description |
|---|---|
| **WorkspaceGraph** | Small, local view of a user’s workspace. Generates *nodes* and *edges* from user profile, memory manager, and preferences. |
| **KnowledgeGraphTool** | Wrapper around the external graph store (Neo4j by default). Provides async `execute` calls for `add_relationship`, `query`, etc. |
| **DeviceGraph** | Persists device‑state information (online/offline, sensor values). Used by the Edge API. |
| **Neo4jGraph** | Low‑level driver for Neo4j. Handles actual persistence of nodes/relationships. |
| **MemoryManager** | Retrieves recent memories for a user (vector store) and builds a profile summary. |
| **UserProfileStore** | Loads/stores per‑user profile data (preferences, facts, tasks, projects, files, devices, decisions). |

---

## 2. Main Files & Entry Points

- `app/core/workspace_graph.py` – Implements `WorkspaceGraph` with methods:
  - `build_for_user(user_id, query=None)` → `{nodes, edges}`
  - `sync_user(user_id, query=None)` → pushes nodes/edges to the graph tool.
  - `evidence_for_prompt(user_id, query=None)` → list of short strings for LLM prompts.
- `app/tools/kgtool.py` – Defines `KnowledgeGraphTool` (async API to Neo4j). Used lazily by `WorkspaceGraph.sync_user`.
- `app/api/edge.py` – Exposes a **DeviceGraph** REST API for registering nodes, updating sensor state, and querying active nodes.
- `monitoring/src/db/neo4j.py` – Low‑level Neo4j driver implementation.
- `app/settings/config.py` – Configuration constants, notably `GRAPH_DB_PATH` (default `MEMORY_ROOT/graph/raven.sqlite`).

---

## 3. Data Flow Overview

```mermaid
flowchart TD
    UserProfileStore --> WorkspaceGraph
    MemoryManager --> WorkspaceGraph
    WorkspaceGraph --> KnowledgeGraphTool --> Neo4jGraph
    DeviceGraph --> Edge API --> DeviceGraph (persistence)
```

1. **Profile Load** – `WorkspaceGraph` loads a `UserProfileStore` for the given `user_id`.
2. **Memory Retrieval** – `MemoryManager.retrieve_context` pulls the most relevant memories (top‑k = 8).
3. **Node/Edge Construction** – Helper methods `_node`, `_edge`, `_stable_id` create deterministic structures.
4. **Sync** – `sync_user` lazily imports `KnowledgeGraphTool` and iterates over nodes/edges, invoking `execute(operation="add_relationship", ...)`.
5. **Device State** – `DeviceGraph` maintains a dict of devices, persisting via `_save()` (SQLite/Neo4j depending on config).

---

## 4. Indexing Process (What gets stored?)

- **Node Types**: `user`, `preference`, `fact`, `task`, `project`, `file`, `device`, `decision`, `memory`.
- **Edges**: Relationships such as `PREFERS`, `KNOWS`, `TRACKS`, `OWNS_PROJECT`, `USES_FILE`, `USES_DEVICE`, `MADE_DECISION`, `REMEMBERS`, `PROFILE_HINT`.
- **Stable IDs** – Generated via SHA‑1 of concatenated parts (`_stable_id`) to ensure deterministic identifiers across runs.
- **Metadata** – Each node/edge carries `user_id` and optional extra fields (e.g., `timezone`, `preferred_language`).

---

## 5. Integration Points

| Integration | How to Use |
|---|---|
| **LLM Prompt Generation** | Call `WorkspaceGraph.evidence_for_prompt(user_id, query)` to obtain a concise list of strings describing the graph. Useful for context injection. |
| **Graph Sync** | Invoke `await WorkspaceGraph.sync_user(user_id, query)` to push the latest view to the external Neo4j store. |
| **Device API** | Use the FastAPI routes in `app/api/edge.py` (`/register_node`, `/update_sensor_state`, `/active_nodes`) to keep device state in sync with the graph. |
| **Custom Graph Tool** | Replace `KnowledgeGraphTool` with any async object exposing `execute(operation, **kwargs)` – the rest of the system remains unchanged. |

---

## 6. Extending / Customising

1. **Add New Node Types** – Extend the `for`‑loop in `build_for_user` (lines 72‑80) with a new `(category, values, relation)` tuple.
2. **Custom Edge Logic** – Modify `_edge` or add post‑processing after node creation before returning the graph dict.
3. **Alternative Persistence** – Swap `Neo4jGraph` for another backend by editing `monitoring/src/db/neo4j.py` and updating `GRAPH_DB_PATH` in `config.py`.
4. **Batch Sync** – For large graphs, batch `execute` calls or implement a bulk import method inside `KnowledgeGraphTool`.

---

## 7. Quick Example (Python)

```python
from app.core.workspace_graph import WorkspaceGraph
import asyncio

async def demo():
    wg = WorkspaceGraph()
    # Build a lightweight view for user "u1"
    graph = wg.build_for_user("u1", query="concise")
    print("Nodes:", len(graph["nodes"]))
    print("Edges:", len(graph["edges"]))
    # Push to external store (if available)
    synced = await wg.sync_user("u1")
    print("Synced:", synced)
    # Get prompt‑ready evidence
    evidence = wg.evidence_for_prompt("u1")
    print("\n".join(evidence))

asyncio.run(demo())
```

---

## 8. Frequently Asked Questions

- **Do I need Neo4j installed?**
  - No. If the `KnowledgeGraphTool` cannot be imported, `sync_user` silently returns with zero sync counts. The system falls back to a *local‑only* view.
- **Where are device states stored?**
  - In `monitoring/src/db/neo4j.py` (Neo4j) or a SQLite fallback defined by `GRAPH_DB_PATH`.
- **How are stable IDs generated?**
  - SHA‑1 of the concatenated string parts, truncated to 12 hex characters (`_stable_id`).
- **Can I query the graph directly?**
  - Yes, via the `KnowledgeGraphTool.execute(operation="query", cypher="MATCH ...")` interface.

---

*This guide is deliberately concise; for deeper details, refer to the source files listed in Section 2.*
