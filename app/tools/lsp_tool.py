from __future__ import annotations

import logging
from typing import Any, Dict

from app.core.lsp_client import LSPClientManager, SEVERITY_MAP, detect_language
from app.tools.base import BaseTool, ToolParameter, ToolSchema
from app.tools.__init__ import tool_error, tool_success

logger = logging.getLogger(__name__)


class LSPTool(BaseTool):
    def get_name(self) -> str:
        return "lsp_tool"

    def get_description(self) -> str:
        return (
            "Analyze source code files using LSP servers for semantic "
            "diagnostics, errors, and suggestions"
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action to perform",
                    required=True,
                    enum=["diagnose", "fix", "analyze", "status"],
                ),
                ToolParameter(
                    name="file_path",
                    type="string",
                    description="Path to the source file (required for diagnose/fix/analyze)",
                    required=False,
                ),
                ToolParameter(
                    name="language",
                    type="string",
                    description="Programming language (auto-detected from extension if omitted)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        action = str(kwargs.get("action", "")).strip()
        file_path = kwargs.get("file_path")
        language = kwargs.get("language")

        if action == "status":
            return await self._status()

        if not file_path:
            return tool_error("file_path is required for action: " + action, action=action)

        file_path = str(file_path)

        if not language:
            detected = detect_language(file_path)
            if not detected:
                return tool_error(
                    f"Could not detect language from file: {file_path}. "
                    "Specify language parameter manually.",
                    action=action,
                )
            language = detected
            logger.debug("Detected language %s for %s", language, file_path)

        language = str(language)

        client = await LSPClientManager.get_client(language)
        if client is None:
            return tool_error(
                f"No LSP server available for language: {language}. "
                f"Supported: {list(LSPClientManager._instances.keys())}",
                action=action,
            )

        if action == "diagnose":
            return await self._diagnose(client, file_path, language)
        elif action == "analyze":
            return await self._analyze(client, file_path, language)
        elif action == "fix":
            return await self._fix(client, file_path, language)
        else:
            return tool_error(f"Unknown action: {action}", action=action)

    async def _status(self) -> Dict[str, Any]:
        active = {}
        for lang, client in LSPClientManager._instances.items():
            active[lang] = {
                "server_command": client.server_command,
                "initialized": client._initialized,
                "open_files": list(client._diagnostics.keys()),
            }
        return tool_success(
            {
                "running_servers": active,
                "server_count": len(active),
            },
            action="status",
        )

    async def _diagnose(self, client: Any, file_path: str, language: str) -> Dict[str, Any]:
        await client.open_file(file_path, language)
        import asyncio

        await asyncio.sleep(0.5)
        diagnostics = await client.get_diagnostics(file_path)
        await client.close_file(file_path)

        formatted = []
        for d in diagnostics:
            formatted.append(
                {
                    "severity": SEVERITY_MAP.get(d.severity, "unknown"),
                    "message": d.message,
                    "line": d.line,
                    "column": d.column,
                    "end_line": d.end_line,
                    "end_column": d.end_column,
                    "source": d.source,
                    "code": d.code,
                }
            )

        return tool_success(
            {
                "diagnostics": formatted,
                "diagnostic_count": len(formatted),
                "file_path": file_path,
                "language": language,
            },
            action="diagnose",
        )

    async def _analyze(self, client: Any, file_path: str, language: str) -> Dict[str, Any]:
        await client.open_file(file_path, language)
        import asyncio

        await asyncio.sleep(0.5)
        diagnostics = await client.get_diagnostics(file_path)

        suggestions = []
        for d in diagnostics:
            if d.severity <= 2:
                actions = await client.get_code_actions(file_path, d.line, d.column)
                suggestions.append(
                    {
                        "diagnostic": {
                            "message": d.message,
                            "line": d.line,
                            "column": d.column,
                        },
                        "code_actions": actions,
                    }
                )

        await client.close_file(file_path)

        formatted_diags = []
        for d in diagnostics:
            formatted_diags.append(
                {
                    "severity": SEVERITY_MAP.get(d.severity, "unknown"),
                    "message": d.message,
                    "line": d.line,
                    "column": d.column,
                    "end_line": d.end_line,
                    "end_column": d.end_column,
                    "source": d.source,
                    "code": d.code,
                }
            )

        return tool_success(
            {
                "diagnostics": formatted_diags,
                "diagnostic_count": len(formatted_diags),
                "suggestions": suggestions,
                "suggestion_count": len(suggestions),
                "file_path": file_path,
                "language": language,
            },
            action="analyze",
        )

    async def _fix(self, client: Any, file_path: str, language: str) -> Dict[str, Any]:
        await client.open_file(file_path, language)
        import asyncio

        await asyncio.sleep(0.5)
        diagnostics = await client.get_diagnostics(file_path)

        applied = 0
        failed = 0
        for d in diagnostics:
            if d.severity <= 2:
                actions = await client.get_code_actions(file_path, d.line, d.column)
                for action in actions:
                    success = await client.execute_code_action(action)
                    if success:
                        applied += 1
                    else:
                        failed += 1

        await client.close_file(file_path)

        return tool_success(
            {
                "file_path": file_path,
                "language": language,
                "fixes_applied": applied,
                "fixes_failed": failed,
                "total_issues": len(diagnostics),
            },
            action="fix",
        )
