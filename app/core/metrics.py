# app/core/metrics.py
"""Prometheus metrics for SARAS observability."""

from prometheus_client import Counter, Gauge, Histogram

requests_total = Counter(
    "saras_requests_total",
    "Total requests received",
    ["platform", "source_kind"],
)

requests_blocked = Counter(
    "saras_requests_blocked_total",
    "Requests blocked by security guard or rate limiter",
    ["reason"],
)

llm_duration_seconds = Histogram(
    "saras_llm_duration_seconds",
    "LLM call latency in seconds",
    ["provider", "model"],
)

tool_calls_total = Counter(
    "saras_tool_calls_total",
    "Tool invocations",
    ["tool_name", "success"],
)

active_sessions = Gauge(
    "saras_active_sessions",
    "Number of active user sessions",
)
