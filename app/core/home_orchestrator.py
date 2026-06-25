"""Home Orchestrator — Phase 4 (v11) — scenes + presence.

A high-level coordinator on top of the existing stateless
Home Assistant wrappers (:class:`SmartHomeTool`,
:class:`SensorReadTool`, etc.).  The orchestrator introduces
two new domain primitives:

1. **Scene** — a named, ordered list of ``SceneAction``s that
   mutate a set of HA entities in one call.  Example:

   ::

       Scene("movie_mode", location="living_room", actions=[
           SceneAction("light.living_room", "turn_on",
                       {"brightness": 32}),
           SceneAction("light.living_room", "turn_on",
                       {"color_temp": 220}),
           SceneAction("media_player.tv", "turn_on", {}),
       ])

2. **Presence** — the user's current location and when they
   arrived there.  Used by ``current_scene_for_presence()``
   to answer "what should the house be doing right now?".

The orchestrator does **not** talk to Home Assistant directly.
The agent runtime already registers ``SmartHomeTool`` (and
its peers) as a tool; the orchestrator delegates scene
actions to that tool at run time.  This keeps the boundary
clean — the orchestrator never sees an HTTP client.

JSONL fallback
--------------

The scene catalog and presence record are persisted to JSONL
under the workspace root so a process restart does not
destroy them.  The format is one JSON object per line:

    {"kind": "scene", "name": "movie_mode", ...}
    {"kind": "presence", "location": "living_room", ...}

A corrupt line is skipped (logged at WARNING) and the rest
of the file is read normally.

Failure modes
-------------

Every write is best-effort.  A missing tool, a missing HA
configuration, or a network error is captured in the
returned :class:`SceneResult.actions` list with
``success=False`` and the error message.  The orchestrator
never raises on runtime errors — the slash-command path and
the ambient-loop tick are the two callers and both need
bulletproof failure handling.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol

logger = logging.getLogger(__name__)


# ── Domain dataclasses ───────────────────────────────────────────────


@dataclass(slots=True)
class SceneAction:
    """One step in a scene.

    ``entity_id`` is the HA entity to act on (e.g.
    ``light.living_room``).  ``service`` is the HA service
    name within the entity's domain (e.g. ``turn_on``,
    ``turn_off``, ``toggle``).  ``service_data`` is the
    optional extra kwargs (e.g. ``{"brightness": 32}``).
    """

    entity_id: str
    service: str
    service_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "service": self.service,
            "service_data": dict(self.service_data),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SceneAction":
        return cls(
            entity_id=str(raw.get("entity_id", "")).strip(),
            service=str(raw.get("service", "")).strip(),
            service_data=dict(raw.get("service_data") or {}),
        )


@dataclass(slots=True)
class Scene:
    """A named, ordered list of :class:`SceneAction` steps.

    ``location`` ties the scene to a presence zone — e.g. a
    ``"movie_mode"`` scene lives in the ``"living_room"`` and
    is the answer to "what should happen in the living room
    when the user is there in the evening?".
    """

    name: str
    actions: list[SceneAction] = field(default_factory=list)
    location: str | None = None
    description: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "scene",
            "name": self.name,
            "location": self.location,
            "description": self.description,
            "created_at": self.created_at,
            "actions": [a.to_dict() for a in self.actions],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Scene":
        return cls(
            name=str(raw.get("name", "")).strip(),
            location=(str(raw["location"]).strip()
                      if raw.get("location") else None),
            description=str(raw.get("description", "")),
            created_at=str(raw.get("created_at", "")),
            actions=[
                SceneAction.from_dict(a)
                for a in (raw.get("actions") or [])
            ],
        )


@dataclass(slots=True)
class SceneResult:
    """The outcome of running a scene.

    ``actions`` is one entry per :class:`SceneAction` in
    declaration order — the caller can correlate by index
    when reporting results back to the user.  ``succeeded``
    is the count of ``success=True`` actions; ``dry_run`` is
    ``True`` when the scene was planned but not executed.
    """

    scene_name: str
    actions: list[dict[str, Any]] = field(default_factory=list)
    dry_run: bool = False
    succeeded: int = 0
    failed: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_name": self.scene_name,
            "dry_run": self.dry_run,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "actions": list(self.actions),
        }

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def format_text(self) -> str:
        """One-screen, human-readable render for /scene and the
        ambient-loop audit log entry."""
        tag = "DRY-RUN" if self.dry_run else "RUN"
        lines: list[str] = [
            f"{tag} {self.scene_name}: {self.succeeded} ok, {self.failed} failed",
        ]
        for a in self.actions:
            mark = "✓" if a.get("success") else "✗"
            lines.append(
                f"  {mark} {a.get('entity_id')} {a.get('service')} "
                f"({a.get('error', '')})"
            )
        return "\n".join(lines)


@dataclass(slots=True)
class Presence:
    """The user's current location and arrival time.

    ``location`` is a free-form string that the operator
    defines (e.g. ``"living_room"``, ``"office"``, ``"away"``).
    ``arrived_at`` is an ISO timestamp.  ``source`` records
    how the presence was set (``"user"`` for explicit
    ``set_presence``, ``"tick"`` for the ambient-loop refresh,
    ``"slash"`` for a ``/scene`` call that implied a location
    change).
    """

    location: str
    arrived_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )
    source: str = "user"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "presence",
            "location": self.location,
            "arrived_at": self.arrived_at,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Presence":
        return cls(
            location=str(raw.get("location", "")).strip() or "unknown",
            arrived_at=str(
                raw.get("arrived_at")
                or datetime.now(timezone.utc).isoformat(),
            ),
            source=str(raw.get("source", "user")),
        )


# ── Tool protocol (loose coupling) ─────────────────────────────────


class SceneExecutor(Protocol):
    """Loose interface the orchestrator needs from the agent
    runtime.  Any object with an ``execute(**kwargs) -> dict``
    method qualifies — typically ``SmartHomeTool`` but a
    stub or a RecordingExecutor works equally well in tests.

    The orchestrator calls
    ``executor.execute(operation=service, entity_id=..., **service_data)``
    for each :class:`SceneAction` and interprets the
    returned ``{"success": bool, "error": str|None}`` dict.
    """

    async def execute(self, **kwargs: Any) -> dict[str, Any]: ...


# ── Orchestrator ────────────────────────────────────────────────────


class HomeOrchestrator:
    """High-level coordinator for scenes + presence.

    The class is **stateless beyond configuration** — every
    method walks the JSONL fallback on demand.  There is no
    in-memory cache, so a process restart is a no-op.  When
    ``executor`` is ``None`` (the default), scene execution
    returns ``success=False`` for every action with the
    error ``"no executor wired"`` — this is the test/dev
    mode and is also the right behaviour when the slash
    command is invoked before the agent runtime has booted.
    """

    def __init__(
        self,
        *,
        workspace_dir: str | Path | None = None,
        executor: SceneExecutor | None = None,
        jsonl_path: str | Path | None = None,
    ) -> None:
        from app.settings.config import Config

        self._workspace_dir = Path(
            workspace_dir or os.environ.get("RAVEN_MEMORY_ROOT") or Config.MEMORY_ROOT
        )
        self._jsonl_path = Path(
            jsonl_path
            if jsonl_path is not None
            else (self._workspace_dir / "home_orchestrator.jsonl")
        )
        self._jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        self._executor = executor

    # ── Scene CRUD ─────────────────────────────────────────────

    def define_scene(
        self,
        name: str,
        actions: Iterable[SceneAction | tuple[str, str] | dict[str, Any]],
        *,
        location: str | None = None,
        description: str = "",
    ) -> Scene:
        """Persist a new scene.  Re-defining an existing
        scene overwrites it (the orchestrator is meant to be
        a catalogue, not a versioned store).

        ``actions`` accepts three shapes for convenience:

        * :class:`SceneAction`
        * ``(entity_id, service)`` tuple — ``service_data``
          defaults to ``{}``
        * ``{"entity_id": ..., "service": ...,
          "service_data": ...}`` dict
        """
        scene = Scene(
            name=name.strip(),
            location=location.strip() if location else None,
            description=description,
            actions=[_coerce_action(a) for a in actions],
        )
        if not scene.name:
            raise ValueError("Scene name is required.")
        # Drop any prior scene with the same name so the
        # redefinition wins atomically.
        existing = [s for s in self._read_scenes() if s.name != scene.name]
        existing.append(scene)
        self._write_scenes(existing)
        return scene

    def get_scene(self, name: str) -> Scene | None:
        """Return the scene with this name, or ``None``."""
        for s in self._read_scenes():
            if s.name == name:
                return s
        return None

    def list_scenes(
        self, *, location: str | None = None,
    ) -> list[Scene]:
        """Return all scenes, optionally filtered by location.

        The location filter is case-insensitive substring —
        ``"living"`` matches ``"living_room"`` and
        ``"living_room"`` and ``"Living Room"``.  A scene
        with no location set never matches a location filter.
        """
        scenes = self._read_scenes()
        if location is None:
            return scenes
        needle = location.strip().lower()
        if not needle:
            return scenes
        out: list[Scene] = []
        for s in scenes:
            if s.location and needle in s.location.lower():
                out.append(s)
        return out

    def delete_scene(self, name: str) -> bool:
        """Remove a scene by name.  Returns ``True`` when a
        scene was actually deleted, ``False`` when the name
        was unknown (the call is a no-op in that case)."""
        scenes = self._read_scenes()
        kept = [s for s in scenes if s.name != name]
        if len(kept) == len(scenes):
            return False
        self._write_scenes(kept)
        return True

    # ── Scene execution ───────────────────────────────────────

    async def run_scene(
        self, name: str, *, dry_run: bool = False,
    ) -> SceneResult:
        """Execute a scene by name.

        In dry-run mode, the actions are *not* dispatched to
        the executor — the result is built with
        ``success=True`` and the would-be call recorded in
        each action entry.  This is the path the slash
        command uses to preview a scene before running it.

        In live mode, actions are dispatched sequentially
        in declaration order.  A failure on action *n* does
        **not** stop the run — every action is attempted so
        the caller gets a complete picture.
        """
        scene = self.get_scene(name)
        if scene is None:
            return SceneResult(
                scene_name=name,
                actions=[],
                dry_run=dry_run,
                succeeded=0,
                failed=0,
            )
        result = SceneResult(
            scene_name=scene.name,
            actions=[],
            dry_run=dry_run,
        )
        for action in scene.actions:
            entry = await self._execute_action(action, dry_run=dry_run)
            result.actions.append(entry)
            if entry.get("success"):
                result.succeeded += 1
            else:
                result.failed += 1
        return result

    async def _execute_action(
        self, action: SceneAction, *, dry_run: bool,
    ) -> dict[str, Any]:
        """Dispatch a single :class:`SceneAction` to the
        executor (or build a dry-run entry when there is
        no executor / dry-run is requested)."""
        if dry_run or self._executor is None:
            return {
                "entity_id": action.entity_id,
                "service": action.service,
                "service_data": dict(action.service_data),
                "success": True,
                "error": None,
                "dry_run": True,
            }
        try:
            res = await self._executor.execute(
                operation=action.service,
                entity_id=action.entity_id,
                service_data=dict(action.service_data),
            )
        except Exception as exc:  # noqa: BLE001 - executor boundary
            logger.warning(
                "HomeOrchestrator: executor raised for %s %s — %s",
                action.entity_id, action.service, exc,
            )
            return {
                "entity_id": action.entity_id,
                "service": action.service,
                "service_data": dict(action.service_data),
                "success": False,
                "error": str(exc),
                "dry_run": False,
            }
        success = bool(res.get("success"))
        return {
            "entity_id": action.entity_id,
            "service": action.service,
            "service_data": dict(action.service_data),
            "success": success,
            "error": res.get("error"),
            "dry_run": False,
        }

    # ── Presence ───────────────────────────────────────────────

    def set_presence(
        self,
        location: str,
        *,
        source: str = "user",
    ) -> Presence:
        """Record the user's current location.

        The presence record is a single line in the JSONL
        (the most recent call wins).  Re-setting the same
        location updates the ``arrived_at`` timestamp.
        """
        presence = Presence(
            location=location.strip() or "unknown",
            source=source,
        )
        self._write_presence(presence)
        return presence

    def get_presence(self) -> Presence | None:
        """Return the most recent presence record, or
        ``None`` when no presence has ever been set."""
        return self._read_presence()

    def current_scene_for_presence(self) -> Scene | None:
        """Return the most recently defined scene whose
        location matches the current presence, or ``None``
        when no presence has been set or no scene matches.

        "Most recently defined" = highest ``created_at``
        timestamp.  This is the answer to "what should the
        house be doing right now?" — the newest scene in
        the location the user is currently in.
        """
        presence = self.get_presence()
        if presence is None:
            return None
        candidates = self.list_scenes(location=presence.location)
        if not candidates:
            return None
        return max(candidates, key=lambda s: s.created_at)

    def scenes_for_location(self, location: str) -> list[Scene]:
        """Public alias for :meth:`list_scenes` that makes
        the intent obvious at the call site.  The two
        methods are kept separate so ``list_scenes`` keeps
        its general-CRUD feel for the read path."""
        return self.list_scenes(location=location)

    # ── JSONL helpers ──────────────────────────────────────────

    def _read_scenes(self) -> list[Scene]:
        scenes: list[Scene] = []
        if not self._jsonl_path.exists():
            return scenes
        for raw in self._jsonl_path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                d = json.loads(raw)
            except json.JSONDecodeError:
                # A single corrupt line must not abort the
                # whole read — log and move on.
                logger.warning(
                    "HomeOrchestrator: skipping corrupt JSONL line — %r",
                    raw[:80],
                )
                continue
            if d.get("kind") == "scene":
                try:
                    scenes.append(Scene.from_dict(d))
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "HomeOrchestrator: skipping malformed scene — %s",
                        exc,
                    )
        return scenes

    def _write_scenes(self, scenes: list[Scene]) -> None:
        """Atomic rewrite of the scene catalog portion of
        the JSONL.  Presence records are preserved."""
        presence = self._read_presence()
        try:
            tmp = self._jsonl_path.with_suffix(".jsonl.tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                if presence is not None:
                    fh.write(json.dumps(presence.to_dict(), ensure_ascii=False) + "\n")
                for s in scenes:
                    fh.write(json.dumps(s.to_dict(), ensure_ascii=False) + "\n")
            tmp.replace(self._jsonl_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("HomeOrchestrator: write_scenes failed — %s", exc)

    def _read_presence(self) -> Presence | None:
        if not self._jsonl_path.exists():
            return None
        latest: Presence | None = None
        for raw in self._jsonl_path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                d = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if d.get("kind") == "presence":
                try:
                    candidate = Presence.from_dict(d)
                except Exception:  # noqa: BLE001
                    continue
                if latest is None or candidate.arrived_at > latest.arrived_at:
                    latest = candidate
        return latest

    def _write_presence(self, presence: Presence) -> None:
        scenes = self._read_scenes()
        try:
            tmp = self._jsonl_path.with_suffix(".jsonl.tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                fh.write(json.dumps(presence.to_dict(), ensure_ascii=False) + "\n")
                for s in scenes:
                    fh.write(json.dumps(s.to_dict(), ensure_ascii=False) + "\n")
            tmp.replace(self._jsonl_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("HomeOrchestrator: write_presence failed — %s", exc)


# ── Helpers ──────────────────────────────────────────────────────────


def _coerce_action(
    value: SceneAction | tuple[Any, ...] | dict[str, Any],
) -> SceneAction:
    """Normalise the accepted action shapes into a
    :class:`SceneAction`.  Raises ``ValueError`` on anything
    that does not match — the caller is the slash command
    or a test, both of which can format the error nicely.

    Accepted shapes:

    * :class:`SceneAction` — passthrough
    * ``(entity_id, service)`` — ``service_data`` defaults to ``{}``
    * ``(entity_id, service, service_data)`` — full form
    * ``{"entity_id": ..., "service": ...,
      "service_data": ...}`` — dict
    """
    if isinstance(value, SceneAction):
        return value
    if isinstance(value, tuple) and len(value) == 2:
        entity_id, service = value
        return SceneAction(entity_id=str(entity_id), service=str(service))
    if isinstance(value, tuple) and len(value) == 3:
        entity_id, service, service_data = value
        return SceneAction(
            entity_id=str(entity_id),
            service=str(service),
            service_data=dict(service_data or {}),
        )
    if isinstance(value, dict):
        return SceneAction.from_dict(value)
    raise ValueError(
        f"SceneAction must be SceneAction, (entity, service) tuple, "
        f"(entity, service, service_data) tuple, or dict; "
        f"got {type(value).__name__}."
    )


# ── Singleton ────────────────────────────────────────────────────────


_home_orchestrator: HomeOrchestrator | None = None


def get_home_orchestrator(
    *,
    workspace_dir: str | Path | None = None,
    executor: SceneExecutor | None = None,
) -> HomeOrchestrator:
    """Return the process-wide :class:`HomeOrchestrator`.

    The first call constructs the orchestrator with the
    supplied kwargs.  Subsequent calls return the cached
    instance and **ignore** the kwargs — tests that need a
    fresh orchestrator with a custom executor should call
    :func:`reset_home_orchestrator_for_tests` between cases
    and either patch this function or call
    :class:`HomeOrchestrator` directly.
    """
    global _home_orchestrator
    if _home_orchestrator is None:
        _home_orchestrator = HomeOrchestrator(
            workspace_dir=workspace_dir,
            executor=executor,
        )
    return _home_orchestrator


def reset_home_orchestrator_for_tests() -> None:  # pragma: no cover - seam
    """Drop the cached singleton."""
    global _home_orchestrator
    _home_orchestrator = None


__all__ = [
    "SceneAction",
    "Scene",
    "SceneResult",
    "Presence",
    "SceneExecutor",
    "HomeOrchestrator",
    "get_home_orchestrator",
    "reset_home_orchestrator_for_tests",
]
