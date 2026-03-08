from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Union

from supabase import create_client, Client

from app.tools.base import BaseTool, ToolParameter, ToolSchema  # assuming this exists


class SupabaseTool(BaseTool):
    def __init__(self, url: str, key: str):
        self.url = url
        self.key = key
        self._client: Optional[Client] = None

    def _get_client(self) -> Client:
        if self._client is None:
            self._client = create_client(self.url, self.key)
        return self._client

    def get_name(self) -> str:
        return "supabase"

    def get_description(self) -> str:
        return (
            "Interact with Supabase: database (CRUD, count), storage (files), "
            "basic RPC, and admin auth (needs service_role key)."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    required=True,
                    description="Operation to perform",
                    enum=[
                        # Database
                        "insert",
                        "bulk_insert",
                        "select",
                        "update",
                        "delete",
                        "upsert",
                        "count",
                        # Advanced DB
                        "rpc",
                        # Storage
                        "upload_file",
                        "download_file",
                        "list_files",
                        "delete_file",
                        "create_bucket",
                        # Auth (admin – requires service_role key!)
                        "list_users",
                        "get_user",
                    ],
                ),
                ToolParameter(
                    name="table",
                    type="string",
                    required=False,
                    description="Database table name",
                ),
                ToolParameter(
                    name="data",
                    type="object",
                    required=False,
                    description="Data for insert/update/upsert",
                ),
                ToolParameter(
                    name="rows",
                    type="array",
                    required=False,
                    description="Rows for bulk insert",
                ),
                ToolParameter(
                    name="filters",
                    type="object",
                    description="e.g. {'status': 'active', 'age_gt': 18, 'id_in': [1,3,5]}",
                    required=False,
                ),
                ToolParameter(
                    name="columns",
                    type="array",
                    required=False,
                    description="Columns to select",
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    required=False,
                    description="Result limit",
                ),
                ToolParameter(
                    name="offset",
                    type="integer",
                    required=False,
                    description="Result offset",
                ),
                ToolParameter(
                    name="order_by",
                    type="string",
                    required=False,
                    description="Column to order by",
                ),
                ToolParameter(
                    name="ascending",
                    type="boolean",
                    required=False,
                    description="Sort ascending",
                ),
                ToolParameter(
                    name="rpc_name",
                    type="string",
                    required=False,
                    description="RPC function name",
                ),
                ToolParameter(
                    name="params",
                    type="object",
                    required=False,
                    description="RPC parameters",
                ),
                ToolParameter(
                    name="bucket",
                    type="string",
                    required=False,
                    description="Storage bucket name",
                ),
                ToolParameter(
                    name="file_path",
                    type="string",
                    required=False,
                    description="Local file path",
                ),
                ToolParameter(
                    name="storage_path",
                    type="string",
                    required=False,
                    description="Remote storage path",
                ),
                ToolParameter(
                    name="user_id",
                    type="string",
                    required=False,
                    description="User ID for auth operations",
                ),
            ],
        )

    async def execute(
        self,
        operation: str,
        table: Optional[str] = None,
        data: Optional[Dict] = None,
        rows: Optional[List[Dict]] = None,
        filters: Optional[Dict[str, Any]] = None,
        columns: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0,
        order_by: Optional[str] = None,
        ascending: bool = True,
        rpc_name: Optional[str] = None,
        params: Optional[Dict] = None,
        bucket: Optional[str] = None,
        file_path: Optional[str] = None,
        storage_path: Optional[str] = None,
        user_id: Optional[str] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        try:
            client = self._get_client()

            # ── DATABASE OPERATIONS ────────────────────────────────────────
            if operation in (
                "insert",
                "bulk_insert",
                "select",
                "update",
                "delete",
                "upsert",
                "count",
            ):
                if not table:
                    raise ValueError("table is required for database operations")

                query = client.table(table)

                # Apply filters (improved version)
                if filters:
                    for key, value in filters.items():
                        if key.endswith("_gt"):
                            query = query.gt(key[:-3], value)
                        elif key.endswith("_gte"):
                            query = query.gte(key[:-4], value)
                        elif key.endswith("_lt"):
                            query = query.lt(key[:-3], value)
                        elif key.endswith("_lte"):
                            query = query.lte(key[:-4], value)
                        elif key.endswith("_in"):
                            query = query.in_(
                                key[:-3], value if isinstance(value, list) else [value]
                            )
                        elif key.endswith("_neq"):
                            query = query.neq(key[:-4], value)
                        else:
                            # default .eq()
                            query = query.eq(key, value)

            if operation == "insert":
                if not data:
                    raise ValueError("data is required for insert")
                result = query.insert(data).execute()
                return {"success": True, "data": result.data}

            if operation == "bulk_insert":
                if not rows:
                    raise ValueError("rows is required for bulk_insert")
                result = query.insert(rows).execute()
                return {
                    "success": True,
                    "inserted": len(result.data or []),
                    "data": result.data,
                }

            if operation == "select":
                sel = ",".join(columns) if columns else "*"
                query = query.select(sel)
                if order_by:
                    query = query.order(order_by, desc=not ascending)
                query = query.limit(limit).offset(offset)
                result = query.execute()
                return {
                    "success": True,
                    "rows": result.data,
                    "count": len(result.data or []),
                }

            if operation == "update":
                if not data:
                    raise ValueError("data is required for update")
                result = query.update(data).execute()
                return {"success": True, "updated": result.data}

            if operation == "delete":
                result = query.delete().execute()
                return {"success": True, "deleted": result.data}

            if operation == "upsert":
                if not data:
                    raise ValueError("data is required for upsert")
                result = query.upsert(data).execute()
                return {"success": True, "data": result.data}

            if operation == "count":
                result = query.select("count", count="exact").execute()
                return {"success": True, "count": result.count}

            # ── RPC ─────────────────────────────────────────────────────────
            if operation == "rpc":
                if not rpc_name:
                    raise ValueError("rpc_name is required")
                result = client.rpc(rpc_name, params or {}).execute()
                return {"success": True, "data": result.data}

            # ── STORAGE ─────────────────────────────────────────────────────
            if operation in (
                "upload_file",
                "download_file",
                "list_files",
                "delete_file",
                "create_bucket",
            ):
                if not bucket:
                    raise ValueError("bucket is required for storage operations")
                storage = client.storage.from_(bucket)

            if operation == "upload_file":
                if not file_path or not storage_path:
                    raise ValueError("file_path and storage_path required")
                with open(file_path, "rb") as f:
                    storage.upload(storage_path, f)
                return {"success": True, "path": storage_path}

            if operation == "download_file":
                if not storage_path:
                    raise ValueError("storage_path required")
                data = storage.download(storage_path)
                os.makedirs("downloads", exist_ok=True)
                local_path = os.path.join("downloads", os.path.basename(storage_path))
                with open(local_path, "wb") as f:
                    f.write(data)
                return {"success": True, "local_path": local_path}

            if operation == "list_files":
                files = storage.list(path="", limit=limit, offset=offset)
                return {"success": True, "files": [f.__dict__ for f in files]}

            if operation == "delete_file":
                if not storage_path:
                    raise ValueError("storage_path required")
                storage.remove([storage_path])
                return {"success": True, "deleted": storage_path}

            if operation == "create_bucket":
                public = params.get("public", False) if params else False
                client.storage.create_bucket(bucket, public=public)
                return {"success": True, "bucket": bucket}

            # ── AUTH ADMIN (needs service_role key!) ───────────────────────
            if operation == "list_users":
                users = client.auth.admin.list_users()
                return {"success": True, "users": [u.__dict__ for u in users.users]}

            if operation == "get_user":
                if not user_id:
                    raise ValueError("user_id required")
                user = client.auth.admin.get_user_by_id(user_id)
                return {
                    "success": True,
                    "user": user.user.__dict__ if user.user else None,
                }

            return {"success": False, "error": f"Unknown operation: {operation}"}

        except Exception as e:
            return {"success": False, "error": str(e), "type": type(e).__name__}
