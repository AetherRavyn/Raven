import asyncio
import os
import shlex
from typing import Any, Dict, List, Optional

from app.tools.base import BaseTool, ToolParameter, ToolSchema




class GitOperationTool(BaseTool):
    def __init__(self, repo_path: str = "."):
        self.repo_path = os.path.abspath(repo_path)
        if not os.path.isdir(os.path.join(self.repo_path, ".git")):
            # Optional: You could auto-init if you want
            raise ValueError(
                f"Directory '{self.repo_path}' is not a valid git repository."
            )

        self.MAX_OUTPUT_LENGTH = 8000  # Increased for better context

    def get_name(self) -> str:
        return "git_ops"

    def get_description(self) -> str:
        return (
            "The ultimate Git tool. "
            "Handles all version control tasks: state inspection, history, branching, "
            "remote syncing, conflict resolution, cherry-picking, tagging, and stashing."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="The git operation to perform.",
                    required=True,
                    enum=[
                        # --- 1. Inspection & State ---
                        "status",
                        "log",
                        "diff",
                        "show_file",
                        "blame",
                        "ls_files",
                        "current_branch",
                        "remote_url",
                        # --- 2. Staging & Committing ---
                        "add",
                        "rm",
                        "commit",
                        "reset",
                        "restore",
                        # --- 3. Branching & Merging ---
                        "checkout",
                        "create_branch",
                        "delete_branch",
                        "list_branches",
                        "merge",
                        "abort_merge",
                        # --- 4. Conflict Resolution ---
                        "checkout_ours",
                        "checkout_theirs",
                        # --- 5. Syncing ---
                        "fetch",
                        "pull",
                        "push",
                        "push_force",
                        # --- 6. Advanced History ---
                        "cherry_pick",
                        "revert",
                        "reflog",
                        # --- 7. Stashing ---
                        "stash",
                        "stash_list",
                        "stash_pop",
                        "stash_apply",
                        "stash_drop",
                        # --- 8. Releases ---
                        "tag",
                        "push_tags",
                    ],
                ),
                ToolParameter(
                    name="target",
                    type="string",
                    description="Primary target (file, branch, commit hash, or tag).",
                    required=False,
                ),
                ToolParameter(
                    name="message",
                    type="string",
                    description="Commit message or stash name.",
                    required=False,
                ),
                ToolParameter(
                    name="extra_args",
                    type="string",
                    description="Optional extra arguments (e.g., '--no-verify' or specific file paths for diffs). Use with caution.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        op = kwargs.get("operation")
        target = kwargs.get("target")
        message = kwargs.get("message")
        extra_args = kwargs.get("extra_args", "")

        # Split extra_args safely to avoid shell injection
        extras = shlex.split(extra_args) if extra_args else []

        cmd = []

        # --- 1. Inspection ---
        if op == "status":
            cmd = ["git", "status"]
        elif op == "log":
            # Smart log: concise, graph, last 20
            cmd = ["git", "log", "-n", "20", "--graph", "--oneline", "--decorate"]
        elif op == "diff":
            cmd = ["git", "diff"] + ([target] if target else [])
        elif op == "show_file":
            if not target:
                return self._error("Target file path required.")
            cmd = ["git", "show", f"HEAD:{target}"]
        elif op == "blame":
            if not target:
                return self._error("Target file path required.")
            cmd = ["git", "blame", target]
        elif op == "ls_files":
            cmd = ["git", "ls-files"]
        elif op == "current_branch":
            cmd = ["git", "branch", "--show-current"]
        elif op == "remote_url":
            cmd = ["git", "remote", "get-url", "origin"]

        # --- 2. Staging & Committing ---
        elif op == "add":
            if not target:
                return self._error("Target file (or '.') required.")
            cmd = ["git", "add", target]
        elif op == "rm":
            if not target:
                return self._error("Target file required.")
            cmd = ["git", "rm", target]
        elif op == "commit":
            if not message:
                return self._error("Message required.")
            cmd = ["git", "commit", "-m", message]
        elif op == "reset":
            # Soft reset by default if no mode specified, or use extras
            cmd = ["git", "reset"] + extras + ([target] if target else [])
        elif op == "restore":
            if not target:
                return self._error("Target file required.")
            cmd = ["git", "restore", target]

        # --- 3. Branching & Merging ---
        elif op == "checkout":
            if not target:
                return self._error("Target branch required.")
            cmd = ["git", "checkout", target]
        elif op == "create_branch":
            if not target:
                return self._error("New branch name required.")
            cmd = ["git", "checkout", "-b", target]
        elif op == "delete_branch":
            if not target:
                return self._error("Branch name required.")
            cmd = [
                "git",
                "branch",
                "-D",
                target,
            ]  # Force delete to avoid agent stuck loop
        elif op == "list_branches":
            cmd = ["git", "branch", "-a"]
        elif op == "merge":
            if not target:
                return self._error("Target branch required.")
            cmd = ["git", "merge", target]
        elif op == "abort_merge":
            cmd = ["git", "merge", "--abort"]

        # --- 4. Conflict Resolution ---
        elif op == "checkout_ours":
            if not target:
                return self._error("Target file required.")
            cmd = ["git", "checkout", "--ours", target]
        elif op == "checkout_theirs":
            if not target:
                return self._error("Target file required.")
            cmd = ["git", "checkout", "--theirs", target]

        # --- 5. Syncing ---
        elif op == "fetch":
            cmd = ["git", "fetch", "--all"]
        elif op == "pull":
            cmd = ["git", "pull"]
        elif op == "push":
            cmd = ["git", "push"]
        elif op == "push_force":
            # Dangerous, but sometimes necessary for agents fixing their own history
            cmd = ["git", "push", "--force"]

        # --- 6. Advanced History ---
        elif op == "cherry_pick":
            if not target:
                return self._error("Commit hash required.")
            cmd = ["git", "cherry-pick", target]
        elif op == "revert":
            if not target:
                return self._error("Commit hash required.")
            cmd = ["git", "revert", target, "--no-edit"]
        elif op == "reflog":
            cmd = ["git", "reflog", "-n", "20"]

        # --- 7. Stashing ---
        elif op == "stash":
            cmd = ["git", "stash"]
            if message:
                cmd.extend(["save", message])
        elif op == "stash_list":
            cmd = ["git", "stash", "list"]
        elif op == "stash_pop":
            cmd = ["git", "stash", "pop"] + ([target] if target else [])
        elif op == "stash_apply":
            cmd = ["git", "stash", "apply"] + ([target] if target else [])
        elif op == "stash_drop":
            cmd = ["git", "stash", "drop"] + ([target] if target else [])

        # --- 8. Releases ---
        elif op == "tag":
            if not target:
                return self._error("Tag name required.")
            cmd = ["git", "tag", target]
            if message:
                cmd.extend(["-m", message])
        elif op == "push_tags":
            cmd = ["git", "push", "--tags"]

        else:
            return self._error(f"Unknown operation: {op}")

        # Execute
        return await self._run_command(cmd)

    async def _run_command(self, cmd: List[str]) -> Dict[str, Any]:
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            stdout_str = stdout.decode("utf-8", errors="replace").strip()
            stderr_str = stderr.decode("utf-8", errors="replace").strip()

            # Truncate output to protect LLM context
            if len(stdout_str) > self.MAX_OUTPUT_LENGTH:
                stdout_str = (
                    stdout_str[: self.MAX_OUTPUT_LENGTH]
                    + f"\n... [Output Truncated. Total: {len(stdout_str)} chars]"
                )

            # Git often prints status info to stderr even on success (e.g. 'Cloning into...')
            # We treat non-zero return codes as failures.
            if process.returncode != 0:
                return {
                    "success": False,
                    "output": stderr_str if stderr_str else stdout_str,
                    "return_code": process.returncode,
                }

            return {
                "success": True,
                "output": stdout_str if stdout_str else f"Success: {' '.join(cmd)}",
                "stderr_info": stderr_str,  # Sometimes helpful info is here even on success
            }

        except Exception as e:
            return self._error(f"System Error: {str(e)}")

    def _error(self, msg: str) -> Dict[str, Any]:
        return {"success": False, "output": f"Error: {msg}"}
