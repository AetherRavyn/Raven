from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.eval import EvalCase, EvaluationHarness
from app.core.metrics import llm_calls_total, llm_latency_seconds
from app.core.models import IncomingRequest, ReplyTarget


class _RuntimeStub:
    def __init__(self) -> None:
        self.botsignal = SimpleNamespace(send_text=self._send_text)

    async def _send_text(self, *args, **kwargs):
        return None

    async def execute_turn(self, request):
        await self.botsignal.send_text(
            request.reply_target,
            "tool output ok",
            source_kind="prompt",
            tool_traces=[],
        )


def test_metrics_aliases_exist() -> None:
    assert llm_calls_total is not None
    assert llm_latency_seconds is not None


@pytest.mark.asyncio
async def test_eval_harness_runs_case(tmp_path):
    runtime = _RuntimeStub()
    harness = EvaluationHarness(output_path=str(tmp_path / "eval.jsonl"))
    request = IncomingRequest(
        platform="web",
        user_id="u1",
        text="say ok",
        reply_target=ReplyTarget(platform="web", chat_id="u1"),
    )
    case = EvalCase(name="simple", request=request, expected_substrings=["ok"])
    result = await harness.run_case(runtime, case)
    assert result.success is True
    assert result.latency_ms >= 0
