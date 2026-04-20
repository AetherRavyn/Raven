from __future__ import annotations

from app.core.metrics import (
    active_sessions,
    llm_calls_total,
    llm_duration_seconds,
    llm_latency_seconds,
    requests_blocked,
    requests_total,
    tool_calls_total,
)


def test_metrics_objects_are_available() -> None:
    assert requests_total is not None
    assert requests_blocked is not None
    assert tool_calls_total is not None
    assert llm_duration_seconds is not None
    assert llm_latency_seconds is llm_duration_seconds
    assert llm_calls_total is not None
    assert active_sessions is not None
