from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.core.eval import EvalCase, EvaluationHarness
from app.core.models import IncomingRequest, ReplyTarget
from app.core.regression import RegressionRunner, RegressionSuite


class _RuntimeStub:
    def __init__(self) -> None:
        self.botsignal = SimpleNamespace(send_text=self._send_text)

    async def _send_text(self, *args, **kwargs):
        return None

    async def execute_turn(self, request):
        await self.botsignal.send_text(
            request.reply_target,
            "hello there",
            source_kind="prompt",
            tool_traces=[],
        )


def test_regression_suite_loads_jsonl(tmp_path) -> None:
    suite_path = tmp_path / "suite.jsonl"
    suite_path.write_text(
        json.dumps(
            {
                "name": "hello",
                "request": {
                    "platform": "web",
                    "user_id": "u1",
                    "text": "hello",
                    "reply_target": {"platform": "web", "chat_id": "u1"},
                },
                "expected_substrings": ["hello"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    suite = RegressionSuite.from_jsonl(str(suite_path))
    assert len(suite.cases) == 1


@pytest.mark.asyncio
async def test_regression_runner_writes_summary(tmp_path) -> None:
    runtime = _RuntimeStub()
    harness = EvaluationHarness(output_path=str(tmp_path / "eval.jsonl"))
    runner = RegressionRunner(harness=harness)
    request = IncomingRequest(
        platform="web",
        user_id="u1",
        text="hello",
        reply_target=ReplyTarget(platform="web", chat_id="u1"),
    )
    suite = RegressionSuite(
        cases=[EvalCase(name="hello", request=request, expected_substrings=["hello"])]
    )
    summary = await runner.run(runtime, suite)
    assert summary["cases"] == 1
    assert summary["passed"] == 1
    assert (tmp_path / "regression_summary.json").exists()
