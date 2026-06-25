"""SQL Database Connector — query SQLite, MySQL, PostgreSQL databases.

Provides a DatabaseQueryTool that connects to arbitrary databases,
executes read-only queries, and returns structured results.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class DatabaseConnector(BaseTool):
    """Connect to and query SQLite, MySQL, or PostgreSQL databases."""

    def get_name(self) -> str:
        return "database_query"

    def get_description(self) -> str:
        return (
            "Query SQLite, MySQL, or PostgreSQL databases. "
            "Execute read-only SQL queries, list tables, get schema info. "
            "Connection strings: sqlite:///path, mysql://user:pass@host/db, postgresql://user:pass@host/db"
        )

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["query", "list_tables", "schema", "stats", "connect"],
                    "description": "Operation to perform",
                },
                "connection_string": {
                    "type": "string",
                    "description": "Database connection string (sqlite:///path, mysql://..., postgresql://...)",
                },
                "query": {"type": "string", "description": "SQL query (read-only)"},
                "params": {"type": "array", "description": "Query parameters"},
            },
            "required": ["operation"],
        }

    def __init__(self, **kwargs: Any) -> None:
        self._connections: dict[str, Any] = {}

    async def execute(self, **kwargs: Any) -> dict:
        operation = kwargs.get("operation", "connect")
        conn_str = kwargs.get("connection_string", "")
        query = kwargs.get("query", "")
        params = kwargs.get("params", [])

        if operation == "connect":
            return self._connect(conn_str)

        if not conn_str:
            return {"error": "connection_string is required"}

        conn = self._get_connection(conn_str)
        if conn is None:
            return {"error": f"Not connected to {conn_str[:50]}. Use operation=connect first."}

        if operation == "query":
            return self._execute_query(conn, query, params, conn_str)
        elif operation == "list_tables":
            return self._list_tables(conn, conn_str)
        elif operation == "schema":
            return self._get_schema(conn, query, conn_str)
        elif operation == "stats":
            return self._get_stats(conn, conn_str)

        return {"error": f"Unknown operation: {operation}"}

    def _connect(self, conn_str: str) -> dict:
        """Connect to a database."""
        if not conn_str:
            return {"error": "connection_string is required"}

        try:
            if conn_str.startswith("sqlite"):
                return self._connect_sqlite(conn_str)
            elif conn_str.startswith("mysql"):
                return self._connect_mysql(conn_str)
            elif conn_str.startswith("postgresql"):
                return self._connect_postgres(conn_str)
            else:
                return {"error": f"Unsupported database type: {conn_str.split(':')[0]}"}
        except Exception as e:
            return {"error": str(e)[:500]}

    def _connect_sqlite(self, conn_str: str) -> dict:
        """Connect to a SQLite database."""
        import sqlite3

        # Parse: sqlite:///path or sqlite://:memory:
        path = conn_str.replace("sqlite:///", "").replace("sqlite://", "")
        if path == ":memory:":
            conn = sqlite3.connect(":memory:")
        else:
            path = Path(path)
            if not path.exists():
                return {"error": f"Database file not found: {path}"}
            conn = sqlite3.connect(str(path))
            conn.row_factory = sqlite3.Row

        self._connections[conn_str] = {"conn": conn, "type": "sqlite", "path": str(path)}
        return {"success": True, "type": "sqlite", "path": str(path)}

    def _connect_mysql(self, conn_str: str) -> dict:
        """Connect to a MySQL database."""
        try:
            import pymysql
            # Parse: mysql://user:pass@host:port/db
            from urllib.parse import urlparse
            parsed = urlparse(conn_str)
            conn = pymysql.connect(
                host=parsed.hostname or "localhost",
                port=parsed.port or 3306,
                user=parsed.username or "",
                password=parsed.password or "",
                database=parsed.path.lstrip("/") or "",
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
            )
            self._connections[conn_str] = {"conn": conn, "type": "mysql"}
            return {"success": True, "type": "mysql", "host": parsed.hostname}
        except ImportError:
            return {"error": "pymysql not installed. Run: pip install pymysql"}
        except Exception as e:
            return {"error": str(e)[:500]}

    def _connect_postgres(self, conn_str: str) -> dict:
        """Connect to a PostgreSQL database."""
        try:
            import psycopg2
            import psycopg2.extras
            conn = psycopg2.connect(conn_str)
            conn.cursor_factory = psycopg2.extras.RealDictCursor
            self._connections[conn_str] = {"conn": conn, "type": "postgresql"}
            return {"success": True, "type": "postgresql"}
        except ImportError:
            return {"error": "psycopg2 not installed. Run: pip install psycopg2-binary"}
        except Exception as e:
            return {"error": str(e)[:500]}

    def _get_connection(self, conn_str: str) -> Any | None:
        info = self._connections.get(conn_str)
        return info["conn"] if info else None

    def _execute_query(self, conn: Any, query: str, params: list, conn_str: str) -> dict:
        """Execute a read-only query."""
        if not query:
            return {"error": "query is required"}

        # Safety: only allow SELECT, EXPLAIN, PRAGMA
        safe_prefixes = ("SELECT", "EXPLAIN", "PRAGMA", "SHOW", "DESCRIBE", "WITH")
        if not query.strip().upper().startswith(safe_prefixes):
            return {"error": "Only SELECT, EXPLAIN, PRAGMA queries are allowed (read-only)"}

        conn_type = self._connections.get(conn_str, {}).get("type", "sqlite")

        try:
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)

            # Fetch results
            if cursor.description:
                rows = cursor.fetchall()
                if conn_type == "sqlite":
                    columns = [desc[0] for desc in cursor.description]
                    result_rows = [dict(row) for row in rows]
                elif conn_type == "mysql":
                    result_rows = [dict(row) for row in rows]
                    columns = list(result_rows[0].keys()) if result_rows else []
                else:
                    result_rows = [dict(row) for row in rows]
                    columns = list(result_rows[0].keys()) if result_rows else []

                # Truncate large results
                if len(result_rows) > 100:
                    result_rows = result_rows[:100]
                    truncated = True
                else:
                    truncated = False

                return {
                    "success": True,
                    "columns": columns,
                    "rows": result_rows,
                    "row_count": len(result_rows),
                    "truncated": truncated,
                }
            else:
                return {"success": True, "message": "Query executed (no results returned)"}

        except Exception as e:
            return {"error": str(e)[:500]}

    def _list_tables(self, conn: Any, conn_str: str) -> dict:
        """List all tables in the database."""
        conn_type = self._connections.get(conn_str, {}).get("type", "sqlite")
        try:
            cursor = conn.cursor()
            if conn_type == "sqlite":
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
            elif conn_type == "mysql":
                cursor.execute("SHOW TABLES")
            elif conn_type == "postgresql":
                cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")

            rows = cursor.fetchall()
            tables = [dict(row).get("name", dict(row).get("tablename", "")) for row in rows]
            return {"success": True, "tables": tables, "count": len(tables)}
        except Exception as e:
            return {"error": str(e)[:500]}

    def _get_schema(self, conn: Any, table_name: str, conn_str: str) -> dict:
        """Get schema for a specific table."""
        conn_type = self._connections.get(conn_str, {}).get("type", "sqlite")
        try:
            cursor = conn.cursor()
            if conn_type == "sqlite":
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = [{"name": row[1], "type": row[2], "not_null": bool(row[3]), "pk": bool(row[5])} for row in cursor.fetchall()]
            elif conn_type == "mysql":
                cursor.execute(f"DESCRIBE {table_name}")
                columns = [{"name": row[0], "type": row[1], "not_null": row[2] == "NO", "pk": row[3] == "PRI"} for row in cursor.fetchall()]
            elif conn_type == "postgresql":
                cursor.execute("""
                    SELECT column_name, data_type, is_nullable, column_default
                    FROM information_schema.columns WHERE table_name = %s ORDER BY ordinal_position
                """, (table_name,))
                columns = [{"name": row[0], "type": row[1], "not_null": row[2] == "NO", "default": row[3]} for row in cursor.fetchall()]

            return {"success": True, "table": table_name, "columns": columns}
        except Exception as e:
            return {"error": str(e)[:500]}

    def _get_stats(self, conn: Any, conn_str: str) -> dict:
        """Get database statistics."""
        conn_type = self._connections.get(conn_str, {}).get("type", "sqlite")
        try:
            cursor = conn.cursor()
            if conn_type == "sqlite":
                # Get table count and sizes
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [row[0] for row in cursor.fetchall()]
                stats = {"type": "sqlite", "tables": len(tables), "table_names": tables}

                # Get file size
                path = self._connections[conn_str].get("path", "")
                if path and Path(path).exists():
                    stats["file_size_bytes"] = Path(path).stat().st_size

                return {"success": True, "stats": stats}
            elif conn_type == "mysql":
                cursor.execute("SHOW DATABASES")
                return {"success": True, "stats": {"type": "mysql", "tables": "use list_tables"}}
            else:
                return {"success": True, "stats": {"type": conn_type}}

        except Exception as e:
            return {"error": str(e)[:500]}


class RESTAPIConnector(BaseTool):
    """Connect to REST APIs with automatic documentation."""

    def get_name(self) -> str:
        return "rest_api"

    def get_description(self) -> str:
        return (
            "Make REST API calls with GET, POST, PUT, DELETE. "
            "Supports headers, query params, JSON body, and basic auth."
        )

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "API endpoint URL"},
                "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"], "default": "GET"},
                "headers": {"type": "object", "description": "HTTP headers"},
                "params": {"type": "object", "description": "Query parameters"},
                "body": {"type": "object", "description": "JSON body for POST/PUT"},
                "auth_token": {"type": "string", "description": "Bearer token for auth"},
            },
            "required": ["url"],
        }

    async def execute(self, **kwargs: Any) -> dict:
        url = kwargs.get("url", "")
        method = kwargs.get("method", "GET").upper()
        headers = kwargs.get("headers", {})
        params = kwargs.get("params", {})
        body = kwargs.get("body")
        auth_token = kwargs.get("auth_token", "")

        if not url:
            return {"error": "url is required"}

        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        if body and "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"

        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                kwargs_httpx: dict[str, Any] = {"url": url, "headers": headers}
                if params:
                    kwargs_httpx["params"] = params
                if body:
                    kwargs_httpx["json"] = body

                method_map = {"GET": client.get, "POST": client.post, "PUT": client.put,
                              "DELETE": client.delete, "PATCH": client.patch}
                response = await method_map[method](**kwargs_httpx)

                # Try to parse JSON response
                try:
                    data = response.json()
                except Exception:
                    data = response.text[:5000]

                return {
                    "success": response.status_code < 400,
                    "status_code": response.status_code,
                    "data": data,
                    "headers": dict(response.headers),
                }
        except Exception as e:
            return {"error": str(e)[:500]}
