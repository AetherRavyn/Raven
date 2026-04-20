from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

from app.core.eval import EvalCase, EvaluationHarness
from app.core.models import IncomingRequest, ReplyTarget

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RegressionSuite:
    cases: list[EvalCase] = field(default_factory=list)

    @staticmethod
    def from_jsonl(path: str) -> "RegressionSuite":
        cases: list[EvalCase] = []
        p = Path(path)
        if not p.exists():
            return RegressionSuite()

        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            req = raw["request"]
            request = IncomingRequest(
                platform=req["platform"],
                user_id=req["user_id"],
                text=req["text"],
                reply_target=ReplyTarget(
                    platform=req["reply_target"]["platform"],
                    chat_id=req["reply_target"]["chat_id"],
                    reply_to_id=req["reply_target"].get("reply_to_id"),
                ),
                image_urls=req.get("image_urls"),
                voice_reply=req.get("voice_reply", False),
                conversation_id=req.get("conversation_id"),
            )
            cases.append(
                EvalCase(
                    name=raw["name"],
                    request=request,
                    expected_substrings=list(raw.get("expected_substrings", [])),
                    tool_expected=list(raw.get("tool_expected", [])),
                )
            )
        return RegressionSuite(cases=cases)


class RegressionRunner:
    def __init__(self, harness: EvaluationHarness | None = None) -> None:
        self.harness = harness or EvaluationHarness()

    async def run(self, runtime: Any, suite: RegressionSuite) -> dict[str, Any]:
        results = []
        for case in suite.cases:
            results.append(await self.harness.run_case(runtime, case))

        passed = sum(1 for result in results if result.success)
        summary = {
            "cases": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "results": [asdict(result) for result in results],
        }
        out_path = Path(self.harness.output_path).with_name("regression_summary.json")
        out_path.write_text(
            json.dumps(summary, ensure_ascii=True, indent=2), encoding="utf-8"
        )
        return summary
