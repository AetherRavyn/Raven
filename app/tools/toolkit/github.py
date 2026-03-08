from __future__ import annotations

"""
GitHubTool — a full-featured GitHub REST API integration for AI agents.

Authentication:
    Set the GITHUB_TOKEN environment variable (or pass token to __init__)
    with a Personal Access Token (classic or fine-grained) from
    https://github.com/settings/tokens.

    Required scopes (classic PAT):
        repo, read:org, read:user, read:discussion, gist,
        workflow (for Actions), delete_repo (optional)

GitHub API version: 2022-11-28
Docs: https://docs.github.com/en/rest
"""

import base64
import os
import time
from typing import Any, Dict, List, Optional

import requests

from app.tools.base import BaseTool, ToolParameter, ToolSchema

# ── Constants ────────────────────────────────────────────────────────────── #

_BASE_URL = "https://api.github.com"
_ACCEPT_JSON = "application/vnd.github+json"
_ACCEPT_RAW = "application/vnd.github.raw+json"
_GH_VERSION = "2022-11-28"
_DEFAULT_PER_PAGE = 30


class GitHubTool(BaseTool):
    """GitHub REST API tool covering repos, branches, commits, PRs, issues,
    releases, actions, gists, notifications, search, users, and orgs."""

    def __init__(self, token: Optional[str] = None):
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        if not self.token:
            raise ValueError(
                "GitHub token not provided. "
                "Set GITHUB_TOKEN environment variable or pass token= to GitHubTool()."
            )

    # ------------------------------------------------------------------ #
    #  HTTP helpers                                                      #
    # ------------------------------------------------------------------ #

    def _headers(self, accept: str = _ACCEPT_JSON) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": accept,
            "X-GitHub-Api-Version": _GH_VERSION,
        }

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        accept: str = _ACCEPT_JSON,
        retries: int = 3,
    ) -> Any:
        url = path if path.startswith("https://") else f"{_BASE_URL}/{path.lstrip('/')}"
        for attempt in range(retries):
            resp = requests.request(
                method,
                url,
                headers=self._headers(accept),
                json=payload,
                params={k: v for k, v in (params or {}).items() if v is not None},
            )
            if resp.status_code == 429 or (
                resp.status_code == 403 and "rate limit" in resp.text.lower()
            ):
                reset = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
                time.sleep(max(0, reset - time.time()) + 1)
                continue
            if resp.status_code == 204:  # No Content
                return {}
            resp.raise_for_status()
            return resp.json() if resp.text else {}
        raise RuntimeError(f"GitHub API request failed after {retries} retries: {path}")

    def _get(
        self, path: str, params: Optional[Dict] = None, accept: str = _ACCEPT_JSON
    ) -> Any:
        return self._request("GET", path, params=params, accept=accept)

    def _post(self, path: str, payload: Dict[str, Any]) -> Any:
        return self._request("POST", path, payload=payload)

    def _put(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        return self._request("PUT", path, payload=payload or {})

    def _patch(self, path: str, payload: Dict[str, Any]) -> Any:
        return self._request("PATCH", path, payload=payload)

    def _delete(self, path: str, payload: Optional[Dict[str, Any]] = None) -> Any:
        return self._request("DELETE", path, payload=payload)

    def _paginate(
        self, path: str, params: Dict[str, Any], max_results: int
    ) -> List[Any]:
        """Auto-paginate through a GitHub list endpoint up to max_results items."""
        results: List[Any] = []
        page = 1
        per_page = min(100, max_results)
        while len(results) < max_results:
            batch = self._get(
                path, params={**params, "per_page": per_page, "page": page}
            )
            if not isinstance(batch, list) or not batch:
                break
            results.extend(batch)
            if len(batch) < per_page:
                break
            page += 1
        return results[:max_results]

    # ------------------------------------------------------------------ #
    #  Tool metadata                                                         #
    # ------------------------------------------------------------------ #

    def get_name(self) -> str:
        return "github"

    def get_description(self) -> str:
        return (
            "GitHub tool for AI agents. Covers: repository CRUD, file read/write, "
            "branch management, commit history, pull requests (create/review/merge), "
            "issues (create/update/label/assign/comment), releases and tags, "
            "GitHub Actions (list/trigger/cancel workflows and runs), "
            "gists, notifications, code/repo/user search, "
            "organization and team management, and user profile operations."
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
                    description="GitHub operation to perform.",
                    required=True,
                    enum=[
                        # ── Repositories ──────────────────────────────── #
                        "list_repos",
                        "get_repo",
                        "create_repo",
                        "update_repo",
                        "delete_repo",
                        "fork_repo",
                        "list_repo_topics",
                        "set_repo_topics",
                        "get_repo_languages",
                        "get_repo_contributors",
                        "get_repo_traffic",
                        # ── Files & contents ──────────────────────────── #
                        "get_file",
                        "create_or_update_file",
                        "delete_file",
                        "list_directory",
                        "get_readme",
                        # ── Branches ──────────────────────────────────── #
                        "list_branches",
                        "get_branch",
                        "create_branch",
                        "delete_branch",
                        "merge_branches",
                        "protect_branch",
                        "unprotect_branch",
                        # ── Commits ───────────────────────────────────── #
                        "list_commits",
                        "get_commit",
                        "compare_commits",
                        # ── Pull Requests ─────────────────────────────── #
                        "list_pull_requests",
                        "get_pull_request",
                        "create_pull_request",
                        "update_pull_request",
                        "merge_pull_request",
                        "close_pull_request",
                        "list_pr_reviews",
                        "create_pr_review",
                        "list_pr_files",
                        "list_pr_comments",
                        "add_pr_comment",
                        # ── Issues ────────────────────────────────────── #
                        "list_issues",
                        "get_issue",
                        "create_issue",
                        "update_issue",
                        "close_issue",
                        "reopen_issue",
                        "lock_issue",
                        "unlock_issue",
                        "list_issue_comments",
                        "add_issue_comment",
                        "update_issue_comment",
                        "delete_issue_comment",
                        "add_labels",
                        "remove_label",
                        "set_assignees",
                        # ── Labels ────────────────────────────────────── #
                        "list_labels",
                        "create_label",
                        "update_label",
                        "delete_label",
                        # ── Milestones ────────────────────────────────── #
                        "list_milestones",
                        "create_milestone",
                        "update_milestone",
                        "delete_milestone",
                        # ── Releases & tags ───────────────────────────── #
                        "list_releases",
                        "get_release",
                        "get_latest_release",
                        "create_release",
                        "update_release",
                        "delete_release",
                        "list_tags",
                        # ── GitHub Actions ────────────────────────────── #
                        "list_workflows",
                        "get_workflow",
                        "trigger_workflow",
                        "list_workflow_runs",
                        "get_workflow_run",
                        "cancel_workflow_run",
                        "rerun_workflow",
                        "list_run_jobs",
                        "get_run_logs_url",
                        "list_repo_secrets",
                        # ── Gists ─────────────────────────────────────── #
                        "list_gists",
                        "get_gist",
                        "create_gist",
                        "update_gist",
                        "delete_gist",
                        "star_gist",
                        "unstar_gist",
                        # ── Notifications ─────────────────────────────── #
                        "list_notifications",
                        "mark_notifications_read",
                        # ── Search ────────────────────────────────────── #
                        "search_code",
                        "search_repos",
                        "search_issues",
                        "search_users",
                        "search_commits",
                        # ── Users ─────────────────────────────────────── #
                        "get_authenticated_user",
                        "get_user",
                        "list_user_repos",
                        "list_followers",
                        "list_following",
                        "follow_user",
                        "unfollow_user",
                        "list_user_gists",
                        # ── Organizations ─────────────────────────────── #
                        "get_org",
                        "list_org_repos",
                        "list_org_members",
                        "list_org_teams",
                        "get_team",
                        "list_team_members",
                        "list_team_repos",
                        # ── Starring & watching ───────────────────────── #
                        "star_repo",
                        "unstar_repo",
                        "list_stargazers",
                        "watch_repo",
                        "unwatch_repo",
                        "list_watchers",
                        # ── Collaborators ─────────────────────────────── #
                        "list_collaborators",
                        "add_collaborator",
                        "remove_collaborator",
                        # ── Webhooks ──────────────────────────────────── #
                        "list_webhooks",
                        "create_webhook",
                        "delete_webhook",
                    ],
                ),
                # ── Repo identifiers ───────────────────────────────────── #
                ToolParameter(
                    name="owner",
                    type="string",
                    description="GitHub username or organization name that owns the repository.",
                    required=False,
                ),
                ToolParameter(
                    name="repo",
                    type="string",
                    description="Repository name (without the owner prefix).",
                    required=False,
                ),
                # ── General identifiers ────────────────────────────────── #
                ToolParameter(
                    name="username",
                    type="string",
                    description="GitHub username for user-related operations.",
                    required=False,
                ),
                ToolParameter(
                    name="org",
                    type="string",
                    description="Organization login name.",
                    required=False,
                ),
                ToolParameter(
                    name="team_slug",
                    type="string",
                    description="Team slug within an organization.",
                    required=False,
                ),
                # ── Numeric IDs ────────────────────────────────────────── #
                ToolParameter(
                    name="issue_number",
                    type="integer",
                    description="Issue or pull request number.",
                    required=False,
                ),
                ToolParameter(
                    name="pr_number",
                    type="integer",
                    description="Pull request number.",
                    required=False,
                ),
                ToolParameter(
                    name="comment_id",
                    type="integer",
                    description="Comment ID for update/delete operations.",
                    required=False,
                ),
                ToolParameter(
                    name="milestone_number",
                    type="integer",
                    description="Milestone number.",
                    required=False,
                ),
                ToolParameter(
                    name="release_id",
                    type="integer",
                    description="Release ID.",
                    required=False,
                ),
                ToolParameter(
                    name="workflow_id",
                    type="string",
                    description="Workflow file name (e.g. 'ci.yml') or numeric workflow ID.",
                    required=False,
                ),
                ToolParameter(
                    name="run_id",
                    type="integer",
                    description="Workflow run ID.",
                    required=False,
                ),
                ToolParameter(
                    name="gist_id",
                    type="string",
                    description="Gist ID.",
                    required=False,
                ),
                ToolParameter(
                    name="hook_id",
                    type="integer",
                    description="Webhook hook ID.",
                    required=False,
                ),
                # ── Repository creation / update ───────────────────────── #
                ToolParameter(
                    name="name",
                    type="string",
                    description="Repository or label name.",
                    required=False,
                ),
                ToolParameter(
                    name="description",
                    type="string",
                    description="Repository, release, label, or milestone description.",
                    required=False,
                ),
                ToolParameter(
                    name="private",
                    type="boolean",
                    description="Make the repository private (default: false).",
                    required=False,
                ),
                ToolParameter(
                    name="has_issues",
                    type="boolean",
                    description="Enable issues for the repository.",
                    required=False,
                ),
                ToolParameter(
                    name="has_wiki",
                    type="boolean",
                    description="Enable wiki for the repository.",
                    required=False,
                ),
                ToolParameter(
                    name="has_projects",
                    type="boolean",
                    description="Enable projects for the repository.",
                    required=False,
                ),
                ToolParameter(
                    name="auto_init",
                    type="boolean",
                    description="Initialise the repository with a README on creation.",
                    required=False,
                ),
                ToolParameter(
                    name="gitignore_template",
                    type="string",
                    description="Gitignore template name to apply on creation (e.g. 'Python', 'Node').",
                    required=False,
                ),
                ToolParameter(
                    name="license_template",
                    type="string",
                    description="SPDX license identifier on creation (e.g. 'mit', 'apache-2.0').",
                    required=False,
                ),
                ToolParameter(
                    name="default_branch",
                    type="string",
                    description="Rename the default branch of a repository.",
                    required=False,
                ),
                ToolParameter(
                    name="topics",
                    type="array",
                    description="List of topic strings for set_repo_topics.",
                    required=False,
                ),
                # ── Files & contents ───────────────────────────────────── #
                ToolParameter(
                    name="path",
                    type="string",
                    description="File path within the repository (e.g. 'src/main.py').",
                    required=False,
                ),
                ToolParameter(
                    name="content",
                    type="string",
                    description=(
                        "Plain-text file content for create_or_update_file. "
                        "The tool automatically base64-encodes it for the API."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="sha",
                    type="string",
                    description="Blob SHA of the existing file — required when updating or deleting a file.",
                    required=False,
                ),
                ToolParameter(
                    name="commit_message",
                    type="string",
                    description="Commit message for file create/update/delete operations.",
                    required=False,
                ),
                # ── Branches ──────────────────────────────────────────────#
                ToolParameter(
                    name="branch",
                    type="string",
                    description="Branch name.",
                    required=False,
                ),
                ToolParameter(
                    name="base_branch",
                    type="string",
                    description="Base branch name (source for PRs; target for merges).",
                    required=False,
                ),
                ToolParameter(
                    name="head_branch",
                    type="string",
                    description="Head branch name (source for merges and PRs).",
                    required=False,
                ),
                ToolParameter(
                    name="from_sha",
                    type="string",
                    description="SHA or branch name to create a new branch from.",
                    required=False,
                ),
                # ── Commits ────────────────────────────────────────────── #
                ToolParameter(
                    name="commit_sha",
                    type="string",
                    description="Full or abbreviated commit SHA.",
                    required=False,
                ),
                ToolParameter(
                    name="base_sha",
                    type="string",
                    description="Base commit SHA or ref for compare_commits.",
                    required=False,
                ),
                ToolParameter(
                    name="head_sha",
                    type="string",
                    description="Head commit SHA or ref for compare_commits.",
                    required=False,
                ),
                # ── Pull Requests ─────────────────────────────────────── #
                ToolParameter(
                    name="title",
                    type="string",
                    description="Title for a pull request, issue, release, or milestone.",
                    required=False,
                ),
                ToolParameter(
                    name="body",
                    type="string",
                    description="Body / description text for PRs, issues, reviews, or comments.",
                    required=False,
                ),
                ToolParameter(
                    name="draft",
                    type="boolean",
                    description="Create a pull request as a draft.",
                    required=False,
                ),
                ToolParameter(
                    name="merge_method",
                    type="string",
                    description="Merge strategy for PRs: 'merge', 'squash', or 'rebase'.",
                    required=False,
                    enum=["merge", "squash", "rebase"],
                ),
                ToolParameter(
                    name="review_event",
                    type="string",
                    description="PR review event: 'APPROVE', 'REQUEST_CHANGES', or 'COMMENT'.",
                    required=False,
                    enum=["APPROVE", "REQUEST_CHANGES", "COMMENT"],
                ),
                ToolParameter(
                    name="review_comments",
                    type="array",
                    description=(
                        "Inline review comments for create_pr_review. "
                        "Each item: {'path': 'file.py', 'line': 10, 'body': 'Consider...'}"
                    ),
                    required=False,
                ),
                # ── Issues ────────────────────────────────────────────── #
                ToolParameter(
                    name="labels",
                    type="array",
                    description="List of label name strings.",
                    required=False,
                ),
                ToolParameter(
                    name="assignees",
                    type="array",
                    description="List of GitHub usernames to assign.",
                    required=False,
                ),
                ToolParameter(
                    name="state",
                    type="string",
                    description="Filter state: 'open', 'closed', or 'all'.",
                    required=False,
                    enum=["open", "closed", "all"],
                ),
                ToolParameter(
                    name="lock_reason",
                    type="string",
                    description="Reason for locking an issue: 'off-topic', 'too heated', 'resolved', 'spam'.",
                    required=False,
                    enum=["off-topic", "too heated", "resolved", "spam"],
                ),
                # ── Labels ────────────────────────────────────────────── #
                ToolParameter(
                    name="label_name",
                    type="string",
                    description="Existing label name for update/delete/remove operations.",
                    required=False,
                ),
                ToolParameter(
                    name="color",
                    type="string",
                    description="Hex color code for a label (without '#', e.g. 'ff0000').",
                    required=False,
                ),
                # ── Milestones ────────────────────────────────────────── #
                ToolParameter(
                    name="due_on",
                    type="string",
                    description="Milestone due date in ISO 8601 format (e.g. '2026-06-30T00:00:00Z').",
                    required=False,
                ),
                # ── Releases ──────────────────────────────────────────── #
                ToolParameter(
                    name="tag_name",
                    type="string",
                    description="Tag name for a release or tag list (e.g. 'v1.2.0').",
                    required=False,
                ),
                ToolParameter(
                    name="target_commitish",
                    type="string",
                    description="Branch or commit SHA the release tag should point to.",
                    required=False,
                ),
                ToolParameter(
                    name="prerelease",
                    type="boolean",
                    description="Mark release as a pre-release.",
                    required=False,
                ),
                ToolParameter(
                    name="generate_release_notes",
                    type="boolean",
                    description="Auto-generate release notes from merged PRs.",
                    required=False,
                ),
                # ── Actions ───────────────────────────────────────────── #
                ToolParameter(
                    name="ref",
                    type="string",
                    description="Git ref (branch, tag, or SHA) for triggering a workflow dispatch.",
                    required=False,
                ),
                ToolParameter(
                    name="workflow_inputs",
                    type="object",
                    description="Key-value inputs map for workflow_dispatch events.",
                    required=False,
                ),
                # ── Gists ─────────────────────────────────────────────── #
                ToolParameter(
                    name="files",
                    type="object",
                    description=(
                        "Gist files dict: {'filename.py': {'content': 'print(\"hi\")'}}. "
                        "Set content to null to delete a file when updating."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="public",
                    type="boolean",
                    description="Make the gist public (default: false).",
                    required=False,
                ),
                # ── Branch protection ──────────────────────────────────── #
                ToolParameter(
                    name="required_approvals",
                    type="integer",
                    description="Number of required PR approvals for branch protection.",
                    required=False,
                ),
                ToolParameter(
                    name="dismiss_stale_reviews",
                    type="boolean",
                    description="Dismiss approvals when new commits are pushed.",
                    required=False,
                ),
                ToolParameter(
                    name="require_status_checks",
                    type="array",
                    description="List of required status check context strings.",
                    required=False,
                ),
                # ── Collaborators ─────────────────────────────────────── #
                ToolParameter(
                    name="permission",
                    type="string",
                    description="Collaborator or webhook permission level: 'pull', 'push', 'admin', 'maintain', 'triage'.",
                    required=False,
                    enum=["pull", "push", "admin", "maintain", "triage"],
                ),
                # ── Webhooks ──────────────────────────────────────────── #
                ToolParameter(
                    name="webhook_url",
                    type="string",
                    description="Payload URL for a new webhook.",
                    required=False,
                ),
                ToolParameter(
                    name="webhook_events",
                    type="array",
                    description="List of event types the webhook should fire for (e.g. ['push', 'pull_request']).",
                    required=False,
                ),
                ToolParameter(
                    name="webhook_secret",
                    type="string",
                    description="Optional shared secret for webhook payload signing.",
                    required=False,
                ),
                # ── Search ────────────────────────────────────────────── #
                ToolParameter(
                    name="query",
                    type="string",
                    description="Search query string (GitHub search syntax supported).",
                    required=False,
                ),
                ToolParameter(
                    name="sort",
                    type="string",
                    description="Sort field for search results (e.g. 'stars', 'updated', 'created').",
                    required=False,
                ),
                ToolParameter(
                    name="order",
                    type="string",
                    description="Sort order: 'asc' or 'desc'.",
                    required=False,
                    enum=["asc", "desc"],
                ),
                # ── Pagination / filtering ─────────────────────────────── #
                ToolParameter(
                    name="per_page",
                    type="integer",
                    description=f"Results per page (default: {_DEFAULT_PER_PAGE}, max: 100).",
                    required=False,
                ),
                ToolParameter(
                    name="page",
                    type="integer",
                    description="Page number for paginated results (default: 1).",
                    required=False,
                ),
                ToolParameter(
                    name="max_results",
                    type="integer",
                    description="Auto-paginate and return up to this many total results (default: 30).",
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
        owner: Optional[str] = None,
        repo: Optional[str] = None,
        username: Optional[str] = None,
        org: Optional[str] = None,
        team_slug: Optional[str] = None,
        issue_number: Optional[int] = None,
        pr_number: Optional[int] = None,
        comment_id: Optional[int] = None,
        milestone_number: Optional[int] = None,
        release_id: Optional[int] = None,
        workflow_id: Optional[str] = None,
        run_id: Optional[int] = None,
        gist_id: Optional[str] = None,
        hook_id: Optional[int] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        private: Optional[bool] = None,
        has_issues: Optional[bool] = None,
        has_wiki: Optional[bool] = None,
        has_projects: Optional[bool] = None,
        auto_init: Optional[bool] = None,
        gitignore_template: Optional[str] = None,
        license_template: Optional[str] = None,
        default_branch: Optional[str] = None,
        topics: Optional[List[str]] = None,
        path: Optional[str] = None,
        content: Optional[str] = None,
        sha: Optional[str] = None,
        commit_message: Optional[str] = None,
        branch: Optional[str] = None,
        base_branch: Optional[str] = None,
        head_branch: Optional[str] = None,
        from_sha: Optional[str] = None,
        commit_sha: Optional[str] = None,
        base_sha: Optional[str] = None,
        head_sha: Optional[str] = None,
        title: Optional[str] = None,
        body: Optional[str] = None,
        draft: Optional[bool] = None,
        merge_method: str = "merge",
        review_event: Optional[str] = None,
        review_comments: Optional[List[Dict[str, Any]]] = None,
        labels: Optional[List[str]] = None,
        assignees: Optional[List[str]] = None,
        state: Optional[str] = None,
        lock_reason: Optional[str] = None,
        label_name: Optional[str] = None,
        color: Optional[str] = None,
        due_on: Optional[str] = None,
        tag_name: Optional[str] = None,
        target_commitish: Optional[str] = None,
        prerelease: Optional[bool] = None,
        generate_release_notes: Optional[bool] = None,
        ref: Optional[str] = None,
        workflow_inputs: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
        public: Optional[bool] = None,
        required_approvals: Optional[int] = None,
        dismiss_stale_reviews: Optional[bool] = None,
        require_status_checks: Optional[List[str]] = None,
        permission: Optional[str] = None,
        webhook_url: Optional[str] = None,
        webhook_events: Optional[List[str]] = None,
        webhook_secret: Optional[str] = None,
        query: Optional[str] = None,
        sort: Optional[str] = None,
        order: Optional[str] = None,
        per_page: int = _DEFAULT_PER_PAGE,
        page: int = 1,
        max_results: int = _DEFAULT_PER_PAGE,
        **_: Any,
    ) -> Dict[str, Any]:
        per_page = min(max(1, per_page), 100)

        def r(path: str) -> str:
            """Shorthand: resolve owner/repo path prefix."""
            if not owner or not repo:
                raise ValueError("'owner' and 'repo' are required for this operation.")
            return f"repos/{owner}/{repo}/{path}"

        try:
            # ================================================================ #
            #  REPOSITORIES                                                     #
            # ================================================================ #

            if operation == "list_repos":
                target = org or username
                if target and org:
                    data = self._paginate(
                        f"orgs/{org}/repos",
                        {"type": "all", "sort": sort or "full_name"},
                        max_results,
                    )
                elif target:
                    data = self._paginate(
                        f"users/{target}/repos",
                        {"sort": sort or "updated"},
                        max_results,
                    )
                else:
                    data = self._paginate(
                        "user/repos",
                        {"sort": sort or "updated", "affiliation": "owner"},
                        max_results,
                    )
                return _ok(operation, {"repos": data, "count": len(data)})

            elif operation == "get_repo":
                _req("owner", owner)
                _req("repo", repo)
                return _ok(operation, {"repo": self._get(f"repos/{owner}/{repo}")})

            elif operation == "create_repo":
                _req("name", name)
                payload: Dict[str, Any] = {"name": name}
                _set(payload, "description", description)
                _set(payload, "private", private)
                _set(payload, "has_issues", has_issues)
                _set(payload, "has_wiki", has_wiki)
                _set(payload, "has_projects", has_projects)
                _set(payload, "auto_init", auto_init)
                _set(payload, "gitignore_template", gitignore_template)
                _set(payload, "license_template", license_template)
                endpoint = f"orgs/{org}/repos" if org else "user/repos"
                result = self._post(endpoint, payload)
                return _ok(
                    operation, {"repo": result, "clone_url": result.get("clone_url")}
                )

            elif operation == "update_repo":
                _req("owner", owner)
                _req("repo", repo)
                payload = {}
                _set(payload, "name", name)
                _set(payload, "description", description)
                _set(payload, "private", private)
                _set(payload, "has_issues", has_issues)
                _set(payload, "has_wiki", has_wiki)
                _set(payload, "has_projects", has_projects)
                _set(payload, "default_branch", default_branch)
                return _ok(
                    operation, {"repo": self._patch(f"repos/{owner}/{repo}", payload)}
                )

            elif operation == "delete_repo":
                _req("owner", owner)
                _req("repo", repo)
                self._delete(f"repos/{owner}/{repo}")
                return _ok(operation, {"deleted": True, "repo": f"{owner}/{repo}"})

            elif operation == "fork_repo":
                _req("owner", owner)
                _req("repo", repo)
                payload = {}
                if org:
                    payload["organization"] = org
                result = self._post(f"repos/{owner}/{repo}/forks", payload)
                return _ok(
                    operation, {"fork": result, "clone_url": result.get("clone_url")}
                )

            elif operation == "list_repo_topics":
                return _ok(
                    operation, {"topics": self._get(r("topics")).get("names", [])}
                )

            elif operation == "set_repo_topics":
                _req("topics", topics)
                self._put(r("topics"), {"names": topics})
                return _ok(operation, {"topics": topics})

            elif operation == "get_repo_languages":
                return _ok(operation, {"languages": self._get(r("languages"))})

            elif operation == "get_repo_contributors":
                data = self._paginate(r("contributors"), {}, max_results)
                return _ok(operation, {"contributors": data, "count": len(data)})

            elif operation == "get_repo_traffic":
                views = self._get(r("traffic/views"))
                clones = self._get(r("traffic/clones"))
                popular = self._get(r("traffic/popular/referrers"))
                return _ok(
                    operation, {"views": views, "clones": clones, "referrers": popular}
                )

            # ================================================================ #
            #  FILES & CONTENTS                                                #
            # ================================================================ #

            elif operation == "get_file":
                _req("path", path)
                params = {"ref": branch} if branch else {}
                result = self._get(r(f"contents/{path}"), params=params)
                decoded = base64.b64decode(result.get("content", "")).decode(
                    "utf-8", errors="replace"
                )
                return _ok(
                    operation,
                    {"file": result, "content": decoded, "sha": result.get("sha")},
                )

            elif operation == "create_or_update_file":
                _req("path", path)
                _req("content", content)
                _req("commit_message", commit_message)
                payload = {
                    "message": commit_message,
                    "content": base64.b64encode(content.encode()).decode(),  # type: ignore[union-attr]
                }
                if sha:
                    payload["sha"] = sha
                if branch:
                    payload["branch"] = branch
                result = self._put(r(f"contents/{path}"), payload)
                return _ok(
                    operation,
                    {
                        "sha": result.get("content", {}).get("sha"),
                        "commit_sha": result.get("commit", {}).get("sha"),
                        "url": result.get("content", {}).get("html_url"),
                    },
                )

            elif operation == "delete_file":
                _req("path", path)
                _req("sha", sha)
                _req("commit_message", commit_message)
                payload = {"message": commit_message, "sha": sha}
                if branch:
                    payload["branch"] = branch
                result = self._delete(r(f"contents/{path}"), payload)
                return _ok(
                    operation,
                    {
                        "commit_sha": result.get("commit", {}).get("sha"),
                        "deleted": True,
                    },
                )

            elif operation == "list_directory":
                params = {"ref": branch} if branch else {}
                result = self._get(r(f"contents/{path or ''}"), params=params)
                items = result if isinstance(result, list) else [result]
                return _ok(operation, {"items": items, "count": len(items)})

            elif operation == "get_readme":
                params = {"ref": branch} if branch else {}
                result = self._get(r("readme"), params=params)
                decoded = base64.b64decode(result.get("content", "")).decode(
                    "utf-8", errors="replace"
                )
                return _ok(operation, {"readme": result, "content": decoded})

            # ================================================================ #
            #  BRANCHES                                                        #
            # ================================================================ #

            elif operation == "list_branches":
                data = self._paginate(r("branches"), {}, max_results)
                return _ok(operation, {"branches": data, "count": len(data)})

            elif operation == "get_branch":
                _req("branch", branch)
                return _ok(operation, {"branch": self._get(r(f"branches/{branch}"))})

            elif operation == "create_branch":
                _req("branch", branch)
                _req("from_sha", from_sha)
                result = self._post(
                    r("git/refs"), {"ref": f"refs/heads/{branch}", "sha": from_sha}
                )
                return _ok(operation, {"ref": result})

            elif operation == "delete_branch":
                _req("branch", branch)
                self._delete(r(f"git/refs/heads/{branch}"))
                return _ok(operation, {"deleted": True, "branch": branch})

            elif operation == "merge_branches":
                _req("base_branch", base_branch)
                _req("head_branch", head_branch)
                payload = {"base": base_branch, "head": head_branch}
                if commit_message:
                    payload["commit_message"] = commit_message
                result = self._post(r("merges"), payload)
                return _ok(operation, {"merge_commit": result})

            elif operation == "protect_branch":
                _req("branch", branch)
                payload = {
                    "required_status_checks": {
                        "strict": True,
                        "contexts": require_status_checks or [],
                    }
                    if require_status_checks is not None
                    else None,
                    "enforce_admins": True,
                    "required_pull_request_reviews": {
                        "required_approving_review_count": required_approvals or 1,
                        "dismiss_stale_reviews": dismiss_stale_reviews or False,
                    },
                    "restrictions": None,
                }
                result = self._put(
                    r(f"branches/{branch}/protection"),
                    {k: v for k, v in payload.items() if v is not None},
                )
                return _ok(operation, {"protection": result})

            elif operation == "unprotect_branch":
                _req("branch", branch)
                self._delete(r(f"branches/{branch}/protection"))
                return _ok(operation, {"unprotected": True, "branch": branch})

            # ================================================================ #
            #  COMMITS                                                         #
            # ================================================================ #

            elif operation == "list_commits":
                params = {"sha": branch, "per_page": per_page, "page": page}
                data = self._paginate(r("commits"), params, max_results)
                return _ok(operation, {"commits": data, "count": len(data)})

            elif operation == "get_commit":
                _req("commit_sha", commit_sha)
                return _ok(operation, {"commit": self._get(r(f"commits/{commit_sha}"))})

            elif operation == "compare_commits":
                _req("base_sha", base_sha)
                _req("head_sha", head_sha)
                return _ok(
                    operation,
                    {"comparison": self._get(r(f"compare/{base_sha}...{head_sha}"))},
                )

            # ================================================================ #
            #  PULL REQUESTS                                                   #
            # ================================================================ #

            elif operation == "list_pull_requests":
                params = {"state": state or "open", "per_page": per_page, "page": page}
                if base_branch:
                    params["base"] = base_branch
                data = self._paginate(r("pulls"), params, max_results)
                return _ok(operation, {"pull_requests": data, "count": len(data)})

            elif operation == "get_pull_request":
                _req("pr_number", pr_number)
                return _ok(
                    operation, {"pull_request": self._get(r(f"pulls/{pr_number}"))}
                )

            elif operation == "create_pull_request":
                _req("title", title)
                _req("head_branch", head_branch)
                _req("base_branch", base_branch)
                payload = {"title": title, "head": head_branch, "base": base_branch}
                _set(payload, "body", body)
                _set(payload, "draft", draft)
                result = self._post(r("pulls"), payload)
                return _ok(
                    operation,
                    {
                        "pull_request": result,
                        "number": result.get("number"),
                        "url": result.get("html_url"),
                    },
                )

            elif operation == "update_pull_request":
                _req("pr_number", pr_number)
                payload = {}
                _set(payload, "title", title)
                _set(payload, "body", body)
                _set(payload, "state", state)
                _set(payload, "base", base_branch)
                return _ok(
                    operation,
                    {"pull_request": self._patch(r(f"pulls/{pr_number}"), payload)},
                )

            elif operation == "merge_pull_request":
                _req("pr_number", pr_number)
                payload = {"merge_method": merge_method}
                _set(payload, "commit_title", title)
                _set(payload, "commit_message", body)
                return _ok(
                    operation,
                    {"merge": self._put(r(f"pulls/{pr_number}/merge"), payload)},
                )

            elif operation == "close_pull_request":
                _req("pr_number", pr_number)
                return _ok(
                    operation,
                    {
                        "pull_request": self._patch(
                            r(f"pulls/{pr_number}"), {"state": "closed"}
                        )
                    },
                )

            elif operation == "list_pr_reviews":
                _req("pr_number", pr_number)
                data = self._get(r(f"pulls/{pr_number}/reviews"))
                return _ok(operation, {"reviews": data, "count": len(data)})

            elif operation == "create_pr_review":
                _req("pr_number", pr_number)
                _req("review_event", review_event)
                payload = {"event": review_event}
                _set(payload, "body", body)
                if review_comments:
                    payload["comments"] = review_comments
                return _ok(
                    operation,
                    {"review": self._post(r(f"pulls/{pr_number}/reviews"), payload)},
                )

            elif operation == "list_pr_files":
                _req("pr_number", pr_number)
                data = self._get(r(f"pulls/{pr_number}/files"))
                return _ok(operation, {"files": data, "count": len(data)})

            elif operation == "list_pr_comments":
                _req("pr_number", pr_number)
                data = self._paginate(r(f"pulls/{pr_number}/comments"), {}, max_results)
                return _ok(operation, {"comments": data, "count": len(data)})

            elif operation == "add_pr_comment":
                _req("pr_number", pr_number)
                _req("body", body)
                result = self._post(r(f"issues/{pr_number}/comments"), {"body": body})
                return _ok(operation, {"comment": result, "id": result.get("id")})

            # ================================================================ #
            #  ISSUES                                                          #
            # ================================================================ #

            elif operation == "list_issues":
                params = {
                    "state": state or "open",
                    "per_page": per_page,
                    "page": page,
                    "labels": ",".join(labels) if labels else None,
                    "assignee": assignees[0] if assignees else None,
                    "milestone": milestone_number,
                    "sort": sort or "created",
                }
                data = self._paginate(r("issues"), params, max_results)
                return _ok(operation, {"issues": data, "count": len(data)})

            elif operation == "get_issue":
                _req("issue_number", issue_number)
                return _ok(operation, {"issue": self._get(r(f"issues/{issue_number}"))})

            elif operation == "create_issue":
                _req("title", title)
                payload = {"title": title}
                _set(payload, "body", body)
                _set(payload, "labels", labels)
                _set(payload, "assignees", assignees)
                if milestone_number:
                    payload["milestone"] = milestone_number
                result = self._post(r("issues"), payload)
                return _ok(
                    operation,
                    {
                        "issue": result,
                        "number": result.get("number"),
                        "url": result.get("html_url"),
                    },
                )

            elif operation == "update_issue":
                _req("issue_number", issue_number)
                payload = {}
                _set(payload, "title", title)
                _set(payload, "body", body)
                _set(payload, "labels", labels)
                _set(payload, "assignees", assignees)
                _set(payload, "state", state)
                if milestone_number is not None:
                    payload["milestone"] = milestone_number
                return _ok(
                    operation,
                    {"issue": self._patch(r(f"issues/{issue_number}"), payload)},
                )

            elif operation == "close_issue":
                _req("issue_number", issue_number)
                return _ok(
                    operation,
                    {
                        "issue": self._patch(
                            r(f"issues/{issue_number}"), {"state": "closed"}
                        )
                    },
                )

            elif operation == "reopen_issue":
                _req("issue_number", issue_number)
                return _ok(
                    operation,
                    {
                        "issue": self._patch(
                            r(f"issues/{issue_number}"), {"state": "open"}
                        )
                    },
                )

            elif operation == "lock_issue":
                _req("issue_number", issue_number)
                payload = {}
                if lock_reason:
                    payload["lock_reason"] = lock_reason
                self._put(r(f"issues/{issue_number}/lock"), payload)
                return _ok(operation, {"locked": True, "issue_number": issue_number})

            elif operation == "unlock_issue":
                _req("issue_number", issue_number)
                self._delete(r(f"issues/{issue_number}/lock"))
                return _ok(operation, {"unlocked": True, "issue_number": issue_number})

            elif operation == "list_issue_comments":
                _req("issue_number", issue_number)
                data = self._paginate(
                    r(f"issues/{issue_number}/comments"), {}, max_results
                )
                return _ok(operation, {"comments": data, "count": len(data)})

            elif operation == "add_issue_comment":
                _req("issue_number", issue_number)
                _req("body", body)
                result = self._post(
                    r(f"issues/{issue_number}/comments"), {"body": body}
                )
                return _ok(operation, {"comment": result, "id": result.get("id")})

            elif operation == "update_issue_comment":
                _req("comment_id", comment_id)
                _req("body", body)
                result = self._patch(r(f"issues/comments/{comment_id}"), {"body": body})
                return _ok(operation, {"comment": result})

            elif operation == "delete_issue_comment":
                _req("comment_id", comment_id)
                self._delete(r(f"issues/comments/{comment_id}"))
                return _ok(operation, {"deleted": True, "comment_id": comment_id})

            elif operation == "add_labels":
                _req("issue_number", issue_number)
                _req("labels", labels)
                result = self._post(
                    r(f"issues/{issue_number}/labels"), {"labels": labels}
                )
                return _ok(operation, {"labels": result})

            elif operation == "remove_label":
                _req("issue_number", issue_number)
                _req("label_name", label_name)
                self._delete(r(f"issues/{issue_number}/labels/{label_name}"))
                return _ok(operation, {"removed": True, "label": label_name})

            elif operation == "set_assignees":
                _req("issue_number", issue_number)
                _req("assignees", assignees)
                result = self._post(
                    r(f"issues/{issue_number}/assignees"), {"assignees": assignees}
                )
                return _ok(operation, {"issue": result})

            # ================================================================ #
            #  LABELS                                                          #
            # ================================================================ #

            elif operation == "list_labels":
                data = self._paginate(r("labels"), {}, max_results)
                return _ok(operation, {"labels": data, "count": len(data)})

            elif operation == "create_label":
                _req("name", name)
                _req("color", color)
                payload = {"name": name, "color": color}
                _set(payload, "description", description)
                return _ok(operation, {"label": self._post(r("labels"), payload)})

            elif operation == "update_label":
                _req("label_name", label_name)
                payload = {}
                _set(payload, "name", name)
                _set(payload, "color", color)
                _set(payload, "description", description)
                return _ok(
                    operation,
                    {"label": self._patch(r(f"labels/{label_name}"), payload)},
                )

            elif operation == "delete_label":
                _req("label_name", label_name)
                self._delete(r(f"labels/{label_name}"))
                return _ok(operation, {"deleted": True, "label": label_name})

            # ================================================================ #
            #  MILESTONES                                                      #
            # ================================================================ #

            elif operation == "list_milestones":
                data = self._paginate(
                    r("milestones"), {"state": state or "open"}, max_results
                )
                return _ok(operation, {"milestones": data, "count": len(data)})

            elif operation == "create_milestone":
                _req("title", title)
                payload = {"title": title}
                _set(payload, "description", description)
                _set(payload, "due_on", due_on)
                _set(payload, "state", state)
                return _ok(
                    operation, {"milestone": self._post(r("milestones"), payload)}
                )

            elif operation == "update_milestone":
                _req("milestone_number", milestone_number)
                payload = {}
                _set(payload, "title", title)
                _set(payload, "description", description)
                _set(payload, "due_on", due_on)
                _set(payload, "state", state)
                return _ok(
                    operation,
                    {
                        "milestone": self._patch(
                            r(f"milestones/{milestone_number}"), payload
                        )
                    },
                )

            elif operation == "delete_milestone":
                _req("milestone_number", milestone_number)
                self._delete(r(f"milestones/{milestone_number}"))
                return _ok(
                    operation, {"deleted": True, "milestone_number": milestone_number}
                )

            # ================================================================ #
            #  RELEASES & TAGS                                                 #
            # ================================================================ #

            elif operation == "list_releases":
                data = self._paginate(r("releases"), {}, max_results)
                return _ok(operation, {"releases": data, "count": len(data)})

            elif operation == "get_release":
                _req("release_id", release_id)
                return _ok(
                    operation, {"release": self._get(r(f"releases/{release_id}"))}
                )

            elif operation == "get_latest_release":
                return _ok(operation, {"release": self._get(r("releases/latest"))})

            elif operation == "create_release":
                _req("tag_name", tag_name)
                payload = {"tag_name": tag_name}
                _set(payload, "name", title)
                _set(payload, "body", body)
                _set(payload, "target_commitish", target_commitish)
                _set(payload, "prerelease", prerelease)
                _set(payload, "generate_release_notes", generate_release_notes)
                result = self._post(r("releases"), payload)
                return _ok(
                    operation,
                    {
                        "release": result,
                        "id": result.get("id"),
                        "url": result.get("html_url"),
                    },
                )

            elif operation == "update_release":
                _req("release_id", release_id)
                payload = {}
                _set(payload, "tag_name", tag_name)
                _set(payload, "name", title)
                _set(payload, "body", body)
                _set(payload, "prerelease", prerelease)
                return _ok(
                    operation,
                    {"release": self._patch(r(f"releases/{release_id}"), payload)},
                )

            elif operation == "delete_release":
                _req("release_id", release_id)
                self._delete(r(f"releases/{release_id}"))
                return _ok(operation, {"deleted": True, "release_id": release_id})

            elif operation == "list_tags":
                data = self._paginate(r("tags"), {}, max_results)
                return _ok(operation, {"tags": data, "count": len(data)})

            # ================================================================ #
            #  GITHUB ACTIONS                                                  #
            # ================================================================ #

            elif operation == "list_workflows":
                result = self._get(r("actions/workflows"))
                return _ok(
                    operation,
                    {
                        "workflows": result.get("workflows", []),
                        "count": result.get("total_count", 0),
                    },
                )

            elif operation == "get_workflow":
                _req("workflow_id", workflow_id)
                return _ok(
                    operation,
                    {"workflow": self._get(r(f"actions/workflows/{workflow_id}"))},
                )

            elif operation == "trigger_workflow":
                _req("workflow_id", workflow_id)
                _req("ref", ref)
                payload = {"ref": ref, "inputs": workflow_inputs or {}}
                self._post(r(f"actions/workflows/{workflow_id}/dispatches"), payload)
                return _ok(
                    operation,
                    {"triggered": True, "workflow_id": workflow_id, "ref": ref},
                )

            elif operation == "list_workflow_runs":
                params = {"per_page": per_page, "page": page}
                if workflow_id:
                    data = self._paginate(
                        r(f"actions/workflows/{workflow_id}/runs"), params, max_results
                    )
                else:
                    result = self._get(r("actions/runs"), params=params)
                    data = result.get("workflow_runs", [])
                return _ok(operation, {"runs": data, "count": len(data)})

            elif operation == "get_workflow_run":
                _req("run_id", run_id)
                return _ok(operation, {"run": self._get(r(f"actions/runs/{run_id}"))})

            elif operation == "cancel_workflow_run":
                _req("run_id", run_id)
                self._post(r(f"actions/runs/{run_id}/cancel"), {})
                return _ok(operation, {"cancelled": True, "run_id": run_id})

            elif operation == "rerun_workflow":
                _req("run_id", run_id)
                self._post(r(f"actions/runs/{run_id}/rerun"), {})
                return _ok(operation, {"rerun": True, "run_id": run_id})

            elif operation == "list_run_jobs":
                _req("run_id", run_id)
                result = self._get(r(f"actions/runs/{run_id}/jobs"))
                return _ok(
                    operation,
                    {
                        "jobs": result.get("jobs", []),
                        "count": result.get("total_count", 0),
                    },
                )

            elif operation == "get_run_logs_url":
                _req("run_id", run_id)
                # GitHub returns a 302 redirect to the log archive URL
                url = f"{_BASE_URL}/repos/{owner}/{repo}/actions/runs/{run_id}/logs"
                resp = requests.get(url, headers=self._headers(), allow_redirects=False)
                logs_url = resp.headers.get("Location", "")
                return _ok(operation, {"logs_url": logs_url})

            elif operation == "list_repo_secrets":
                result = self._get(r("actions/secrets"))
                return _ok(
                    operation,
                    {
                        "secrets": result.get("secrets", []),
                        "count": result.get("total_count", 0),
                    },
                )

            # ================================================================ #
            #  GISTS                                                           #
            # ================================================================ #

            elif operation == "list_gists":
                target = username or "self"
                if username:
                    data = self._paginate(f"users/{username}/gists", {}, max_results)
                else:
                    data = self._paginate("gists", {}, max_results)
                return _ok(operation, {"gists": data, "count": len(data)})

            elif operation == "get_gist":
                _req("gist_id", gist_id)
                return _ok(operation, {"gist": self._get(f"gists/{gist_id}")})

            elif operation == "create_gist":
                _req("files", files)
                payload = {"files": files, "public": public or False}
                _set(payload, "description", description)
                result = self._post("gists", payload)
                return _ok(
                    operation,
                    {
                        "gist": result,
                        "id": result.get("id"),
                        "url": result.get("html_url"),
                    },
                )

            elif operation == "update_gist":
                _req("gist_id", gist_id)
                payload = {}
                _set(payload, "description", description)
                _set(payload, "files", files)
                return _ok(
                    operation, {"gist": self._patch(f"gists/{gist_id}", payload)}
                )

            elif operation == "delete_gist":
                _req("gist_id", gist_id)
                self._delete(f"gists/{gist_id}")
                return _ok(operation, {"deleted": True, "gist_id": gist_id})

            elif operation == "star_gist":
                _req("gist_id", gist_id)
                self._put(f"gists/{gist_id}/star")
                return _ok(operation, {"starred": True, "gist_id": gist_id})

            elif operation == "unstar_gist":
                _req("gist_id", gist_id)
                self._delete(f"gists/{gist_id}/star")
                return _ok(operation, {"unstarred": True, "gist_id": gist_id})

            # ================================================================ #
            #  NOTIFICATIONS                                                   #
            # ================================================================ #

            elif operation == "list_notifications":
                data = self._get(
                    "notifications",
                    params={"all": True, "per_page": per_page, "page": page},
                )
                return _ok(
                    operation,
                    {
                        "notifications": data,
                        "count": len(data) if isinstance(data, list) else 0,
                    },
                )

            elif operation == "mark_notifications_read":
                self._put("notifications", {})
                return _ok(operation, {"marked_read": True})

            # ================================================================ #
            #  SEARCH                                                          #
            # ================================================================ #

            elif operation == "search_code":
                _req("query", query)
                result = self._get(
                    "search/code",
                    params={
                        "q": query,
                        "per_page": per_page,
                        "page": page,
                        "sort": sort,
                        "order": order,
                    },
                )
                return _ok(
                    operation,
                    {
                        "items": result.get("items", []),
                        "total_count": result.get("total_count", 0),
                    },
                )

            elif operation == "search_repos":
                _req("query", query)
                result = self._get(
                    "search/repositories",
                    params={
                        "q": query,
                        "per_page": per_page,
                        "page": page,
                        "sort": sort,
                        "order": order,
                    },
                )
                return _ok(
                    operation,
                    {
                        "items": result.get("items", []),
                        "total_count": result.get("total_count", 0),
                    },
                )

            elif operation == "search_issues":
                _req("query", query)
                result = self._get(
                    "search/issues",
                    params={
                        "q": query,
                        "per_page": per_page,
                        "page": page,
                        "sort": sort,
                        "order": order,
                    },
                )
                return _ok(
                    operation,
                    {
                        "items": result.get("items", []),
                        "total_count": result.get("total_count", 0),
                    },
                )

            elif operation == "search_users":
                _req("query", query)
                result = self._get(
                    "search/users",
                    params={
                        "q": query,
                        "per_page": per_page,
                        "page": page,
                        "sort": sort,
                        "order": order,
                    },
                )
                return _ok(
                    operation,
                    {
                        "items": result.get("items", []),
                        "total_count": result.get("total_count", 0),
                    },
                )

            elif operation == "search_commits":
                _req("query", query)
                result = self._get(
                    "search/commits",
                    params={
                        "q": query,
                        "per_page": per_page,
                        "page": page,
                        "sort": sort,
                        "order": order,
                    },
                )
                return _ok(
                    operation,
                    {
                        "items": result.get("items", []),
                        "total_count": result.get("total_count", 0),
                    },
                )

            # ================================================================ #
            #  USERS                                                           #
            # ================================================================ #

            elif operation == "get_authenticated_user":
                return _ok(operation, {"user": self._get("user")})

            elif operation == "get_user":
                _req("username", username)
                return _ok(operation, {"user": self._get(f"users/{username}")})

            elif operation == "list_user_repos":
                _req("username", username)
                data = self._paginate(
                    f"users/{username}/repos", {"sort": sort or "updated"}, max_results
                )
                return _ok(operation, {"repos": data, "count": len(data)})

            elif operation == "list_followers":
                target = username or "self"
                path = f"users/{target}/followers" if username else "user/followers"
                data = self._paginate(path, {}, max_results)
                return _ok(operation, {"followers": data, "count": len(data)})

            elif operation == "list_following":
                path = f"users/{username}/following" if username else "user/following"
                data = self._paginate(path, {}, max_results)
                return _ok(operation, {"following": data, "count": len(data)})

            elif operation == "follow_user":
                _req("username", username)
                self._put(f"user/following/{username}")
                return _ok(operation, {"following": True, "username": username})

            elif operation == "unfollow_user":
                _req("username", username)
                self._delete(f"user/following/{username}")
                return _ok(operation, {"unfollowed": True, "username": username})

            elif operation == "list_user_gists":
                _req("username", username)
                data = self._paginate(f"users/{username}/gists", {}, max_results)
                return _ok(operation, {"gists": data, "count": len(data)})

            # ================================================================ #
            #  ORGANIZATIONS                                                   #
            # ================================================================ #

            elif operation == "get_org":
                _req("org", org)
                return _ok(operation, {"org": self._get(f"orgs/{org}")})

            elif operation == "list_org_repos":
                _req("org", org)
                data = self._paginate(f"orgs/{org}/repos", {"type": "all"}, max_results)
                return _ok(operation, {"repos": data, "count": len(data)})

            elif operation == "list_org_members":
                _req("org", org)
                data = self._paginate(f"orgs/{org}/members", {}, max_results)
                return _ok(operation, {"members": data, "count": len(data)})

            elif operation == "list_org_teams":
                _req("org", org)
                data = self._paginate(f"orgs/{org}/teams", {}, max_results)
                return _ok(operation, {"teams": data, "count": len(data)})

            elif operation == "get_team":
                _req("org", org)
                _req("team_slug", team_slug)
                return _ok(
                    operation, {"team": self._get(f"orgs/{org}/teams/{team_slug}")}
                )

            elif operation == "list_team_members":
                _req("org", org)
                _req("team_slug", team_slug)
                data = self._paginate(
                    f"orgs/{org}/teams/{team_slug}/members", {}, max_results
                )
                return _ok(operation, {"members": data, "count": len(data)})

            elif operation == "list_team_repos":
                _req("org", org)
                _req("team_slug", team_slug)
                data = self._paginate(
                    f"orgs/{org}/teams/{team_slug}/repos", {}, max_results
                )
                return _ok(operation, {"repos": data, "count": len(data)})

            # ================================================================ #
            #  STARRING & WATCHING                                             #
            # ================================================================ #

            elif operation == "star_repo":
                _req("owner", owner)
                _req("repo", repo)
                self._put(f"user/starred/{owner}/{repo}")
                return _ok(operation, {"starred": True, "repo": f"{owner}/{repo}"})

            elif operation == "unstar_repo":
                _req("owner", owner)
                _req("repo", repo)
                self._delete(f"user/starred/{owner}/{repo}")
                return _ok(operation, {"unstarred": True, "repo": f"{owner}/{repo}"})

            elif operation == "list_stargazers":
                data = self._paginate(r("stargazers"), {}, max_results)
                return _ok(operation, {"stargazers": data, "count": len(data)})

            elif operation == "watch_repo":
                _req("owner", owner)
                _req("repo", repo)
                self._put(f"repos/{owner}/{repo}/subscription", {"subscribed": True})
                return _ok(operation, {"watching": True, "repo": f"{owner}/{repo}"})

            elif operation == "unwatch_repo":
                _req("owner", owner)
                _req("repo", repo)
                self._delete(f"repos/{owner}/{repo}/subscription")
                return _ok(operation, {"unwatched": True, "repo": f"{owner}/{repo}"})

            elif operation == "list_watchers":
                data = self._paginate(r("subscribers"), {}, max_results)
                return _ok(operation, {"watchers": data, "count": len(data)})

            # ================================================================ #
            #  COLLABORATORS                                                   #
            # ================================================================ #

            elif operation == "list_collaborators":
                data = self._paginate(r("collaborators"), {}, max_results)
                return _ok(operation, {"collaborators": data, "count": len(data)})

            elif operation == "add_collaborator":
                _req("username", username)
                payload = {}
                if permission:
                    payload["permission"] = permission
                self._put(r(f"collaborators/{username}"), payload)
                return _ok(
                    operation,
                    {
                        "added": True,
                        "username": username,
                        "permission": permission or "push",
                    },
                )

            elif operation == "remove_collaborator":
                _req("username", username)
                self._delete(r(f"collaborators/{username}"))
                return _ok(operation, {"removed": True, "username": username})

            # ================================================================ #
            #  WEBHOOKS                                                        #
            # ================================================================ #

            elif operation == "list_webhooks":
                data = self._get(r("hooks"))
                return _ok(operation, {"webhooks": data, "count": len(data)})

            elif operation == "create_webhook":
                _req("webhook_url", webhook_url)
                payload = {
                    "name": "web",
                    "active": True,
                    "events": webhook_events or ["push"],
                    "config": {
                        "url": webhook_url,
                        "content_type": "json",
                        **({"secret": webhook_secret} if webhook_secret else {}),
                    },
                }
                result = self._post(r("hooks"), payload)
                return _ok(operation, {"webhook": result, "id": result.get("id")})

            elif operation == "delete_webhook":
                _req("hook_id", hook_id)
                self._delete(r(f"hooks/{hook_id}"))
                return _ok(operation, {"deleted": True, "hook_id": hook_id})

            return _err(f"Unknown operation: {operation}")

        except ValueError as e:
            return _err(str(e))
        except requests.HTTPError as e:
            body: Dict[str, Any] = {}
            try:
                body = e.response.json()
            except Exception:
                pass
            return {
                "success": False,
                "error": body.get("message", str(e)),
                "documentation_url": body.get("documentation_url"),
                "status_code": e.response.status_code
                if e.response is not None
                else None,
            }
        except Exception as e:
            return {"success": False, "error": f"GitHub tool error: {str(e)}"}


# ── Module-level helpers ──────────────────────────────────────────────────── #


def _ok(operation: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {"success": True, "operation": operation, **data}


def _err(message: str) -> Dict[str, Any]:
    return {"success": False, "error": message}


def _req(field: str, value: Any) -> None:
    """Raise ValueError if a required parameter is missing."""
    if value is None or value == "":
        raise ValueError(f"'{field}' is required for this operation.")


def _set(payload: Dict[str, Any], key: str, value: Any) -> None:
    """Add key to payload only if value is not None."""
    if value is not None:
        payload[key] = value
