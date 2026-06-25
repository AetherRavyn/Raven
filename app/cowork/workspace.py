"""Cowork workspace — a user-granted folder with explicit access mode.

A workspace is the **only** path the worker can read from or write
to during a session.  Outside the granted path, the sandboxed
executor refuses to operate.  This is the same security model
:class:`app.tools.filetool.AdvancedFileOperationTool` uses, lifted
to the cowork level so the worker can compose multiple tools
without losing the boundary.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class AccessMode(str, Enum):
    """Permission level the user granted the worker for a folder.

    ``RO`` — read-only.  Worker can list, read, search, summarise.
    ``RW`` — read+write.  Worker can also create, modify, delete
              files within the granted path.  Sub-folders are
              governed by the same mode (no per-subfolder override).
    """

    RO = "ro"
    RW = "rw"

    @property
    def can_write(self) -> bool:
        return self is AccessMode.RW


@dataclass(slots=True)
class Workspace:
    """A folder the user has granted the worker access to."""

    id: str
    name: str
    path: str
    access: AccessMode = AccessMode.RW
    created_at: float = field(default_factory=time.time)
    last_used: float = 0.0
    # Optional: an explicit allowlist of file extensions.  Empty
    # means "all extensions allowed".  Used by the worker to
    # refuse to touch things like ``.env`` or ``*.key`` even if
    # the user gave rw access.
    deny_globs: list[str] = field(default_factory=list)

    # ── validation ────────────────────────────────────────────────

    def __post_init__(self) -> None:
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        self.path = os.path.abspath(self.path)

    def is_within(self, candidate: str) -> bool:
        """True if *candidate* is inside the granted path."""
        try:
            cand_abs = os.path.abspath(candidate)
            self_path = self.path
            # Common-prefix check, with trailing sep to avoid /foo
            # matching /foobar.  ``os.path.commonpath`` handles this.
            return os.path.commonpath([cand_abs, self_path]) == self_path
        except ValueError:
            return False

    def is_denied(self, candidate: str) -> bool:
        """True if *candidate* matches a deny glob (e.g. ``.env``)."""
        if not self.deny_globs:
            return False
        import fnmatch

        name = os.path.basename(candidate)
        return any(fnmatch.fnmatch(name, g) for g in self.deny_globs)

    def authorise(self, candidate: str, write: bool = False) -> tuple[bool, str]:
        """Return ``(ok, reason)`` for a path operation.

        - ``write=True`` and the workspace is RO → denied.
        - Path outside the granted tree → denied.
        - Path matches a deny glob → denied.
        """
        if not self.is_within(candidate):
            return False, f"path '{candidate}' is outside the granted workspace"
        if write and not self.access.can_write:
            return False, f"workspace '{self.name}' is read-only"
        if self.is_denied(candidate):
            return False, f"path '{candidate}' matches a deny glob"
        return True, "ok"

    def touch(self) -> None:
        self.last_used = time.time()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["access"] = self.access.value
        return d

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Workspace":
        return cls(
            id=raw["id"],
            name=raw["name"],
            path=raw["path"],
            access=AccessMode(raw.get("access", "rw")),
            created_at=raw.get("created_at", time.time()),
            last_used=raw.get("last_used", 0.0),
            deny_globs=list(raw.get("deny_globs", [])),
        )


class WorkspaceStore:
    """JSON-on-disk persistence for the user's workspaces."""

    def __init__(self, workspace_dir: str | Path | None = None) -> None:
        self._root = Path(workspace_dir or self._default_workspace())
        self._root.mkdir(parents=True, exist_ok=True)
        self._path = self._root / "cowork" / "workspaces.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._items: dict[str, Workspace] = {}
        self._load()

    @staticmethod
    def _default_workspace() -> str:
        for candidate in ("workspace", "data", "."):
            p = Path(candidate)
            if p.is_dir():
                return str(p.resolve())
        return os.getcwd()

    # ── CRUD ──────────────────────────────────────────────────────

    def list(self) -> list[Workspace]:
        return sorted(self._items.values(), key=lambda w: w.last_used, reverse=True)

    def get(self, workspace_id: str) -> Optional[Workspace]:
        return self._items.get(workspace_id)

    def add(
        self,
        name: str,
        path: str,
        access: AccessMode = AccessMode.RW,
        deny_globs: list[str] | None = None,
    ) -> Workspace:
        abs_path = os.path.abspath(path)
        if not os.path.isdir(abs_path):
            raise ValueError(f"path does not exist or is not a directory: {abs_path}")
        ws = Workspace(
            id=uuid.uuid4().hex[:12],
            name=name,
            path=abs_path,
            access=access,
            deny_globs=deny_globs or [],
        )
        self._items[ws.id] = ws
        self._save()
        return ws

    def remove(self, workspace_id: str) -> bool:
        if workspace_id in self._items:
            del self._items[workspace_id]
            self._save()
            return True
        return False

    def touch(self, workspace_id: str) -> None:
        ws = self._items.get(workspace_id)
        if ws:
            ws.touch()
            self._save()

    # ── persistence ───────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._items = {w["id"]: Workspace.from_dict(w) for w in raw}
        except (json.JSONDecodeError, OSError, KeyError) as exc:
            logger.warning("Failed to load workspaces: %s", exc)
            self._items = {}

    def _save(self) -> None:
        try:
            payload = [w.to_dict() for w in self._items.values()]
            self._path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Failed to save workspaces: %s", exc)
