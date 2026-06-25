"""Cowork file-diff utility.

Produces a unified-diff-like structure for a file before / after a
cowork step, suitable for rendering in the dashboard's diff viewer
and for storing as a per-step audit record.  Falls back to
``difflib`` so it works on any host without extra deps.
"""
from __future__ import annotations

import difflib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Hunk:
    """A single diff hunk — old start, new start, list of lines."""

    old_start: int
    new_start: int
    lines: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Diff:
    """Before/after diff for a single file."""

    path: str
    old_text: str
    new_text: str
    hunks: list[Hunk] = field(default_factory=list)
    # Convenience flags
    is_new: bool = False  # file did not exist before
    is_deleted: bool = False  # file will not exist after
    is_unchanged: bool = False

    @property
    def has_changes(self) -> bool:
        return bool(self.hunks) or self.is_new or self.is_deleted

    def stats(self) -> dict[str, int]:
        added = 0
        removed = 0
        for h in self.hunks:
            for line in h.lines:
                if line.startswith("+") and not line.startswith("+++"):
                    added += 1
                elif line.startswith("-") and not line.startswith("---"):
                    removed += 1
        return {"added": added, "removed": removed, "hunks": len(self.hunks)}

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "is_new": self.is_new,
            "is_deleted": self.is_deleted,
            "is_unchanged": self.is_unchanged,
            "hunks": [h.to_dict() for h in self.hunks],
            "stats": self.stats(),
            "old_text": self.old_text,
            "new_text": self.new_text,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Diff":
        return cls(
            path=raw["path"],
            old_text=raw.get("old_text", ""),
            new_text=raw.get("new_text", ""),
            hunks=[Hunk(**h) for h in raw.get("hunks", [])],
            is_new=raw.get("is_new", False),
            is_deleted=raw.get("is_deleted", False),
            is_unchanged=raw.get("is_unchanged", False),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "Diff":
        return cls.from_dict(json.loads(raw))


def compute_file_diff(
    path: str,
    old_text: str,
    new_text: str,
    *,
    context: int = 3,
) -> Diff:
    """Compute a unified-diff for *path* between *old_text* and *new_text*.

    Uses :mod:`difflib` for portability.  Returns a :class:`Diff`
    ready for the dashboard to render.
    """
    is_new = old_text == "" and new_text != ""
    is_deleted = old_text != "" and new_text == ""
    is_unchanged = old_text == new_text
    if is_unchanged:
        return Diff(
            path=path,
            old_text=old_text,
            new_text=new_text,
            hunks=[],
            is_unchanged=True,
        )

    raw_hunks: list[str] = list(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=context,
            lineterm="\n",
        )
    )
    if not raw_hunks:
        return Diff(
            path=path,
            old_text=old_text,
            new_text=new_text,
            hunks=[],
            is_unchanged=True,
        )

    hunks: list[Hunk] = []
    current: Hunk | None = None
    for line_any in raw_hunks:
        line: str = line_any
        if line.startswith("@@"):
            # Parse "@@ -old_start,old_count +new_start,new_count @@"
            try:
                header = line.split("@@")[1].strip().split()
                old_range = header[0].lstrip("-").split(",")
                new_range = header[1].lstrip("+").split(",")
                old_start = int(old_range[0])
                new_start = int(new_range[0])
            except (IndexError, ValueError):
                old_start, new_start = 0, 0
            current = Hunk(old_start=old_start, new_start=new_start, lines=[])
            hunks.append(current)
        elif current is not None and (
            line.startswith("+")
            or line.startswith("-")
            or line.startswith(" ")
        ):
            current.lines.append(line.rstrip("\n"))
    return Diff(
        path=path,
        old_text=old_text,
        new_text=new_text,
        hunks=hunks,
        is_new=is_new,
        is_deleted=is_deleted,
    )


def diff_for_path(
    path: str,
    new_text: str | None = None,
    *,
    root: str,
) -> Diff:
    """Compute a diff for *path* against its current on-disk contents.

    If *new_text* is None, the diff is against an empty string
    (i.e. "delete the file").  *root* is the workspace root so
    paths stay relative.
    """
    abs_path = (
        os.path.join(root, path) if not os.path.isabs(path) else path
    )
    if not os.path.exists(abs_path):
        return compute_file_diff(path, old_text="", new_text=new_text or "")
    try:
        with open(abs_path, encoding="utf-8") as f:
            old_text = f.read()
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("diff_for_path: read %s failed: %s", abs_path, exc)
        old_text = ""
    return compute_file_diff(path, old_text=old_text, new_text=new_text or "")
