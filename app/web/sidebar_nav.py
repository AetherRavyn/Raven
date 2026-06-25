"""Single source of truth for the Hermes-style dashboard sidebar.

13 entries, ordered to mirror the Hermes Agent reference UI shipped
on 2026-06-21 (see docs/13-jarvis-friday-gap-analysis-2026-06.md,
v31 follow-on).  ``providers`` was added on 2026-06-22 so the
operator can paste API keys from the dashboard and have the agent
swarm route through them via HTTP (replacing the old CLI fallback).
Each entry is a ``NavEntry`` with:

- ``slug``  — the URL slug (``/page/<slug>``)
- ``label`` — display text in the sidebar
- ``group`` — ``"primary"`` (CHAT/SESSIONS/MODELS/LOGS) or
              ``"config"`` (everything else)
- ``hint``  — short subtitle shown in the sidebar tooltip

The list is intentionally a Python module rather than a Jinja-only
constant so the dashboard tests can iterate it (route-table snapshot,
sidebar-present assertions, etc.) without re-parsing HTML.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NavEntry:
    slug: str
    label: str
    group: str
    hint: str


# 13 entries — locked on 2026-06-21, +1 on 2026-06-22 for the
# Providers dashboard.  Do not reorder without a screenshot
# sign-off; the user has the muscle memory from the Hermes
# Agent reference UI.
NAV_ENTRIES: tuple[NavEntry, ...] = (
    NavEntry("chat", "CHAT", "primary", "Live conversation with the assistant"),
    NavEntry("sessions", "SESSIONS", "primary", "Per-user conversation history"),
    NavEntry("cowork", "COWORK", "primary", "Kimi/Claude-style folder sessions (plan, approve, diff)"),
    NavEntry("knowledge-graph", "KNOWLEDGE GRAPH", "primary", "HelixDB entity browser + graph visualization"),
    NavEntry("memory", "MEMORY", "primary", "Memory system: search, store, stats"),
    NavEntry("models", "MODELS", "primary", "Active LLM provider + model"),
    NavEntry("providers", "PROVIDERS", "primary", "API keys for every LLM / voice / search provider"),
    NavEntry("provider-manage", "MODEL SELECT", "primary", "Active provider, model, ranking, enable/disable"),
    NavEntry("learned-skills", "LEARNED SKILLS", "primary", "Auto-created skills + reinforcement learning"),
    NavEntry("personality", "PERSONALITY", "primary", "Emotional state, drift, values, relationship"),
    NavEntry("logs", "LOGS", "primary", "Audit timeline + event stream"),
    NavEntry("cron", "CRON", "config", "Scheduled jobs (toggle / run)"),
    NavEntry("skills", "SKILLS", "config", "Skill registry + learner"),
    NavEntry("plugins", "PLUGINS", "config", "Modular platform plugins"),
    NavEntry("modules", "A2A MODULES", "config", "Raven Protocol modules — discover, call, manage"),
    NavEntry("mcp", "MCP", "config", "Model Context Protocol servers"),
    NavEntry("channels", "CHANNELS", "config", "Telegram / Discord / Slack / Matrix"),
    NavEntry("webhooks", "WEBHOOKS", "config", "Outgoing HTTP hooks"),
    NavEntry("pairing", "PAIRING", "config", "DM pairing codes"),
    NavEntry("profiles", "PROFILES", "config", "Per-user preferences"),
)


def nav_entries() -> tuple[NavEntry, ...]:
    """Return the 12 nav entries (read-only)."""
    return NAV_ENTRIES


def nav_slugs() -> tuple[str, ...]:
    """Return just the slugs — used by the route-table snapshot test."""
    return tuple(e.slug for e in NAV_ENTRIES)


def find_entry(slug: str) -> NavEntry | None:
    """Return the entry for ``slug`` or ``None`` if not found."""
    for entry in NAV_ENTRIES:
        if entry.slug == slug:
            return entry
    return None
