"""Atomic file writes — prevents data loss from crash-mid-write.

All JSONL and JSON file writes should use these helpers instead
of raw open("a").write().
"""

from __future__ import annotations

import json
import os
import tempfile
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def atomic_append(file_path: str | Path, line: str) -> None:
    """Atomically append a line to a file.

    Writes to a temp file, then atomically renames. If the process
    crashes during write, the original file is unchanged.
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=str(file_path.parent), suffix=".tmp", prefix=file_path.stem,
        )
        try:
            # Copy existing content
            if file_path.exists():
                os.write(fd, file_path.read_bytes())
            # Append new line
            os.write(fd, line.encode("utf-8"))
            os.close(fd)
            fd = -1
            # Atomic rename
            os.rename(tmp_path, str(file_path))
        finally:
            if fd >= 0:
                os.close(fd)
            # Clean up temp file if rename failed
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
    except Exception as exc:
        logger.warning("atomic_append failed for %s: %s", file_path, exc)


def atomic_append_jsonl(file_path: str | Path, data: dict | Any) -> None:
    """Atomically append a JSON line to a JSONL file."""
    atomic_append(file_path, json.dumps(data, ensure_ascii=False, default=str) + "\n")


def atomic_write_json(file_path: str | Path, data: Any) -> None:
    """Atomically write a complete JSON file (not append)."""
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    content = json.dumps(data, indent=2, ensure_ascii=False, default=str)

    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=str(file_path.parent), suffix=".tmp", prefix=file_path.stem,
        )
        try:
            os.write(fd, content.encode("utf-8"))
            os.close(fd)
            fd = -1
            os.rename(tmp_path, str(file_path))
        finally:
            if fd >= 0:
                os.close(fd)
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
    except Exception as exc:
        logger.warning("atomic_write_json failed for %s: %s", file_path, exc)
