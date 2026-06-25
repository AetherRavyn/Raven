"""RAVEN Cowork — Kimi/Claude-cowork-style long-running autonomous work on a folder.

Public surface
--------------
- :class:`Workspace`          — a user-granted folder + access mode (ro/rw)
- :class:`Plan` / :class:`PlanStep` — multi-step plan generated from a goal
- :class:`CoworkSession`      — long-lived session (IDLE → PLANNING →
                                 AWAITING_APPROVAL → EXECUTING → DONE/STOPPED)
- :class:`CoworkWorker`       — runs the plan step-by-step with pause / resume
- :class:`Diff`               — before/after file diff

Persistence
-----------
Everything is JSON-on-disk under ``workspace/cowork/``:

    workspace/cowork/
      workspaces.json
      sessions/{session_id}/
        meta.json       — session state + current plan
        events.jsonl    — event log (audit + UI stream)
        diffs/{step_id}/{file}.json  — per-file diff
        snapshots/      — pre-change backups (for undo)

The session is a coroutine that can be ``await``-ed from the runtime
or polled from the dashboard.  Progress events are emitted on
:data:`COWORK_TOPIC` via :class:`InProcBus` so the dashboard and
Tauri shell can subscribe without coupling to the worker.
"""
from __future__ import annotations

import logging

from app.cowork.workspace import Workspace, WorkspaceStore, AccessMode
from app.cowork.plan import Plan, PlanStep, StepStatus
from app.cowork.diff import Diff, compute_file_diff
from app.cowork.planner import (
    ALLOWED_ACTIONS,
    LLMPlanner,
    PlannerFn,
    PlannerStrategy,
    RulePlanner,
    parse_plan_from_json,
    register_planner,
    resolve_planner,
)
from app.cowork.session import (
    CoworkSession,
    SessionState,
    SessionStore,
    COWORK_TOPIC,
    CoworkEvent,
)
from app.cowork.worker import CoworkWorker
from app.cowork.store import CoworkStore
from app.cowork.manager import CoworkManager, get_cowork_manager

logger = logging.getLogger(__name__)

__all__ = [
    "Workspace",
    "WorkspaceStore",
    "AccessMode",
    "Plan",
    "PlanStep",
    "StepStatus",
    "Diff",
    "compute_file_diff",
    "ALLOWED_ACTIONS",
    "RulePlanner",
    "LLMPlanner",
    "PlannerStrategy",
    "PlannerFn",
    "parse_plan_from_json",
    "register_planner",
    "resolve_planner",
    "CoworkSession",
    "SessionState",
    "SessionStore",
    "CoworkWorker",
    "CoworkStore",
    "CoworkManager",
    "COWORK_TOPIC",
    "CoworkEvent",
    "get_cowork_store",
    "get_cowork_manager",
]


def get_cowork_store(workspace_dir: str | None = None) -> CoworkStore:
    """Module-level singleton accessor (same pattern as the rest of RAVEN)."""
    return CoworkStore(workspace_dir)
