"""Cowork manager — singleton that owns the active worker + bus subscription.

The HTTP endpoints, the CLI, and the dashboard all go through
:meth:`CoworkManager.dispatch` to keep state coherent.  The
manager:

  * owns the long-lived :class:`InProcBus` subscription that
    re-broadcasts cowork events to the dashboard SSE endpoint
  * owns one :class:`CoworkWorker` per active session
  * runs the worker in an :func:`asyncio.create_task` so the
    HTTP layer doesn't block on plan execution
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from app.cowork.plan import StepStatus
from app.cowork.session import (
    CoworkEvent,
    CoworkSession,
    SessionState,
)
from app.cowork.store import CoworkStore
from app.cowork.worker import CoworkWorker
from app.cowork.workspace import AccessMode

logger = logging.getLogger(__name__)


class CoworkManager:
    """Singleton owning the active worker + state."""

    def __init__(self, store: CoworkStore | None = None) -> None:
        from app.core.inproc_bus import get_inproc_bus

        self._store = store or CoworkStore()
        self._bus = get_inproc_bus()
        self._worker: CoworkWorker | None = None
        self._worker_task: asyncio.Task[None] | None = None
        # Live event ring buffer for SSE consumers.
        self._live: list[CoworkEvent] = []
        self._live_max = 200

    @property
    def store(self) -> CoworkStore:
        return self._store

    @property
    def worker(self) -> CoworkWorker | None:
        return self._worker

    @property
    def live_events(self) -> list[CoworkEvent]:
        return list(self._live)

    def append_live(self, event: CoworkEvent) -> None:
        self._live.append(event)
        if len(self._live) > self._live_max:
            self._live = self._live[-self._live_max :]

    # ── workspace ops ────────────────────────────────────────────

    def list_workspaces(self) -> list[dict[str, Any]]:
        return [w.to_dict() for w in self._store.workspaces.list()]

    def add_workspace(
        self,
        name: str,
        path: str,
        access: str = "rw",
        deny_globs: list[str] | None = None,
    ) -> dict[str, Any]:
        ws = self._store.workspaces.add(
            name=name,
            path=path,
            access=AccessMode(access),
            deny_globs=deny_globs,
        )
        return ws.to_dict()

    def remove_workspace(self, workspace_id: str) -> bool:
        return self._store.workspaces.remove(workspace_id)

    # ── session ops ──────────────────────────────────────────────

    def list_sessions(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self._store.sessions.list()]

    def get_session(self, session_id: str) -> Optional[dict[str, Any]]:
        sess = self._store.sessions.get(session_id)
        return sess.to_dict() if sess else None

    def get_active_session(self) -> Optional[dict[str, Any]]:
        sess = self._store.sessions.get_active()
        return sess.to_dict() if sess else None

    async def start_session(
        self,
        workspace_id: str,
        goal: str,
        *,
        auto_approve_low_risk: bool = False,
        strategy: str = "default",
    ) -> dict[str, Any]:
        ws = self._store.workspaces.get(workspace_id)
        if ws is None:
            raise ValueError(f"workspace not found: {workspace_id}")
        self._store.workspaces.touch(workspace_id)
        session = CoworkSession(
            id="",
            workspace_id=workspace_id,
            goal=goal,
            state=SessionState.IDLE,
        )
        self._store.sessions.upsert(session)
        self._store.set_active(session.id)
        # Plan + execute
        self._worker = CoworkWorker(store=self._store, bus=self._bus)
        plan = await self._worker.propose_plan(session, strategy=strategy)
        if auto_approve_low_risk:
            plan.approved_all = True
            for s in plan.steps:
                if s.risk == "low":
                    s.status = StepStatus.APPROVED
            self._store.sessions.upsert(session)
        self._worker.attach(session)
        self._worker_task = asyncio.create_task(self._worker.run())
        return session.to_dict()

    def pause_session(self, session_id: str) -> bool:
        if self._worker is None or self._worker._session is None:
            return False
        if self._worker._session.id != session_id:
            return False
        self._worker.request_pause()
        return True

    def resume_session(self, session_id: str) -> bool:
        if self._worker is None or self._worker._session is None:
            return False
        if self._worker._session.id != session_id:
            return False
        self._worker.request_resume()
        return True

    def stop_session(self, session_id: str) -> bool:
        if self._worker is None or self._worker._session is None:
            return False
        if self._worker._session.id != session_id:
            return False
        self._worker.request_stop()
        return True

    def approve_step(self, session_id: str, step_id: str) -> bool:
        if (
            self._worker is None
            or self._worker._session is None
            or self._worker._session.id != session_id
        ):
            return False
        step = self._worker._session.plan.step(step_id) if self._worker._session.plan else None
        if step is None:
            return False
        step.status = StepStatus.APPROVED
        self._store.sessions.upsert(self._worker._session)
        self._worker.approve_step(step_id)
        return True

    def reject_step(self, session_id: str, step_id: str, reason: str = "") -> bool:
        if (
            self._worker is None
            or self._worker._session is None
            or self._worker._session.id != session_id
        ):
            return False
        step = self._worker._session.plan.step(step_id) if self._worker._session.plan else None
        if step is None:
            return False
        step.status = StepStatus.REJECTED
        step.error = reason
        self._store.sessions.upsert(self._worker._session)
        self._worker.reject_step(step_id, reason)
        return True

    def approve_all(self, session_id: str) -> bool:
        if (
            self._worker is None
            or self._worker._session is None
            or self._worker._session.id != session_id
            or self._worker._session.plan is None
        ):
            return False
        self._worker._session.plan.approved_all = True
        for s in self._worker._session.plan.steps:
            if s.status.value in {"pending", "awaiting_approval"}:
                s.status = StepStatus.APPROVED
        self._store.sessions.upsert(self._worker._session)
        # Unblock the current awaiting step (if any).
        if self._worker._current_step_id:
            self._worker.approve_step(self._worker._current_step_id)
        return True

    def read_events(self, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._store.read_events(session_id, limit=limit)]


_MANAGER: CoworkManager | None = None


def get_cowork_manager() -> CoworkManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = CoworkManager()
    return _MANAGER
