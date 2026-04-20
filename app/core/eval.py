from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from app.core.models import IncomingRequest

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EvalCase:
    name: str
    request: IncomingRequest
    expected_substrings: list[str] = field(default_factory=list)
    tool_expected: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EvalResult:
    name: str
    success: bool
    latency_ms: float
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    tool_names: list[str] = field(default_factory=list)
    answer_text: str = ""


class EvaluationHarness:
    def __init__(self, output_path: str = "workspace/eval_results.jsonl") -> None:
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.summary_path = self.output_path.with_name("eval_summary.json")

    @staticmethod
    def _match(expected: list[str], text: str) -> tuple[list[str], list[str]]:
        matched: list[str] = []
        missing: list[str] = []
        lowered = text.lower()
        for item in expected:
            if item.lower() in lowered:
                matched.append(item)
            else:
                missing.append(item)
        return matched, missing

    async def run_case(self, runtime: Any, case: EvalCase) -> EvalResult:
        start = time.perf_counter()
        captured: list[str] = []
        tool_names: list[str] = []

        original_send = runtime.botsignal.send_text

        async def _capture_send(target, text, source_kind=None, tool_traces=None):
            captured.append(text or "")
            if tool_traces:
                for trace in tool_traces:
                    if trace.tool_name not in tool_names:
                        tool_names.append(trace.tool_name)
            return await original_send(
                target, text, source_kind=source_kind, tool_traces=tool_traces
            )

        runtime.botsignal.send_text = _capture_send
        try:
            await runtime.execute_turn(case.request)
        finally:
            runtime.botsignal.send_text = original_send

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        answer_text = captured[-1] if captured else ""
        matched, missing = self._match(case.expected_substrings, answer_text)
        success = not missing
        if case.tool_expected:
            tool_lower = {name.lower() for name in tool_names}
            if not set(name.lower() for name in case.tool_expected).issubset(
                tool_lower
            ):
                success = False
                for tool in case.tool_expected:
                    if tool.lower() not in tool_lower and tool not in missing:
                        missing.append(tool)

        result = EvalResult(
            name=case.name,
            success=success,
            latency_ms=round(elapsed_ms, 2),
            matched=matched,
            missing=missing,
            tool_names=tool_names,
            answer_text=answer_text,
        )
        with self.output_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(result), ensure_ascii=True) + "\n")

        self._write_summary(result)
        return result

    def _write_summary(self, result: EvalResult) -> None:
        try:
            existing: dict[str, Any] = {}
            if self.summary_path.exists():
                existing = json.loads(self.summary_path.read_text(encoding="utf-8"))
            runs = int(existing.get("runs", 0)) + 1
            successes = int(existing.get("successes", 0)) + (1 if result.success else 0)
            avg_latency = float(existing.get("avg_latency_ms", 0.0))
            new_avg = ((avg_latency * (runs - 1)) + result.latency_ms) / runs
            data = {
                "runs": runs,
                "successes": successes,
                "success_rate": round(successes / runs if runs else 0.0, 3),
                "avg_latency_ms": round(new_avg, 2),
                "last_case": result.name,
                "last_success": result.success,
            }
            self.summary_path.write_text(
                json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.debug("Failed to write eval summary: %s", exc)
