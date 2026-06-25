"""Cowork persistence façade — bundles WorkspaceStore + SessionStore.

A single :class:`CoworkStore` is the only object the rest of the
app needs to know about.  The HTTP endpoints and the worker
both go through this.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from app.cowork.workspace import WorkspaceStore
from app.cowork.session import SessionStore, CoworkEvent

logger = logging.getLogger(__name__)


class CoworkStore:
    """Top-level facade.  One instance per process."""

    def __init__(self, workspace_dir: str | Path | None = None) -> None:
        self.workspaces = WorkspaceStore(workspace_dir)
        self.sessions = SessionStore(workspace_dir)
        # Track the current active session (the worker enforces
        # one-at-a-time, but multiple sessions can be in history).
        self._active_session_id: Optional[str] = None

    # ── active session tracking ───────────────────────────────────

    @property
    def active_session_id(self) -> Optional[str]:
        return self._active_session_id

    def set_active(self, session_id: Optional[str]) -> None:
        self._active_session_id = session_id

    # ── event log (per-session JSONL) ─────────────────────────────

    def append_event(self, event: CoworkEvent) -> None:
        """Append an event to the session's JSONL log.

        The dashboard SSE endpoint and Tauri shell subscribe to
        :data:`COWORK_TOPIC` for live events; the JSONL is the
        cold-path audit + replay.
        """
        path = self.sessions.events_dir(event.session_id) / "events.jsonl"
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("Failed to append event: %s", exc)

    def read_events(self, session_id: str, limit: int = 200) -> list[CoworkEvent]:
        path = self.sessions.events_dir(session_id) / "events.jsonl"
        if not path.exists():
            return []
        out: list[CoworkEvent] = []
        try:
            with path.open("r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return []
        for line in lines[-limit:]:
            try:
                out.append(CoworkEvent.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError):
                continue
        return out
