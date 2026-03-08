from __future__ import annotations

"""
NotionTool — a full-featured Notion API integration for AI agents.

Authentication:
    Set the NOTION_API_KEY environment variable (or pass api_key to __init__)
    with an Internal Integration Token from https://www.notion.so/my-integrations.
    The integration must be shared with any workspace pages/databases it needs to access.

Docs: https://developers.notion.com/reference
@swadhinbiswas
"""

import os
import time
from typing import Any, Dict, List, Optional

import requests

from app.tools.base import BaseTool, ToolParameter, ToolSchema

# ── Constants ────────────────────────────────────────────────────────────── #

_BASE_URL = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"
_DEFAULT_PAGE_SIZE = 20


class NotionTool(BaseTool):
    """Notion API tool covering pages, databases, blocks, search, users, and comments."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("NOTION_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "Notion API key not provided. "
                "Set NOTION_API_KEY environment variable or pass api_key to NotionTool()."
            )

    # ------------------------------------------------------------------ #
    #  HTTP helpers                                                          #
    # ------------------------------------------------------------------ #

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Notion-Version": _NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        retries: int = 3,
    ) -> Dict[str, Any]:
        url = f"{_BASE_URL}/{path.lstrip('/')}"
        for attempt in range(retries):
            resp = requests.request(
                method,
                url,
                headers=self._headers(),
                json=payload,
                params=params,
            )
            if resp.status_code == 429:  # rate-limited
                wait = int(resp.headers.get("Retry-After", 2**attempt))
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json() if resp.text else {}
        raise RuntimeError(f"Notion API request failed after {retries} retries: {path}")

    def _get(self, path: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        return self._request("GET", path, params=params)

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", path, payload=payload)

    def _patch(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("PATCH", path, payload=payload)

    def _delete(self, path: str) -> Dict[str, Any]:
        return self._request("DELETE", path)

    # ------------------------------------------------------------------ #
    #  Tool metadata                                                         #
    # ------------------------------------------------------------------ #

    def get_name(self) -> str:
        return "notion"

    def get_description(self) -> str:
        return (
            "Notion workspace tool for AI agents. Supports: searching the workspace; "
            "creating, reading, updating, and archiving pages; querying, creating, and "
            "updating databases; reading, appending, updating, and deleting blocks; "
            "managing page properties; listing workspace users; and adding/listing comments."
        )

    def get_schema(self) -> ToolSchema:  # noqa: C901
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                # ── Core ──────────────────────────────────────────────── #
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Notion operation to perform.",
                    required=True,
                    enum=[
                        # Search
                        "search",
                        # Pages
                        "get_page",
                        "create_page",
                        "update_page",
                        "archive_page",
                        "restore_page",
                        "get_page_content",
                        # Databases
                        "get_database",
                        "create_database",
                        "update_database",
                        "query_database",
                        # Blocks
                        "get_block",
                        "get_block_children",
                        "append_blocks",
                        "update_block",
                        "delete_block",
                        # Users
                        "list_users",
                        "get_user",
                        "get_bot_user",
                        # Comments
                        "add_comment",
                        "list_comments",
                    ],
                ),
                # ── Identifiers ────────────────────────────────────────── #
                ToolParameter(
                    name="page_id",
                    type="string",
                    description="ID of a Notion page (UUID with or without dashes).",
                    required=False,
                ),
                ToolParameter(
                    name="database_id",
                    type="string",
                    description="ID of a Notion database.",
                    required=False,
                ),
                ToolParameter(
                    name="block_id",
                    type="string",
                    description="ID of a Notion block.",
                    required=False,
                ),
                ToolParameter(
                    name="user_id",
                    type="string",
                    description="ID of a Notion user.",
                    required=False,
                ),
                # ── Search ─────────────────────────────────────────────── #
                ToolParameter(
                    name="query",
                    type="string",
                    description="Full-text search query.",
                    required=False,
                ),
                ToolParameter(
                    name="filter_type",
                    type="string",
                    description="Restrict search to 'page' or 'database'.",
                    required=False,
                    enum=["page", "database"],
                ),
                # ── Page / database parent ─────────────────────────────── #
                ToolParameter(
                    name="parent_page_id",
                    type="string",
                    description="Parent page ID when creating a page or database inside a page.",
                    required=False,
                ),
                ToolParameter(
                    name="parent_database_id",
                    type="string",
                    description="Parent database ID when creating a page as a database row.",
                    required=False,
                ),
                # ── Page / database title ──────────────────────────────── #
                ToolParameter(
                    name="title",
                    type="string",
                    description="Title for a new page or database.",
                    required=False,
                ),
                # ── Properties ────────────────────────────────────────── #
                ToolParameter(
                    name="properties",
                    type="object",
                    description=(
                        "Page or database properties as a Notion property-value map. "
                        "For pages: {'Status': {'select': {'name': 'In Progress'}}, "
                        "'Due': {'date': {'start': '2026-03-01'}}}. "
                        "For database schema: {'Name': {'title': {}}, 'Status': {'select': {'options': []}}}."
                    ),
                    required=False,
                ),
                # ── Cover & icon ───────────────────────────────────────── #
                ToolParameter(
                    name="cover_url",
                    type="string",
                    description="External image URL for the page cover.",
                    required=False,
                ),
                ToolParameter(
                    name="icon_emoji",
                    type="string",
                    description="Emoji character to use as the page/database icon (e.g. '📄').",
                    required=False,
                ),
                # ── Blocks ────────────────────────────────────────────── #
                ToolParameter(
                    name="blocks",
                    type="array",
                    description=(
                        "List of Notion block objects to append. "
                        "Each block must have a 'type' key and matching content. "
                        "Common types: paragraph, heading_1, heading_2, heading_3, "
                        "bulleted_list_item, numbered_list_item, to_do, toggle, "
                        "code, quote, callout, divider, image, bookmark, table_of_contents. "
                        "Example: [{'type': 'paragraph', 'paragraph': {'rich_text': [{'type': 'text', 'text': {'content': 'Hello'}}]}}]"
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="block_type",
                    type="string",
                    description="Block type to use when updating a block (e.g. 'paragraph', 'heading_1').",
                    required=False,
                ),
                ToolParameter(
                    name="block_content",
                    type="object",
                    description=(
                        "Content payload for the specific block type when updating a block. "
                        "E.g. for a paragraph: {'rich_text': [{'type': 'text', 'text': {'content': 'New text'}}]}"
                    ),
                    required=False,
                ),
                # ── Database query ─────────────────────────────────────── #
                ToolParameter(
                    name="filter",
                    type="object",
                    description=(
                        "Notion filter object for query_database. "
                        "Example (single): {'property': 'Status', 'select': {'equals': 'Done'}}. "
                        "Example (compound): {'and': [{'property': 'Priority', 'select': {'equals': 'High'}}, "
                        "{'property': 'Done', 'checkbox': {'equals': False}}]}"
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="sorts",
                    type="array",
                    description=(
                        "Sort order for query_database. "
                        "Example: [{'property': 'Due', 'direction': 'ascending'}]"
                    ),
                    required=False,
                ),
                # ── Pagination ─────────────────────────────────────────── #
                ToolParameter(
                    name="page_size",
                    type="integer",
                    description=f"Maximum number of results to return (default: {_DEFAULT_PAGE_SIZE}, max: 100).",
                    required=False,
                ),
                ToolParameter(
                    name="start_cursor",
                    type="string",
                    description="Pagination cursor from a previous response's 'next_cursor' field.",
                    required=False,
                ),
                # ── Comments ───────────────────────────────────────────── #
                ToolParameter(
                    name="comment_text",
                    type="string",
                    description="Plain-text content for a new comment.",
                    required=False,
                ),
                ToolParameter(
                    name="discussion_id",
                    type="string",
                    description="Discussion thread ID for listing or replying to comments.",
                    required=False,
                ),
                # ── Database description ───────────────────────────────── #
                ToolParameter(
                    name="description",
                    type="string",
                    description="Plain-text description for a database.",
                    required=False,
                ),
            ],
        )

    # ------------------------------------------------------------------ #
    #  Entry point                                                           #
    # ------------------------------------------------------------------ #

    async def execute(  # noqa: C901
        self,
        operation: str,
        page_id: Optional[str] = None,
        database_id: Optional[str] = None,
        block_id: Optional[str] = None,
        user_id: Optional[str] = None,
        query: Optional[str] = None,
        filter_type: Optional[str] = None,
        parent_page_id: Optional[str] = None,
        parent_database_id: Optional[str] = None,
        title: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None,
        cover_url: Optional[str] = None,
        icon_emoji: Optional[str] = None,
        blocks: Optional[List[Dict[str, Any]]] = None,
        block_type: Optional[str] = None,
        block_content: Optional[Dict[str, Any]] = None,
        filter: Optional[Dict[str, Any]] = None,
        sorts: Optional[List[Dict[str, Any]]] = None,
        page_size: int = _DEFAULT_PAGE_SIZE,
        start_cursor: Optional[str] = None,
        comment_text: Optional[str] = None,
        discussion_id: Optional[str] = None,
        description: Optional[str] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        try:
            page_size = min(max(1, page_size), 100)

            # ── Search ───────────────────────────────────────────────── #
            if operation == "search":
                return self._search(query, filter_type, page_size, start_cursor)

            # ── Pages ────────────────────────────────────────────────── #
            elif operation == "get_page":
                if not page_id:
                    return _err("'page_id' is required.")
                result = self._get(f"pages/{_fmt_id(page_id)}")
                return _ok(operation, {"page": result})

            elif operation == "create_page":
                if not parent_page_id and not parent_database_id:
                    return _err("'parent_page_id' or 'parent_database_id' is required.")
                result = self._create_page(
                    parent_page_id,
                    parent_database_id,
                    title,
                    properties,
                    cover_url,
                    icon_emoji,
                    blocks,
                )
                return _ok(
                    operation,
                    {
                        "page_id": result.get("id"),
                        "url": result.get("url"),
                        "page": result,
                    },
                )

            elif operation == "update_page":
                if not page_id:
                    return _err("'page_id' is required.")
                result = self._update_page(
                    page_id, title, properties, cover_url, icon_emoji
                )
                return _ok(operation, {"page_id": result.get("id"), "page": result})

            elif operation == "archive_page":
                if not page_id:
                    return _err("'page_id' is required.")
                result = self._patch(f"pages/{_fmt_id(page_id)}", {"archived": True})
                return _ok(operation, {"page_id": page_id, "archived": True})

            elif operation == "restore_page":
                if not page_id:
                    return _err("'page_id' is required.")
                result = self._patch(f"pages/{_fmt_id(page_id)}", {"archived": False})
                return _ok(operation, {"page_id": page_id, "archived": False})

            elif operation == "get_page_content":
                if not page_id:
                    return _err("'page_id' is required.")
                return self._get_all_block_children(
                    page_id, page_size, start_cursor, operation
                )

            # ── Databases ────────────────────────────────────────────── #
            elif operation == "get_database":
                if not database_id:
                    return _err("'database_id' is required.")
                result = self._get(f"databases/{_fmt_id(database_id)}")
                return _ok(operation, {"database": result})

            elif operation == "create_database":
                if not parent_page_id:
                    return _err("'parent_page_id' is required for create_database.")
                if not title:
                    return _err("'title' is required.")
                result = self._create_database(
                    parent_page_id,
                    title,
                    properties or {},
                    description,
                    icon_emoji,
                    cover_url,
                )
                return _ok(
                    operation,
                    {
                        "database_id": result.get("id"),
                        "url": result.get("url"),
                        "database": result,
                    },
                )

            elif operation == "update_database":
                if not database_id:
                    return _err("'database_id' is required.")
                result = self._update_database(
                    database_id, title, description, properties, icon_emoji, cover_url
                )
                return _ok(
                    operation, {"database_id": result.get("id"), "database": result}
                )

            elif operation == "query_database":
                if not database_id:
                    return _err("'database_id' is required.")
                return self._query_database(
                    database_id, filter, sorts, page_size, start_cursor
                )

            # ── Blocks ───────────────────────────────────────────────── #
            elif operation == "get_block":
                if not block_id:
                    return _err("'block_id' is required.")
                result = self._get(f"blocks/{_fmt_id(block_id)}")
                return _ok(operation, {"block": result})

            elif operation == "get_block_children":
                target = block_id or page_id
                if not target:
                    return _err("'block_id' or 'page_id' is required.")
                return self._get_all_block_children(
                    target, page_size, start_cursor, operation
                )

            elif operation == "append_blocks":
                target = block_id or page_id
                if not target:
                    return _err("'block_id' or 'page_id' is required.")
                if not blocks:
                    return _err("'blocks' is required.")
                result = self._post(
                    f"blocks/{_fmt_id(target)}/children",
                    {"children": blocks},
                )
                return _ok(
                    operation,
                    {
                        "parent_id": target,
                        "appended_count": len(result.get("results", [])),
                        "results": result.get("results", []),
                    },
                )

            elif operation == "update_block":
                if not block_id:
                    return _err("'block_id' is required.")
                if not block_type or block_content is None:
                    return _err("'block_type' and 'block_content' are required.")
                payload: Dict[str, Any] = {block_type: block_content}
                result = self._patch(f"blocks/{_fmt_id(block_id)}", payload)
                return _ok(operation, {"block": result})

            elif operation == "delete_block":
                if not block_id:
                    return _err("'block_id' is required.")
                self._delete(f"blocks/{_fmt_id(block_id)}")
                return _ok(operation, {"block_id": block_id, "deleted": True})

            # ── Users ────────────────────────────────────────────────── #
            elif operation == "list_users":
                result = self._get("users", params={"page_size": page_size})
                return _ok(
                    operation,
                    {
                        "users": result.get("results", []),
                        "count": len(result.get("results", [])),
                        "has_more": result.get("has_more", False),
                        "next_cursor": result.get("next_cursor"),
                    },
                )

            elif operation == "get_user":
                if not user_id:
                    return _err("'user_id' is required.")
                result = self._get(f"users/{user_id}")
                return _ok(operation, {"user": result})

            elif operation == "get_bot_user":
                result = self._get("users/me")
                return _ok(operation, {"bot_user": result})

            # ── Comments ─────────────────────────────────────────────── #
            elif operation == "add_comment":
                if not page_id:
                    return _err("'page_id' is required.")
                if not comment_text:
                    return _err("'comment_text' is required.")
                result = self._add_comment(page_id, comment_text, discussion_id)
                return _ok(operation, {"comment": result})

            elif operation == "list_comments":
                if not page_id and not discussion_id:
                    return _err("'page_id' or 'discussion_id' is required.")
                params: Dict[str, Any] = {"page_size": page_size}
                if page_id:
                    params["block_id"] = _fmt_id(page_id)
                if discussion_id:
                    params["discussion_id"] = discussion_id
                if start_cursor:
                    params["start_cursor"] = start_cursor
                result = self._get("comments", params=params)
                return _ok(
                    operation,
                    {
                        "comments": result.get("results", []),
                        "count": len(result.get("results", [])),
                        "has_more": result.get("has_more", False),
                        "next_cursor": result.get("next_cursor"),
                    },
                )

            return _err(f"Unknown operation: {operation}")

        except requests.HTTPError as e:
            body: Dict[str, Any] = {}
            try:
                body = e.response.json()
            except Exception:
                pass
            return {
                "success": False,
                "error": body.get("message", str(e)),
                "notion_code": body.get("code"),
                "status_code": e.response.status_code
                if e.response is not None
                else None,
            }
        except Exception as e:
            return {"success": False, "error": f"Notion tool error: {str(e)}"}

    # ------------------------------------------------------------------ #
    #  Private helpers                                                       #
    # ------------------------------------------------------------------ #

    # ── Search ───────────────────────────────────────────────────────── #

    def _search(
        self,
        query: Optional[str],
        filter_type: Optional[str],
        page_size: int,
        start_cursor: Optional[str],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"page_size": page_size}
        if query:
            payload["query"] = query
        if filter_type:
            payload["filter"] = {"value": filter_type, "property": "object"}
        if start_cursor:
            payload["start_cursor"] = start_cursor
        result = self._post("search", payload)
        return _ok(
            "search",
            {
                "results": result.get("results", []),
                "count": len(result.get("results", [])),
                "has_more": result.get("has_more", False),
                "next_cursor": result.get("next_cursor"),
            },
        )

    # ── Pages ─────────────────────────────────────────────────────────── #

    def _create_page(
        self,
        parent_page_id: Optional[str],
        parent_database_id: Optional[str],
        title: Optional[str],
        properties: Optional[Dict[str, Any]],
        cover_url: Optional[str],
        icon_emoji: Optional[str],
        blocks: Optional[List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        # Build parent
        if parent_database_id:
            parent = {"type": "database_id", "database_id": _fmt_id(parent_database_id)}
        else:
            parent = {"type": "page_id", "page_id": _fmt_id(parent_page_id)}  # type: ignore[arg-type]

        # Build properties — title property is required
        page_properties: Dict[str, Any] = properties or {}
        if title and "title" not in page_properties:
            page_properties["title"] = _rich_text_prop(title)

        payload: Dict[str, Any] = {"parent": parent, "properties": page_properties}

        if icon_emoji:
            payload["icon"] = {"type": "emoji", "emoji": icon_emoji}
        if cover_url:
            payload["cover"] = {"type": "external", "external": {"url": cover_url}}
        if blocks:
            payload["children"] = blocks

        return self._post("pages", payload)

    def _update_page(
        self,
        page_id: str,
        title: Optional[str],
        properties: Optional[Dict[str, Any]],
        cover_url: Optional[str],
        icon_emoji: Optional[str],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        page_properties: Dict[str, Any] = properties or {}
        if title:
            page_properties["title"] = _rich_text_prop(title)
        if page_properties:
            payload["properties"] = page_properties
        if icon_emoji:
            payload["icon"] = {"type": "emoji", "emoji": icon_emoji}
        if cover_url:
            payload["cover"] = {"type": "external", "external": {"url": cover_url}}
        return self._patch(f"pages/{_fmt_id(page_id)}", payload)

    # ── Databases ─────────────────────────────────────────────────────── #

    def _create_database(
        self,
        parent_page_id: str,
        title: str,
        schema: Dict[str, Any],
        description: Optional[str],
        icon_emoji: Optional[str],
        cover_url: Optional[str],
    ) -> Dict[str, Any]:
        # Ensure a Name/title column always exists
        if not any(isinstance(v, dict) and "title" in v for v in schema.values()):
            schema = {"Name": {"title": {}}, **schema}

        payload: Dict[str, Any] = {
            "parent": {"type": "page_id", "page_id": _fmt_id(parent_page_id)},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": schema,
        }
        if description:
            payload["description"] = [
                {"type": "text", "text": {"content": description}}
            ]
        if icon_emoji:
            payload["icon"] = {"type": "emoji", "emoji": icon_emoji}
        if cover_url:
            payload["cover"] = {"type": "external", "external": {"url": cover_url}}
        return self._post("databases", payload)

    def _update_database(
        self,
        database_id: str,
        title: Optional[str],
        description: Optional[str],
        properties: Optional[Dict[str, Any]],
        icon_emoji: Optional[str],
        cover_url: Optional[str],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if title:
            payload["title"] = [{"type": "text", "text": {"content": title}}]
        if description:
            payload["description"] = [
                {"type": "text", "text": {"content": description}}
            ]
        if properties:
            payload["properties"] = properties
        if icon_emoji:
            payload["icon"] = {"type": "emoji", "emoji": icon_emoji}
        if cover_url:
            payload["cover"] = {"type": "external", "external": {"url": cover_url}}
        return self._patch(f"databases/{_fmt_id(database_id)}", payload)

    def _query_database(
        self,
        database_id: str,
        filter: Optional[Dict[str, Any]],
        sorts: Optional[List[Dict[str, Any]]],
        page_size: int,
        start_cursor: Optional[str],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"page_size": page_size}
        if filter:
            payload["filter"] = filter
        if sorts:
            payload["sorts"] = sorts
        if start_cursor:
            payload["start_cursor"] = start_cursor
        result = self._post(f"databases/{_fmt_id(database_id)}/query", payload)
        return _ok(
            "query_database",
            {
                "results": result.get("results", []),
                "count": len(result.get("results", [])),
                "has_more": result.get("has_more", False),
                "next_cursor": result.get("next_cursor"),
            },
        )

    # ── Blocks ────────────────────────────────────────────────────────── #

    def _get_all_block_children(
        self,
        parent_id: str,
        page_size: int,
        start_cursor: Optional[str],
        operation: str,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"page_size": page_size}
        if start_cursor:
            params["start_cursor"] = start_cursor
        result = self._get(f"blocks/{_fmt_id(parent_id)}/children", params=params)
        return _ok(
            operation,
            {
                "parent_id": parent_id,
                "blocks": result.get("results", []),
                "count": len(result.get("results", [])),
                "has_more": result.get("has_more", False),
                "next_cursor": result.get("next_cursor"),
            },
        )

    # ── Comments ──────────────────────────────────────────────────────── #

    def _add_comment(
        self,
        page_id: str,
        text: str,
        discussion_id: Optional[str],
    ) -> Dict[str, Any]:
        rich_text = [{"type": "text", "text": {"content": text}}]
        if discussion_id:
            payload: Dict[str, Any] = {
                "discussion_id": discussion_id,
                "rich_text": rich_text,
            }
        else:
            payload = {
                "parent": {"page_id": _fmt_id(page_id)},
                "rich_text": rich_text,
            }
        return self._post("comments", payload)


# ── Module-level helpers ──────────────────────────────────────────────────── #


def _fmt_id(notion_id: str) -> str:
    """Normalise a Notion ID to the dashed UUID format the API expects."""
    clean = notion_id.replace("-", "").strip()
    if len(clean) == 32:
        return f"{clean[:8]}-{clean[8:12]}-{clean[12:16]}-{clean[16:20]}-{clean[20:]}"
    return notion_id  # already formatted or short ID — pass through


def _rich_text_prop(text: str) -> Dict[str, Any]:
    """Wrap plain text in a Notion title property value."""
    return {"title": [{"type": "text", "text": {"content": text}}]}


def _ok(operation: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {"success": True, "operation": operation, **data}


def _err(message: str) -> Dict[str, Any]:
    return {"success": False, "error": message}


# ── Block builder helpers (import from your agent to construct blocks) ─────── #


class NotionBlocks:
    """
    Convenience factory for constructing common Notion block objects.
    Pass the output directly to the 'blocks' parameter of append_blocks or create_page.

    Usage:
        blocks = [
            NotionBlocks.heading_1("My Title"),
            NotionBlocks.paragraph("Some body text."),
            NotionBlocks.to_do("Finish the report", checked=False),
            NotionBlocks.divider(),
            NotionBlocks.code("print('hello')", language="python"),
        ]
    """

    @staticmethod
    def _rich(text: str, bold: bool = False, color: str = "default") -> List[Dict]:
        rt: Dict[str, Any] = {"type": "text", "text": {"content": text}}
        if bold or color != "default":
            rt["annotations"] = {"bold": bold, "color": color}
        return [rt]

    @staticmethod
    def paragraph(text: str, color: str = "default") -> Dict[str, Any]:
        return {
            "type": "paragraph",
            "paragraph": {"rich_text": NotionBlocks._rich(text, color=color)},
        }

    @staticmethod
    def heading_1(text: str) -> Dict[str, Any]:
        return {
            "type": "heading_1",
            "heading_1": {"rich_text": NotionBlocks._rich(text)},
        }

    @staticmethod
    def heading_2(text: str) -> Dict[str, Any]:
        return {
            "type": "heading_2",
            "heading_2": {"rich_text": NotionBlocks._rich(text)},
        }

    @staticmethod
    def heading_3(text: str) -> Dict[str, Any]:
        return {
            "type": "heading_3",
            "heading_3": {"rich_text": NotionBlocks._rich(text)},
        }

    @staticmethod
    def bulleted_list_item(text: str) -> Dict[str, Any]:
        return {
            "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": NotionBlocks._rich(text)},
        }

    @staticmethod
    def numbered_list_item(text: str) -> Dict[str, Any]:
        return {
            "type": "numbered_list_item",
            "numbered_list_item": {"rich_text": NotionBlocks._rich(text)},
        }

    @staticmethod
    def to_do(text: str, checked: bool = False) -> Dict[str, Any]:
        return {
            "type": "to_do",
            "to_do": {"rich_text": NotionBlocks._rich(text), "checked": checked},
        }

    @staticmethod
    def toggle(text: str, children: Optional[List[Dict]] = None) -> Dict[str, Any]:
        block: Dict[str, Any] = {
            "type": "toggle",
            "toggle": {"rich_text": NotionBlocks._rich(text)},
        }
        if children:
            block["toggle"]["children"] = children
        return block

    @staticmethod
    def quote(text: str) -> Dict[str, Any]:
        return {"type": "quote", "quote": {"rich_text": NotionBlocks._rich(text)}}

    @staticmethod
    def callout(text: str, emoji: str = "💡") -> Dict[str, Any]:
        return {
            "type": "callout",
            "callout": {
                "rich_text": NotionBlocks._rich(text),
                "icon": {"type": "emoji", "emoji": emoji},
            },
        }

    @staticmethod
    def code(text: str, language: str = "plain text") -> Dict[str, Any]:
        return {
            "type": "code",
            "code": {
                "rich_text": [{"type": "text", "text": {"content": text}}],
                "language": language,
            },
        }

    @staticmethod
    def divider() -> Dict[str, Any]:
        return {"type": "divider", "divider": {}}

    @staticmethod
    def table_of_contents() -> Dict[str, Any]:
        return {"type": "table_of_contents", "table_of_contents": {}}

    @staticmethod
    def image(url: str) -> Dict[str, Any]:
        return {
            "type": "image",
            "image": {"type": "external", "external": {"url": url}},
        }

    @staticmethod
    def bookmark(url: str, caption: str = "") -> Dict[str, Any]:
        return {
            "type": "bookmark",
            "bookmark": {
                "url": url,
                "caption": NotionBlocks._rich(caption) if caption else [],
            },
        }

    @staticmethod
    def embed(url: str) -> Dict[str, Any]:
        return {"type": "embed", "embed": {"url": url}}
