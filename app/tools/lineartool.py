"""Linear Tool — Create, list, update, and search Linear issues via GraphQL API.

Agents use this to manage tasks in Linear directly from the assistant.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)

LINEAR_API_URL = "https://api.linear.app/graphql"


class LinearTool(BaseTool):
    """Create, read, update, and search issues in Linear.

    Requires the LINEAR_API_KEY environment variable to be set.
    """

    group = "productivity"

    def get_name(self) -> str:
        return "linear"

    def get_description(self) -> str:
        return (
            "Linear issue management tool. "
            "Actions: 'create_issue' (create a new issue), "
            "'list_issues' (list issues with optional filters), "
            "'update_issue' (update status/priority/assignee), "
            "'search' (search issues by text). "
            "Requires LINEAR_API_KEY environment variable."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Operation: create_issue, list_issues, update_issue, search",
                    required=True,
                    enum=["create_issue", "list_issues", "update_issue", "search"],
                ),
                ToolParameter(
                    name="title",
                    type="string",
                    description="Issue title (required for create_issue)",
                    required=False,
                ),
                ToolParameter(
                    name="description",
                    type="string",
                    description="Issue description body (markdown supported)",
                    required=False,
                ),
                ToolParameter(
                    name="team_id",
                    type="string",
                    description="Team ID (required for create_issue, optional filter for list_issues)",
                    required=False,
                ),
                ToolParameter(
                    name="priority",
                    type="integer",
                    description="Issue priority: 0=no priority, 1=urgent, 2=high, 3=medium, 4=low",
                    required=False,
                ),
                ToolParameter(
                    name="assignee",
                    type="string",
                    description="Assignee user ID",
                    required=False,
                ),
                ToolParameter(
                    name="status",
                    type="string",
                    description="Status filter (list_issues) or new status ID (update_issue)",
                    required=False,
                ),
                ToolParameter(
                    name="issue_id",
                    type="string",
                    description="Issue ID (required for update_issue)",
                    required=False,
                ),
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search text (required for search action)",
                    required=False,
                ),
            ],
        )

    def _get_api_key(self) -> str | None:
        return os.environ.get("LINEAR_API_KEY")

    def _headers(self) -> dict[str, str]:
        api_key = self._get_api_key()
        return {
            "Content-Type": "application/json",
            "Authorization": api_key or "",
        }

    def _check_config(self) -> dict[str, Any] | None:
        if not self._get_api_key():
            return {
                "success": False,
                "error": "LINEAR_API_KEY is not set. Please configure your Linear API key.",
            }
        return None

    async def _graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                LINEAR_API_URL,
                headers=self._headers(),
                json={"query": query, "variables": variables or {}},
            )
            data = resp.json()
            if "errors" in data:
                return {
                    "success": False,
                    "error": data["errors"][0].get("message", str(data["errors"])),
                }
            return {"success": True, "data": data.get("data", {})}

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        config_err = self._check_config()
        if config_err:
            return config_err

        action = kwargs.get("action")

        try:
            if action == "create_issue":
                return await self._create_issue(kwargs)
            elif action == "list_issues":
                return await self._list_issues(kwargs)
            elif action == "update_issue":
                return await self._update_issue(kwargs)
            elif action == "search":
                return await self._search(kwargs)
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as e:
            logger.exception("Linear tool failed")
            return {"success": False, "error": str(e)}

    async def _create_issue(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        title = kwargs.get("title")
        if not title:
            return {"success": False, "error": "'title' is required for create_issue"}
        team_id = kwargs.get("team_id")
        if not team_id:
            return {"success": False, "error": "'team_id' is required for create_issue"}

        description = kwargs.get("description")
        priority = kwargs.get("priority")
        assignee = kwargs.get("assignee")

        mutation = """
            mutation IssueCreate($title: String!, $teamId: String!, $description: String, $priority: Int, $assigneeId: String) {
                issueCreate(
                    input: {
                        title: $title,
                        teamId: $teamId,
                        description: $description,
                        priority: $priority,
                        assigneeId: $assigneeId
                    }
                ) {
                    success
                    issue {
                        id
                        title
                        identifier
                        url
                        priority
                        state { name }
                        assignee { id name }
                    }
                }
            }
        """
        variables: dict[str, Any] = {
            "title": title,
            "teamId": team_id,
            "description": description,
            "priority": priority,
            "assigneeId": assignee,
        }
        result = await self._graphql(mutation, variables)
        if not result["success"]:
            return result
        issue = result["data"].get("issueCreate", {}).get("issue", {})
        return {"success": True, "action": "create_issue", "issue": issue}

    async def _list_issues(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        team_id = kwargs.get("team_id")
        status = kwargs.get("status")
        assignee = kwargs.get("assignee")

        filters: list[str] = []
        variables: dict[str, Any] = {}

        if team_id:
            filters.append("team: { id: { eq: $teamId } }")
            variables["teamId"] = team_id
        if status:
            filters.append("state: { name: { eq: $status } }")
            variables["status"] = status
        if assignee:
            filters.append("assignee: { id: { eq: $assignee } }")
            variables["assignee"] = assignee

        filter_str = ", ".join(filters) if filters else "{}"
        query = f"""
            query Issues($teamId: String, $status: String, $assignee: String) {{
                issues(filter: {{ {filter_str} }}, first: 50) {{
                    nodes {{
                        id
                        title
                        identifier
                        url
                        priority
                        state {{ name }}
                        assignee {{ id name }}
                        createdAt
                    }}
                }}
            }}
        """
        result = await self._graphql(query, variables)
        if not result["success"]:
            return result
        issues = result["data"].get("issues", {}).get("nodes", [])
        return {"success": True, "action": "list_issues", "issues": issues, "total": len(issues)}

    async def _update_issue(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        issue_id = kwargs.get("issue_id")
        if not issue_id:
            return {"success": False, "error": "'issue_id' is required for update_issue"}

        input_fields: dict[str, Any] = {}
        if kwargs.get("title"):
            input_fields["title"] = kwargs["title"]
        if kwargs.get("description"):
            input_fields["description"] = kwargs["description"]
        if kwargs.get("priority"):
            input_fields["priority"] = kwargs["priority"]
        if kwargs.get("assignee"):
            input_fields["assigneeId"] = kwargs["assignee"]
        if kwargs.get("status"):
            input_fields["stateId"] = kwargs["status"]

        if not input_fields:
            return {"success": False, "error": "No fields provided to update"}

        mutation = """
            mutation IssueUpdate($id: String!, $input: IssueUpdateInput!) {
                issueUpdate(id: $id, input: $input) {
                    success
                    issue {
                        id
                        title
                        identifier
                        url
                        priority
                        state { name }
                        assignee { id name }
                    }
                }
            }
        """
        variables = {"id": issue_id, "input": input_fields}
        result = await self._graphql(mutation, variables)
        if not result["success"]:
            return result
        issue = result["data"].get("issueUpdate", {}).get("issue", {})
        return {"success": True, "action": "update_issue", "issue": issue}

    async def _search(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        query_text = kwargs.get("query")
        if not query_text:
            return {"success": False, "error": "'query' is required for search"}

        query = """
            query Search($term: String!) {
                searchIssues(term: $term, first: 25) {
                    nodes {
                        id
                        title
                        identifier
                        url
                        priority
                        state { name }
                        assignee { id name }
                        team { id name }
                        createdAt
                    }
                }
            }
        """
        result = await self._graphql(query, {"term": query_text})
        if not result["success"]:
            return result
        issues = result["data"].get("searchIssues", {}).get("nodes", [])
        return {"success": True, "action": "search", "issues": issues, "total": len(issues)}
