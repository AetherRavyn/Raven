from __future__ import annotations

from app.core.policy import PolicyEngine
from app.tools.exectool import ExecTool
from app.tools.messagingtool import PlatformMessagingTool
from app.tools.weathertool import WeatherTool


def test_policy_blocks_risky_tools_without_permissions(monkeypatch) -> None:
    monkeypatch.setenv("TOOL_USER_PERMISSIONS", "")
    monkeypatch.setenv("TOOL_AGENT_PERMISSIONS", "")
    policy = PolicyEngine()

    tool = ExecTool.__new__(ExecTool)
    tool.get_capabilities = lambda: ExecTool.get_capabilities(tool)  # type: ignore[misc]
    decision = policy.evaluate(tool)
    assert decision.allowed is False
    assert decision.requires_confirmation is False or decision.permissions_missing


def test_policy_allows_safe_tools() -> None:
    policy = PolicyEngine()
    decision = policy.evaluate(WeatherTool())
    assert decision.allowed is True


def test_policy_blocks_missing_permission_tool(monkeypatch) -> None:
    monkeypatch.setenv("TOOL_USER_PERMISSIONS", "")
    monkeypatch.setenv("TOOL_AGENT_PERMISSIONS", "")
    policy = PolicyEngine()
    decision = policy.evaluate(PlatformMessagingTool())
    assert decision.allowed is False
    assert decision.permissions_missing or decision.requires_confirmation
