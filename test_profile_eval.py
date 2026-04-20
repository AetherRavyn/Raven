from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.core.bootstrapper import Bootstrapper
from app.core.eval import EvalCase, EvaluationHarness
from app.core.models import IncomingRequest, ReplyTarget


class _RuntimeStub:
    def __init__(self) -> None:
        self.botsignal = SimpleNamespace(send_text=self._send_text)

    async def _send_text(self, *args, **kwargs):
        return None

    async def execute_turn(self, request):
        await self.botsignal.send_text(
            request.reply_target,
            "Hello Alex, concise answer.",
            source_kind="prompt",
            tool_traces=[],
        )


def test_bootstrapper_includes_profile_summary(tmp_path, monkeypatch) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "SOUL.md").write_text("Soul", encoding="utf-8")
    (ws / "AGENTS.md").write_text("Agents", encoding="utf-8")
    (ws / "TOOLS.md").write_text("Tools", encoding="utf-8")
    bootstrapper = Bootstrapper(str(ws))

    from app.core.user_profile import UserProfileStore

    store = UserProfileStore(str(ws))
    store.update_from_text("u1", "My name is Alex. I prefer concise answers.")

    prompt = bootstrapper.build_system_prompt(query="preferences", user_id="u1")
    assert "User Profile" in prompt
    assert "concise" in prompt


def test_bootstrapper_includes_workspace_graph(tmp_path) -> None:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "SOUL.md").write_text("Soul", encoding="utf-8")
    (ws / "AGENTS.md").write_text("Agents", encoding="utf-8")
    (ws / "TOOLS.md").write_text("Tools", encoding="utf-8")
    bootstrapper = Bootstrapper(str(ws))

    from app.core.user_profile import UserProfileStore

    store = UserProfileStore(str(ws))
    store.update_from_text("u1", "My name is Alex. I prefer concise answers.")

    prompt = bootstrapper.build_system_prompt(query="Alex concise", user_id="u1")
    assert "Workspace Graph" in prompt


@pytest.mark.asyncio
async def test_eval_harness_writes_summary(tmp_path) -> None:
    runtime = _RuntimeStub()
    out = tmp_path / "results.jsonl"
    harness = EvaluationHarness(output_path=str(out))
    request = IncomingRequest(
        platform="web",
        user_id="u1",
        text="say hello",
        reply_target=ReplyTarget(platform="web", chat_id="u1"),
    )
    case = EvalCase(
        name="hello", request=request, expected_substrings=["Alex", "concise"]
    )
    result = await harness.run_case(runtime, case)
    assert result.success is True
    summary = json.loads(
        (out.with_name("eval_summary.json")).read_text(encoding="utf-8")
    )
    assert summary["runs"] == 1
    assert summary["successes"] == 1
