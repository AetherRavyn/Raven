"""Cowork session lifecycle + InProcBus event topic.

State machine
-------------
::

    IDLE ──propose_plan──> PLANNING ──plan_ready──> AWAITING_APPROVAL
       ^                                                │
       │                                                ├──approve_all──> APPROVED
       │                                                ├──step approve──> APPROVED (per step)
       │                                                │
       │                                                ▼
       └─────────done/STOPPED/FAILED─────────── EXECUTING

The session is owned by :class:`CoworkWorker` which moves the
state forward; the session itself is a passive value object so
the dashboard can render it without owning the coroutine.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from app.cowork.plan import Plan

logger = logging.getLogger(__name__)


# ── Constants ──────────────────────────────────────────────────────

# Single InProcBus topic for all cowork events.  Payloads are
# :class:`CoworkEvent` dicts.  Subscribers: the dashboard SSE
# endpoint, the Tauri shell, audit bridge.
COWORK_TOPIC = "cowork.events"


class SessionState(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"
    STOPPED = "stopped"


# ── Event ──────────────────────────────────────────────────────────


@dataclass(slots=True)
class CoworkEvent:
    """One event in a cowork session's timeline.

    ``kind`` is the discriminator.  Recognised kinds:

    - ``session_started``
    - ``plan_proposed``
    - ``plan_approved``
    - ``step_started``     (payload: step_id, title, action)
    - ``step_approved``    (payload: step_id)
    - ``step_rejected``    (payload: step_id, reason)
    - ``step_done``        (payload: step_id, result, stats)
    - ``step_failed``      (payload: step_id, error)
    - ``session_paused``
    - ``session_resumed``
    - ``session_stopped``
    - ``session_done``
    - ``session_failed``   (payload: error)
    - ``diff_ready``       (payload: step_id, path, stats)
    - ``approval_needed``  (high-risk step waiting)
    """

    session_id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CoworkEvent":
        return cls(
            session_id=raw["session_id"],
            kind=raw["kind"],
            payload=raw.get("payload", {}),
            ts=raw.get("ts", time.time()),
        )


# ── Session value object ──────────────────────────────────────────


@dataclass(slots=True)
class CoworkSession:
    id: str
    workspace_id: str
    goal: str
    state: SessionState = SessionState.IDLE
    plan: Optional[Plan] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    error: str = ""
    # Index of the next step to consider for execution — lets the
    # worker resume after pause/stop without re-running done steps.
    cursor: int = 0

    def __post_init__(self) -> None:
        if not self.id:
            self.id = uuid.uuid4().hex[:12]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        d["plan"] = self.plan.to_dict() if self.plan else None
        return d

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "CoworkSession":
        plan_raw = raw.get("plan")
        return cls(
            id=raw["id"],
            workspace_id=raw["workspace_id"],
            goal=raw["goal"],
            state=SessionState(raw.get("state", "idle")),
            plan=Plan.from_dict(plan_raw) if plan_raw else None,
            created_at=raw.get("created_at", time.time()),
            updated_at=raw.get("updated_at", time.time()),
            error=raw.get("error", ""),
            cursor=raw.get("cursor", 0),
        )


# ── Persistence ───────────────────────────────────────────────────


class SessionStore:
    """JSON-on-disk persistence for cowork sessions."""

    def __init__(self, workspace_dir: str | Path | None = None) -> None:
        self._root = Path(workspace_dir or self._default_workspace())
        self._root.mkdir(parents=True, exist_ok=True)
        self._sessions_dir = self._root / "cowork" / "sessions"
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        self._items: dict[str, CoworkSession] = {}
        self._load()

    @staticmethod
    def _default_workspace() -> str:
        for candidate in ("workspace", "data", "."):
            p = Path(candidate)
            if p.is_dir():
                return str(p.resolve())
        return str(Path.cwd())

    def list(self) -> list[CoworkSession]:
        return sorted(self._items.values(), key=lambda s: s.updated_at, reverse=True)

    def get(self, session_id: str) -> Optional[CoworkSession]:
        return self._items.get(session_id)

    def get_active(self) -> Optional[CoworkSession]:
        for s in self._items.values():
            if s.state in {
                SessionState.EXECUTING,
                SessionState.AWAITING_APPROVAL,
                SessionState.PLANNING,
                SessionState.APPROVED,
                SessionState.PAUSED,
            }:
                return s
        return None

    def upsert(self, session: CoworkSession) -> None:
        session.updated_at = time.time()
        self._items[session.id] = session
        self._save(session)

    def delete(self, session_id: str) -> bool:
        if session_id in self._items:
            del self._items[session_id]
            try:
                (self._sessions_dir / f"{session_id}.json").unlink(missing_ok=True)
                (self._sessions_dir / session_id).rmdir()  # events dir
            except OSError:
                pass
            return True
        return False

    def events_dir(self, session_id: str) -> Path:
        d = self._sessions_dir / session_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ── persistence ───────────────────────────────────────────────

    def _load(self) -> None:
        for path in self._sessions_dir.glob("*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                sess = CoworkSession.from_dict(raw)
                self._items[sess.id] = sess
            except (json.JSONDecodeError, OSError, KeyError) as exc:
                logger.warning("Failed to load session %s: %s", path, exc)

    def _save(self, session: CoworkSession) -> None:
        try:
            self._sessions_dir.mkdir(parents=True, exist_ok=True)
            (self._sessions_dir / f"{session.id}.json").write_text(
                json.dumps(session.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Failed to save session %s: %s", session.id, exc)
