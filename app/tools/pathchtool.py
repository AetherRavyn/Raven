from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from app.tools.base import BaseTool, ToolParameter, ToolSchema

# ---------------------------------------------------------------------------
# Patch parsing models
# ---------------------------------------------------------------------------


class OpType(str, Enum):
    ADD = "add"
    UPDATE = "update"
    DELETE = "delete"


@dataclass
class Hunk:
    """A single @@ block: lines to remove and lines to insert."""

    removes: List[str] = field(default_factory=list)
    adds: List[str] = field(default_factory=list)
    end_of_file: bool = False  # True when hunk targets EOF only


@dataclass
class FileOp:
    op: OpType
    path: str
    move_to: Optional[str] = None  # rename target (UPDATE only)
    hunks: List[Hunk] = field(default_factory=list)  # UPDATE / ADD
    add_lines: List[str] = field(default_factory=list)  # ADD file content


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class PatchParseError(ValueError):
    pass


def _parse_patch(input_text: str) -> List[FileOp]:
    lines = input_text.splitlines()

    # Locate markers
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == "*** Begin Patch")
        end = next(i for i, l in enumerate(lines) if l.strip() == "*** End Patch")
    except StopIteration:
        raise PatchParseError("Missing '*** Begin Patch' or '*** End Patch' markers.")

    body = lines[start + 1 : end]
    ops: List[FileOp] = []
    current_op: Optional[FileOp] = None
    current_hunk: Optional[Hunk] = None

    def _flush_hunk():
        nonlocal current_hunk
        if current_hunk is not None and current_op is not None:
            current_op.hunks.append(current_hunk)
            current_hunk = None

    for raw in body:
        line = raw.rstrip("\n")

        # --- file-level directives ---
        if line.startswith("*** Add File:"):
            _flush_hunk()
            if current_op:
                ops.append(current_op)
            current_op = FileOp(
                op=OpType.ADD, path=line[len("*** Add File:") :].strip()
            )
            current_hunk = None

        elif line.startswith("*** Update File:"):
            _flush_hunk()
            if current_op:
                ops.append(current_op)
            current_op = FileOp(
                op=OpType.UPDATE, path=line[len("*** Update File:") :].strip()
            )
            current_hunk = None

        elif line.startswith("*** Delete File:"):
            _flush_hunk()
            if current_op:
                ops.append(current_op)
            current_op = FileOp(
                op=OpType.DELETE, path=line[len("*** Delete File:") :].strip()
            )
            current_hunk = None

        elif line.startswith("*** Move to:"):
            if current_op is None or current_op.op != OpType.UPDATE:
                raise PatchParseError(
                    "'*** Move to:' must appear inside an '*** Update File:' block."
                )
            current_op.move_to = line[len("*** Move to:") :].strip()

        # --- hunk markers ---
        elif line.strip() == "@@":
            _flush_hunk()
            current_hunk = Hunk()

        elif line.strip() == "*** End of File":
            _flush_hunk()
            current_hunk = Hunk(end_of_file=True)

        # --- content lines ---
        elif line.startswith("+"):
            content = line[1:]  # strip leading +
            if current_op is None:
                raise PatchParseError("Content line '+' found outside any file block.")
            if current_op.op == OpType.ADD:
                current_op.add_lines.append(content)
            elif current_hunk is not None:
                current_hunk.adds.append(content)
            else:
                raise PatchParseError(
                    "'+' line found outside any '@@' hunk in UPDATE block."
                )

        elif line.startswith("-"):
            content = line[1:]
            if current_hunk is None:
                raise PatchParseError("'-' line found outside any '@@' hunk.")
            current_hunk.removes.append(content)

        elif line == "" or line.startswith(" "):
            # Context / blank lines — ignored (not required by our format)
            pass

        # anything else is silently ignored (comments, etc.)

    _flush_hunk()
    if current_op:
        ops.append(current_op)

    if not ops:
        raise PatchParseError("Patch contains no file operations.")

    return ops


# ---------------------------------------------------------------------------
# Applier
# ---------------------------------------------------------------------------


class PatchApplyError(RuntimeError):
    pass


def _resolve_path(path: str, workspace: Optional[str]) -> str:
    """Return absolute path, optionally anchored to workspace."""
    if os.path.isabs(path):
        resolved = path
    else:
        base = workspace or os.getcwd()
        resolved = os.path.normpath(os.path.join(base, path))

    if workspace:
        workspace_abs = os.path.normpath(os.path.abspath(workspace))
        if (
            not resolved.startswith(workspace_abs + os.sep)
            and resolved != workspace_abs
        ):
            raise PatchApplyError(
                f"Path '{path}' escapes the workspace directory. "
                "Set workspace_only=False to allow writes outside workspace."
            )
    return resolved


def _apply_hunks(original_lines: List[str], hunks: List[Hunk]) -> List[str]:
    """Apply a list of hunks to file lines and return the updated lines."""
    result = list(original_lines)

    for hunk in hunks:
        if hunk.end_of_file:
            # EOF insert — just append
            result.extend(l + "\n" for l in hunk.adds)
            continue

        if not hunk.removes and not hunk.adds:
            continue

        if hunk.removes:
            # Find the first occurrence of the remove-block as a contiguous sequence
            target = [l + "\n" for l in hunk.removes]
            n = len(target)
            idx = None
            for i in range(len(result) - n + 1):
                if result[i : i + n] == target:
                    idx = i
                    break
            if idx is None:
                raise PatchApplyError(
                    f"Could not find lines to remove:\n" + "".join(target)
                )
            replacement = [l + "\n" for l in hunk.adds]
            result[idx : idx + n] = replacement
        else:
            # Pure insertion with no context — append (caller should use *** End of File)
            result.extend(l + "\n" for l in hunk.adds)

    return result


def _apply_ops(
    ops: List[FileOp], workspace: Optional[str], workspace_only: bool
) -> List[str]:
    """
    Apply all FileOps to the filesystem.
    Returns a list of human-readable result lines.
    """
    ws = os.path.abspath(workspace) if workspace else None
    if not workspace_only:
        ws = None  # disable workspace guard

    results: List[str] = []

    for op in ops:
        path = _resolve_path(op.path, ws)

        if op.op == OpType.DELETE:
            if not os.path.exists(path):
                raise PatchApplyError(
                    f"Cannot delete '{op.path}': file does not exist."
                )
            os.remove(path)
            results.append(f"Deleted:  {op.path}")

        elif op.op == OpType.ADD:
            if os.path.exists(path):
                raise PatchApplyError(
                    f"Cannot add '{op.path}': file already exists. "
                    "Use '*** Update File' to modify existing files."
                )
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                for line in op.add_lines:
                    f.write(line + "\n")
            results.append(f"Added:    {op.path}  ({len(op.add_lines)} lines)")

        elif op.op == OpType.UPDATE:
            if not os.path.exists(path):
                raise PatchApplyError(
                    f"Cannot update '{op.path}': file does not exist."
                )

            with open(path, "r", encoding="utf-8") as f:
                original = f.readlines()

            updated = _apply_hunks(original, op.hunks)

            # Determine write target (may be a rename)
            write_path = path
            if op.move_to:
                write_path = _resolve_path(op.move_to, ws)
                os.makedirs(os.path.dirname(write_path), exist_ok=True)

            with open(write_path, "w", encoding="utf-8") as f:
                f.writelines(updated)

            if op.move_to and write_path != path:
                os.remove(path)
                results.append(f"Moved:    {op.path} → {op.move_to}")
            else:
                results.append(f"Updated:  {op.path}  ({len(op.hunks)} hunk(s))")

    return results


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class ApplyPatchTool(BaseTool):
    """Apply structured multi-file patches (add, update, delete, move).

    Constructor kwargs:
        workspace       str   Root directory for relative paths (default: cwd)
        workspace_only  bool  Block writes outside workspace dir (default: True)
        dry_run         bool  Parse and validate only, make no filesystem changes (default: False)
    """

    def __init__(self, **cfg: Any):
        self.workspace: Optional[str] = cfg.get("workspace")
        self.workspace_only: bool = bool(cfg.get("workspace_only", True))
        self.dry_run: bool = bool(cfg.get("dry_run", False))

    def get_name(self) -> str:
        return "apply_patch"

    def get_description(self) -> str:
        return (
            "Apply file changes using a structured patch format. "
            "Supports adding, updating (with hunks), deleting, and moving files "
            "across multiple files in a single call."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="input",
                    type="string",
                    description=(
                        "Full patch contents including '*** Begin Patch' and '*** End Patch'. "
                        "Supports: '*** Add File:', '*** Update File:', '*** Delete File:', "
                        "'*** Move to:', '@@' (hunk separator), '*** End of File', "
                        "'+' (add line), '-' (remove line)."
                    ),
                    required=True,
                ),
                ToolParameter(
                    name="workspace",
                    type="string",
                    description=(
                        "Override the root directory used for resolving relative paths. "
                        "Defaults to the directory set at construction time (or cwd)."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="workspace_only",
                    type="boolean",
                    description=(
                        "Block writes outside the workspace directory (default: True). "
                        "Set False only if you intentionally need to write outside the workspace."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="dry_run",
                    type="boolean",
                    description=(
                        "If True, parse and validate the patch without making any filesystem changes."
                    ),
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        patch_input: str = kwargs.get("input", "").strip()
        if not patch_input:
            return {"success": False, "output": "Error: 'input' parameter is required."}

        # Per-call overrides
        workspace = kwargs.get("workspace", self.workspace)
        workspace_only = bool(kwargs.get("workspace_only", self.workspace_only))
        dry_run = bool(kwargs.get("dry_run", self.dry_run))

        # 1. Parse
        try:
            ops = _parse_patch(patch_input)
        except PatchParseError as e:
            return {"success": False, "output": f"Patch parse error: {e}"}

        # 2. Dry-run: report what would happen without touching the filesystem
        if dry_run:
            summary = []
            for op in ops:
                if op.op == OpType.ADD:
                    summary.append(
                        f"[DRY RUN] Would add:    {op.path}  ({len(op.add_lines)} lines)"
                    )
                elif op.op == OpType.DELETE:
                    summary.append(f"[DRY RUN] Would delete: {op.path}")
                elif op.op == OpType.UPDATE:
                    extra = f" → {op.move_to}" if op.move_to else ""
                    summary.append(
                        f"[DRY RUN] Would update: {op.path}{extra}  ({len(op.hunks)} hunk(s))"
                    )
            return {
                "success": True,
                "output": "\n".join(summary),
                "dry_run": True,
                "operations": len(ops),
            }

        # 3. Apply
        try:
            results = _apply_ops(
                ops, workspace=workspace, workspace_only=workspace_only
            )
        except PatchApplyError as e:
            return {"success": False, "output": f"Patch apply error: {e}"}
        except Exception as e:
            return {"success": False, "output": f"Unexpected error: {e}"}

        return {
            "success": True,
            "output": "\n".join(results),
            "operations": len(ops),
        }
