"""Batch Processing — run agent across many prompts in parallel.

Generates structured ShareGPT-format trajectory data for training/evaluation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BatchJob:
    """A single batch processing job."""
    job_id: str
    prompt: str
    status: str = "pending"
    result: str = ""
    trajectory: list[dict[str, Any]] = field(default_factory=list)
    started_at: float = 0.0
    completed_at: float = 0.0
    error: str = ""


class BatchProcessor:
    """Run the agent across many prompts in parallel for training data generation."""

    def __init__(self, workspace_dir: str = "workspace") -> None:
        from app.settings.config import Config
        self._workspace = workspace_dir or Config.MEMORY_ROOT
        self._output_dir = Path(self._workspace) / "batch_output"
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._max_concurrent = 3

    async def process_batch(
        self,
        prompts: list[str],
        orchestrator: Any = None,
        max_concurrent: int = 3,
        output_format: str = "sharegpt",
    ) -> dict[str, Any]:
        """Process a batch of prompts in parallel."""
        self._max_concurrent = max_concurrent

        semaphore = asyncio.Semaphore(max_concurrent)
        jobs = [BatchJob(job_id=f"job_{i}", prompt=p) for i, p in enumerate(prompts)]

        async def process_one(job: BatchJob) -> BatchJob:
            async with semaphore:
                job.status = "running"
                job.started_at = time.time()
                try:
                    from app.core.models import IncomingRequest, ReplyTarget
                    request = IncomingRequest(
                        text=job.prompt,
                        platform="batch",
                        user_id="batch_user",
                        reply_target=ReplyTarget(platform="batch", chat_id="batch"),
                    )
                    result = await orchestrator.handle_request(request)
                    job.result = result.get("text", "") if isinstance(result, dict) else str(result)
                    job.trajectory.append({"role": "user", "content": job.prompt})
                    job.trajectory.append({"role": "assistant", "content": job.result})
                    job.status = "completed"
                except Exception as e:
                    job.status = "failed"
                    job.error = str(e)[:200]
                finally:
                    job.completed_at = time.time()
                return job

        # Run all jobs in parallel
        results = await asyncio.gather(*[process_one(j) for j in jobs])

        # Format output
        output = self._format_output(list(results), output_format)

        # Save output
        timestamp = int(time.time())
        output_path = self._output_dir / f"batch_{timestamp}.jsonl"
        with open(output_path, "w", encoding="utf-8") as f:
            for item in output:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        completed = sum(1 for j in results if j.status == "completed")
        failed = sum(1 for j in results if j.status == "failed")
        avg_time = sum(j.completed_at - j.started_at for j in results) / max(len(results), 1)

        return {
            "success": True,
            "output_path": str(output_path),
            "total": len(prompts),
            "completed": completed,
            "failed": failed,
            "avg_time_per_prompt": round(avg_time, 2),
            "output_format": output_format,
        }

    def _format_output(self, jobs: list[BatchJob], format: str) -> list[dict]:
        """Format batch results."""
        if format == "sharegpt":
            return [
                {
                    "conversations": [
                        {"from": "human", "value": j.prompt},
                        {"from": "gpt", "value": j.result},
                    ],
                    "metadata": {
                        "job_id": j.job_id,
                        "status": j.status,
                        "time_seconds": round(j.completed_at - j.started_at, 2),
                    },
                }
                for j in jobs if j.status == "completed"
            ]
        elif format == "jsonl":
            return [
                {"prompt": j.prompt, "response": j.result, "status": j.status}
                for j in jobs
            ]
        return [{"prompt": j.prompt, "response": j.result} for j in jobs]


# Singleton
_processor: BatchProcessor | None = None


def get_batch_processor() -> BatchProcessor:
    global _processor
    if _processor is None:
        _processor = BatchProcessor()
    return _processor
