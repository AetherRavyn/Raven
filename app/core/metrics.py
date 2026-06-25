# app/core/metrics.py
"""Prometheus metrics for RAVEN observability."""

from prometheus_client import Counter, Gauge, Histogram

requests_total = Counter(
    "raven_requests_total",
    "Total requests received",
    ["platform", "source_kind"],
)

requests_blocked = Counter(
    "raven_requests_blocked_total",
    "Requests blocked by security guard or rate limiter",
    ["reason"],
)

llm_duration_seconds = Histogram(
    "raven_llm_duration_seconds",
    "LLM call latency in seconds",
    ["provider", "model"],
)

llm_calls_total = Counter(
    "raven_llm_calls_total",
    "LLM API calls",
    ["provider", "model"],
)

# Backwards-compatible alias used by the dashboard page.
llm_latency_seconds = llm_duration_seconds

tool_calls_total = Counter(
    "raven_tool_calls_total",
    "Tool invocations",
    ["tool_name", "success"],
)

active_sessions = Gauge(
    "raven_active_sessions",
    "Number of active user sessions",
)
