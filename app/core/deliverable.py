from __future__ import annotations

import csv
import io
import json
import logging
import mimetypes
import sqlite3
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class OutputType(str, Enum):
    ZIP = "zip"
    FILE = "file"
    JSON = "json"
    CSV = "csv"
    PDF = "pdf"
    IMAGE = "image"
    CODE = "code"

    def __str__(self) -> str:
        return self.value


class DeliveryChannel(str, Enum):
    DOWNLOAD_LINK = "download_link"
    FILE_UPLOAD = "file_upload"
    BINARY_STREAM = "binary_stream"
    EMAIL_ATTACHMENT = "email_attachment"

    def __str__(self) -> str:
        return self.value


class Deliverable:
    __slots__ = (
        "id", "output_type", "content", "filename", "mime_type",
        "size_bytes", "metadata", "created_at",
    )

    def __init__(
        self,
        id: str,
        output_type: str,
        content: bytes | str,
        filename: str,
        mime_type: str,
        size_bytes: int = 0,
        metadata: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> None:
        self.id = id
        self.output_type = output_type
        self.content = content
        self.filename = filename
        self.mime_type = mime_type
        self.size_bytes = size_bytes or (len(content) if isinstance(content, bytes) else len(content.encode("utf-8")))
        self.metadata = metadata or {}
        now = datetime.now(timezone.utc).isoformat()
        self.created_at = created_at or now

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Deliverable:
        return cls(
            id=row["id"],
            output_type=row["output_type"],
            content=row["content"],
            filename=row["filename"],
            mime_type=row["mime_type"],
            size_bytes=row["size_bytes"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            created_at=row["created_at"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "output_type": self.output_type,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    def __repr__(self) -> str:
        return (
            f"Deliverable(id={self.id!r}, filename={self.filename!r}, "
            f"type={self.output_type!r})"
        )


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS deliverables (
    id TEXT PRIMARY KEY,
    output_type TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    content BLOB,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS delivery_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deliverable_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    target TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    delivered_at TEXT,
    error TEXT,
    FOREIGN KEY (deliverable_id) REFERENCES deliverables(id)
);
"""

_DELIVERABLE_KEYWORDS = [
    "export", "download", "give me", "csv of", "spreadsheet",
    "as file", "as json", "archive", "zip",
]


class DeliverableManager:
    def __init__(self, db_path: str | Path = "workspace/memory/deliverables.db") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=5000")
        return self._local.conn

    def _init_db(self) -> None:
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def create_deliverable(
        self,
        output_type: str,
        content: bytes | str,
        filename: str,
        metadata: dict[str, Any] | None = None,
    ) -> Deliverable:
        output_type = output_type.lower()
        if output_type not in {t.value for t in OutputType}:
            raise ValueError(f"Unknown output type: {output_type!r}")

        mime_type = self._detect_mime_type(filename)
        prepared = self._prepare_content(output_type, content, filename)
        deliverable = Deliverable(
            id=str(uuid.uuid4()),
            output_type=output_type,
            content=prepared,
            filename=filename,
            mime_type=mime_type,
            metadata=metadata or {},
        )
        self._conn.execute(
            """INSERT INTO deliverables (id, output_type, filename, mime_type, size_bytes, content, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                deliverable.id, deliverable.output_type, deliverable.filename,
                deliverable.mime_type, deliverable.size_bytes,
                sqlite3.Binary(deliverable.content) if isinstance(deliverable.content, bytes) else deliverable.content,
                json.dumps(deliverable.metadata), deliverable.created_at,
            ),
        )
        self._conn.commit()
        logger.info(
            "Deliverable created: %s (%s, %d bytes)",
            deliverable.id, deliverable.filename, deliverable.size_bytes,
        )
        return deliverable

    def get_deliverable(self, deliverable_id: str) -> Deliverable | None:
        row = self._conn.execute(
            "SELECT * FROM deliverables WHERE id = ?", (deliverable_id,)
        ).fetchone()
        return Deliverable.from_row(row) if row else None

    def list_deliverables(self, limit: int = 50) -> list[Deliverable]:
        rows = self._conn.execute(
            "SELECT * FROM deliverables ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [Deliverable.from_row(r) for r in rows]

    def delete_deliverable(self, deliverable_id: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM deliverables WHERE id = ?", (deliverable_id,)
        )
        self._conn.commit()
        deleted = cur.rowcount > 0
        if deleted:
            logger.info("Deliverable deleted: %s", deliverable_id)
            self._conn.execute(
                "DELETE FROM delivery_log WHERE deliverable_id = ?",
                (deliverable_id,),
            )
            self._conn.commit()
        return deleted

    def get_download_url(self, deliverable_id: str) -> str:
        deliverable = self._get_or_raise(deliverable_id)
        return f"https://api.raven.ai/deliverables/{deliverable.id}/download/{deliverable.filename}"

    def get_content(self, deliverable_id: str) -> bytes:
        deliverable = self._get_or_raise(deliverable_id)
        if isinstance(deliverable.content, bytes):
            return deliverable.content
        return deliverable.content.encode("utf-8")

    def deliver_to_channel(
        self,
        deliverable_id: str,
        channel: str,
        target: str,
    ) -> bool:
        if channel not in {c.value for c in DeliveryChannel}:
            raise ValueError(f"Unknown delivery channel: {channel!r}")
        self._get_or_raise(deliverable_id)
        now = datetime.now(timezone.utc).isoformat()
        try:
            logger.info(
                "Delivering %s via %s to %s", deliverable_id, channel, target,
            )
            self._conn.execute(
                """INSERT INTO delivery_log (deliverable_id, channel, target, status, delivered_at)
                   VALUES (?, ?, ?, 'delivered', ?)""",
                (deliverable_id, channel, target, now),
            )
            self._conn.commit()
            return True
        except Exception as exc:
            logger.error("Delivery failed for %s: %s", deliverable_id, exc)
            self._conn.execute(
                """INSERT INTO delivery_log (deliverable_id, channel, target, status, error, delivered_at)
                   VALUES (?, ?, ?, 'failed', ?, ?)""",
                (deliverable_id, channel, target, str(exc), now),
            )
            self._conn.commit()
            return False

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    def clear(self) -> None:
        self._conn.executescript(
            "DELETE FROM deliverables; DELETE FROM delivery_log;"
        )
        self._conn.commit()

    def _get_or_raise(self, deliverable_id: str) -> Deliverable:
        deliverable = self.get_deliverable(deliverable_id)
        if deliverable is None:
            raise ValueError(f"Deliverable not found: {deliverable_id!r}")
        return deliverable

    def _prepare_content(
        self,
        output_type: str,
        content: Any,
        filename: str,
    ) -> bytes:
        if output_type == OutputType.ZIP.value:
            return self._prepare_zip(content, filename)
        if output_type == OutputType.FILE.value:
            return self._prepare_file(content, filename)
        if output_type == OutputType.JSON.value:
            if isinstance(content, str):
                content = json.loads(content)
            return self._prepare_json(content, filename)
        if output_type == OutputType.CSV.value:
            if isinstance(content, bytes):
                content = content.decode("utf-8")
            parsed = self._parse_csv_content(content)
            return self._prepare_csv(parsed["rows"], parsed["headers"], filename)
        if isinstance(content, str):
            return content.encode("utf-8")
        return content

    @staticmethod
    def _prepare_zip(content: bytes | str, filename: str) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            inner_name = filename.replace(".zip", "")
            if isinstance(content, bytes):
                zf.writestr(inner_name, content)
            else:
                zf.writestr(inner_name, content.encode("utf-8"))
        return buf.getvalue()

    @staticmethod
    def _prepare_file(content: bytes | str, filename: str) -> bytes:
        if isinstance(content, str):
            return content.encode("utf-8")
        return content

    @staticmethod
    def _prepare_json(content: Any, filename: str) -> bytes:
        return json.dumps(content, indent=2, default=str).encode("utf-8")

    @staticmethod
    def _prepare_csv(
        rows: list[list[str]],
        headers: list[str],
        filename: str,
    ) -> bytes:
        buf = io.StringIO()
        writer = csv.writer(buf)
        if headers:
            writer.writerow(headers)
        writer.writerows(rows)
        return buf.getvalue().encode("utf-8")

    @staticmethod
    def _parse_csv_content(
        content: str | list[list[str]],
    ) -> dict[str, Any]:
        if isinstance(content, list):
            return {"rows": content, "headers": []}
        lines = [line.strip() for line in content.split("\n") if line.strip()]
        if not lines:
            return {"rows": [], "headers": []}
        reader = csv.reader(lines)
        data = list(reader)
        return {"rows": data[1:], "headers": data[0] if data else []}

    @staticmethod
    def _detect_mime_type(filename: str) -> str:
        mime, _ = mimetypes.guess_type(filename)
        if mime:
            return mime
        ext = Path(filename).suffix.lower()
        mime_map = {
            ".zip": "application/zip",
            ".json": "application/json",
            ".csv": "text/csv",
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".svg": "image/svg+xml",
            ".html": "text/html",
            ".txt": "text/plain",
            ".py": "text/x-python",
            ".md": "text/markdown",
            ".yaml": "application/x-yaml",
            ".yml": "application/x-yaml",
            ".xml": "application/xml",
        }
        return mime_map.get(ext, "application/octet-stream")


def has_deliverable_intent(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in _DELIVERABLE_KEYWORDS)
