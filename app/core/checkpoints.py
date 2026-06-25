"""Checkpoints & Rollback — auto-snapshot files before modifications.

Provides safety net for file operations by:
- Creating checksums before any file modification
- Rolling back to previous state on error
- Listing available checkpoints
- Auto-cleanup of old checkpoints
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CheckpointManager:
    """Auto-snapshot files before modifications, with rollback support."""

    def __init__(self, workspace_dir: str = "workspace") -> None:
        from app.settings.config import Config
        self._workspace = workspace_dir or Config.MEMORY_ROOT
        self._checkpoint_dir = Path(self._workspace) / "checkpoints"
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._index_file = self._checkpoint_dir / "index.json"
        self._max_checkpoints = 50

    def create_checkpoint(self, file_path: str, reason: str = "") -> str:
        """Create a checkpoint before modifying a file."""
        source = Path(file_path)
        if not source.exists():
            return ""

        # Generate checkpoint ID
        checkpoint_id = f"cp_{int(time.time())}_{source.name}"
        cp_dir = self._checkpoint_dir / checkpoint_id
        cp_dir.mkdir(parents=True, exist_ok=True)

        # Copy the file
        dest = cp_dir / source.name
        shutil.copy2(str(source), str(dest))

        # Store metadata
        checksum = self._checksum(source)
        metadata = {
            "id": checkpoint_id,
            "original_path": str(source),
            "backup_path": str(dest),
            "checksum": checksum,
            "size": source.stat().st_size,
            "reason": reason,
            "created_at": time.time(),
        }
        (cp_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        # Update index
        self._update_index(metadata)

        # Cleanup old checkpoints
        self._cleanup()

        return checkpoint_id

    def rollback(self, checkpoint_id: str) -> dict[str, Any]:
        """Restore a file from a checkpoint."""
        cp_dir = self._checkpoint_dir / checkpoint_id
        metadata_file = cp_dir / "metadata.json"

        if not metadata_file.exists():
            return {"error": f"Checkpoint {checkpoint_id} not found"}

        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        backup = Path(metadata["backup_path"])
        target = Path(metadata["original_path"])

        if not backup.exists():
            return {"error": f"Backup file missing: {backup}"}

        # Create a checkpoint of the CURRENT file before rollback
        if target.exists():
            self.create_checkpoint(str(target), reason=f"before rollback to {checkpoint_id}")

        # Restore
        shutil.copy2(str(backup), str(target))

        return {
            "success": True,
            "restored": str(target),
            "from_checkpoint": checkpoint_id,
            "reason": metadata.get("reason", ""),
        }

    def rollback_to_previous(self, file_path: str) -> dict[str, Any]:
        """Rollback a file to its most recent checkpoint."""
        checkpoints = self._get_checkpoints_for(file_path)
        if not checkpoints:
            return {"error": f"No checkpoints found for {file_path}"}

        latest = checkpoints[0]  # Most recent
        return self.rollback(latest["id"])

    def list_checkpoints(self, file_path: str | None = None) -> list[dict[str, Any]]:
        """List available checkpoints."""
        index = self._load_index()
        if file_path:
            return [cp for cp in index if cp.get("original_path") == file_path]
        return index[-self._max_checkpoints:]

    def _get_checkpoints_for(self, file_path: str) -> list[dict[str, Any]]:
        index = self._load_index()
        return [cp for cp in index if cp.get("original_path") == file_path]

    def _checksum(self, path: Path) -> str:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def _load_index(self) -> list[dict[str, Any]]:
        if not self._index_file.exists():
            return []
        try:
            return json.loads(self._index_file.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _update_index(self, metadata: dict[str, Any]) -> None:
        index = self._load_index()
        index.append(metadata)
        self._index_file.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")

    def _cleanup(self) -> None:
        """Remove old checkpoints beyond max limit."""
        index = self._load_index()
        if len(index) <= self._max_checkpoints:
            return

        # Remove oldest
        to_remove = index[:len(index) - self._max_checkpoints]
        for cp in to_remove:
            cp_dir = self._checkpoint_dir / cp["id"]
            if cp_dir.exists():
                shutil.rmtree(str(cp_dir))

        # Update index
        remaining = index[-self._max_checkpoints:]
        self._index_file.write_text(json.dumps(remaining, indent=2, ensure_ascii=False), encoding="utf-8")


# Singleton
_manager: CheckpointManager | None = None


def get_checkpoint_manager() -> CheckpointManager:
    global _manager
    if _manager is None:
        _manager = CheckpointManager()
    return _manager
