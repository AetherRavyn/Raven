"""Batch Processing Tool — Run agent across many prompts in parallel.

Agents use this to generate training data, run evaluations,
or process multiple workloads simultaneously.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class BatchTool(BaseTool):
    """Run the agent across many prompts in parallel for training/evaluation."""

    group = "system"

    def get_name(self) -> str:
        return "batch"

    def get_description(self) -> str:
        return (
            "Runs the agent across multiple prompts in parallel. "
            "Supports actions: 'run' (process prompts and save to JSONL), "
            "'compress' (convert session logs into training examples), "
            "'status' (list completed batch outputs)."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Operation: run, compress, status",
                    required=True,
                    enum=["run", "compress", "status"],
                ),
                ToolParameter(
                    name="prompts",
                    type="string",
                    description="JSON array of prompt strings (required for run)",
                    required=False,
                ),
                ToolParameter(
                    name="max_concurrent",
                    type="integer",
                    description="Max concurrent executions (default 3)",
                    required=False,
                ),
                ToolParameter(
                    name="output_format",
                    type="string",
                    description="Output format: sharegpt, jsonl (default sharegpt)",
                    required=False,
                    enum=["sharegpt", "jsonl"],
                ),
                ToolParameter(
                    name="session_ids",
                    type="string",
                    description="JSON array of session IDs to compress (required for compress)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> dict[str, Any]:
        action = kwargs.get("action", "")
        prompts_raw = kwargs.get("prompts", "[]")
        max_concurrent = int(kwargs.get("max_concurrent", 3))
        output_format = kwargs.get("output_format", "sharegpt")
        session_ids_raw = kwargs.get("session_ids", "[]")

        try:
            if action == "run":
                return await self._run_batch(prompts_raw, max_concurrent, output_format)
            elif action == "compress":
                return await self._compress(session_ids_raw)
            elif action == "status":
                return self._list_outputs()
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        except Exception as e:
            logger.exception("Batch tool failed")
            return {"success": False, "error": str(e)}

    async def _run_batch(
        self, prompts_raw: str, max_concurrent: int, output_format: str
    ) -> dict[str, Any]:
        try:
            prompts = json.loads(prompts_raw)
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"Invalid prompts JSON: {e}"}

        if not isinstance(prompts, list) or not prompts:
            return {"success": False, "error": "prompts must be a non-empty JSON array of strings"}

        from app.core.batch_processor import get_batch_processor

        processor = get_batch_processor()
        orchestrator = self._get_orchestrator()

        result = await processor.process_batch(
            prompts=prompts,
            orchestrator=orchestrator,
            max_concurrent=max_concurrent,
            output_format=output_format,
        )
        return result

    async def _compress(self, session_ids_raw: str) -> dict[str, Any]:
        try:
            session_ids = json.loads(session_ids_raw)
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"Invalid session_ids JSON: {e}"}

        if not isinstance(session_ids, list) or not session_ids:
            return {"success": False, "error": "session_ids must be a non-empty JSON array"}

        from app.core.training_data import TrajectoryCompressor

        compressor = TrajectoryCompressor()
        results = []
        for sid in session_ids:
            try:
                from app.core.session import SessionManager

                mgr = SessionManager()
                messages = mgr.load_session(sid)
                example = compressor.compress_session(sid, messages)
                results.append(example)
            except Exception as e:
                results.append({"session_id": sid, "error": str(e)[:200]})

        return {
            "success": True,
            "compressed": len(results),
            "examples": results,
        }

    def _list_outputs(self) -> dict[str, Any]:
        from pathlib import Path

        from app.settings.config import Config

        output_dir = Path(Config.MEMORY_ROOT) / "batch_output"
        if not output_dir.exists():
            return {"success": True, "outputs": [], "message": "No batch outputs found"}

        files = []
        for f in sorted(output_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
            files.append(
                {
                    "file": f.name,
                    "size": f.stat().st_size,
                    "modified": f.stat().st_mtime,
                }
            )
        return {"success": True, "outputs": files, "directory": str(output_dir)}

    def _get_orchestrator(self) -> Any:
        """Find the orchestrator instance from the runtime context."""
        try:
            from app.core.orchestrator import get_orchestrator

            return get_orchestrator()
        except Exception:
            pass
        raise RuntimeError("Cannot resolve orchestrator for batch processing")
