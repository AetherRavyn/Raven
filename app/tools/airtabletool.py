"""Airtable Tool — List, get, create, update, and delete records in Airtable tables.

Agents use this to read and write data in Airtable bases.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)

AIRTABLE_API_URL = "https://api.airtable.com/v0"


class AirtableTool(BaseTool):
    """Read and write records in Airtable tables.

    Requires the AIRTABLE_API_KEY environment variable to be set.
    """

    group = "productivity"

    def get_name(self) -> str:
        return "airtable"

    def get_description(self) -> str:
        return (
            "Airtable records management tool. "
            "Actions: 'list_records' (list records from a table), "
            "'get_record' (get a single record by ID), "
            "'create_record' (create a new record), "
            "'update_record' (update an existing record), "
            "'delete_record' (delete a record). "
            "Requires AIRTABLE_API_KEY environment variable."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Operation: list_records, get_record, create_record, update_record, delete_record",
                    required=True,
                    enum=[
                        "list_records",
                        "get_record",
                        "create_record",
                        "update_record",
                        "delete_record",
                    ],
                ),
                ToolParameter(
                    name="base_id",
                    type="string",
                    description="Airtable Base ID (required for all actions)",
                    required=False,
                ),
                ToolParameter(
                    name="table_id",
                    type="string",
                    description="Table ID or table name (required for all actions)",
                    required=False,
                ),
                ToolParameter(
                    name="record_id",
                    type="string",
                    description="Record ID (required for get_record, update_record, delete_record)",
                    required=False,
                ),
                ToolParameter(
                    name="fields",
                    type="object",
                    description="Record fields dict (required for create_record, optional for update_record)",
                    required=False,
                ),
                ToolParameter(
                    name="max_records",
                    type="integer",
                    description="Maximum records to return (list_records, default 100)",
                    required=False,
                ),
            ],
        )

    def _get_api_key(self) -> str | None:
        return os.environ.get("AIRTABLE_API_KEY")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_api_key() or ''}",
            "Content-Type": "application/json",
        }

    def _check_config(self) -> dict[str, Any] | None:
        if not self._get_api_key():
            return {
                "success": False,
                "error": "AIRTABLE_API_KEY is not set. Please configure your Airtable API key.",
            }
        return None

    def _check_base_table(self, kwargs: dict[str, Any]) -> dict[str, Any] | None:
        if not kwargs.get("base_id"):
            return {"success": False, "error": "'base_id' is required"}
        if not kwargs.get("table_id"):
            return {"success": False, "error": "'table_id' is required"}
        return None

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{AIRTABLE_API_URL}{path}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(
                method,
                url,
                headers=self._headers(),
                params=params,
                json=json_body,
            )
            if resp.status_code >= 400:
                try:
                    err = resp.json()
                    msg = err.get("error", {}).get("message", str(err))
                except Exception:
                    msg = resp.text
                return {"success": False, "error": msg}
            try:
                return {"success": True, "data": resp.json()}
            except Exception as e:
                return {"success": False, "error": str(e)}

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        config_err = self._check_config()
        if config_err:
            return config_err

        action = kwargs.get("action")

        try:
            if action == "list_records":
                return await self._list_records(kwargs)
            elif action == "get_record":
                return await self._get_record(kwargs)
            elif action == "create_record":
                return await self._create_record(kwargs)
            elif action == "update_record":
                return await self._update_record(kwargs)
            elif action == "delete_record":
                return await self._delete_record(kwargs)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as e:
            logger.exception("Airtable tool failed")
            return {"success": False, "error": str(e)}

    async def _list_records(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        err = self._check_base_table(kwargs)
        if err:
            return err

        base_id = kwargs["base_id"]
        table_id = kwargs["table_id"]
        max_records = kwargs.get("max_records", 100)

        params: dict[str, Any] = {"maxRecords": max_records}
        result = await self._request("GET", f"/{base_id}/{table_id}", params=params)
        if not result["success"]:
            return result

        records = result["data"].get("records", [])
        return {
            "success": True,
            "action": "list_records",
            "records": records,
            "total": len(records),
        }

    async def _get_record(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        err = self._check_base_table(kwargs)
        if err:
            return err

        record_id = kwargs.get("record_id")
        if not record_id:
            return {"success": False, "error": "'record_id' is required for get_record"}

        base_id = kwargs["base_id"]
        table_id = kwargs["table_id"]
        result = await self._request("GET", f"/{base_id}/{table_id}/{record_id}")
        if not result["success"]:
            return result

        return {
            "success": True,
            "action": "get_record",
            "record": result["data"],
        }

    async def _create_record(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        err = self._check_base_table(kwargs)
        if err:
            return err

        fields = kwargs.get("fields")
        if not fields:
            return {"success": False, "error": "'fields' is required for create_record"}

        base_id = kwargs["base_id"]
        table_id = kwargs["table_id"]
        result = await self._request(
            "POST",
            f"/{base_id}/{table_id}",
            json_body={"fields": fields},
        )
        if not result["success"]:
            return result

        return {
            "success": True,
            "action": "create_record",
            "record": result["data"],
        }

    async def _update_record(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        err = self._check_base_table(kwargs)
        if err:
            return err

        record_id = kwargs.get("record_id")
        if not record_id:
            return {"success": False, "error": "'record_id' is required for update_record"}

        fields = kwargs.get("fields")
        if not fields:
            return {"success": False, "error": "'fields' is required for update_record"}

        base_id = kwargs["base_id"]
        table_id = kwargs["table_id"]
        result = await self._request(
            "PATCH",
            f"/{base_id}/{table_id}/{record_id}",
            json_body={"fields": fields},
        )
        if not result["success"]:
            return result

        return {
            "success": True,
            "action": "update_record",
            "record": result["data"],
        }

    async def _delete_record(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        err = self._check_base_table(kwargs)
        if err:
            return err

        record_id = kwargs.get("record_id")
        if not record_id:
            return {"success": False, "error": "'record_id' is required for delete_record"}

        base_id = kwargs["base_id"]
        table_id = kwargs["table_id"]
        result = await self._request(
            "DELETE",
            f"/{base_id}/{table_id}/{record_id}",
        )
        if not result["success"]:
            return result

        return {
            "success": True,
            "action": "delete_record",
            "deleted": True,
            "record_id": record_id,
        }
