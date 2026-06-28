"""Session Manager — Persistent session storage with FTS5 full-text search.

Manages conversation sessions as JSONL files and provides fast
full-text search across all sessions using a persistent SQLite FTS5 index.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages persistent stateful sessions via JSONL files with FTS5 search.

    Each session is stored as ``<session_id>.jsonl`` in the sessions directory.
    A persistent SQLite database with FTS5 full-text search indexes all sessions
    incrementally, avoiding full rebuilds on every query.
    """

    def __init__(self, workspace_dir: str | None = None):
        from app.settings.config import Config

        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path(Config.MEMORY_ROOT)
        self.sessions_dir = Path(Config.MEMORY_ROOT) / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        # Persistent FTS5 index
        self._fts_db_path = self.sessions_dir / ".fts_index.sqlite"
        self._fts_conn: sqlite3.Connection | None = None
        # Track modification times to avoid re-indexing
        self._indexed_files: dict[str, float] = {}

    # ── Session I/O ─────────────────────────────────────────────────

    def _get_session_file(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.jsonl"

    def load_session(self, session_id: str) -> list[dict[str, Any]]:
        file_path = self._get_session_file(session_id)
        messages: list[dict[str, Any]] = []
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            messages.append(json.loads(line))
            except Exception as e:
                logger.error("Failed to load session %s: %s", session_id, e)
        return messages

    def append_message(self, session_id: str, message: dict[str, Any]) -> None:
        from app.core.atomic_io import atomic_append

        file_path = self._get_session_file(session_id)
        try:
            atomic_append(file_path, json.dumps(message) + "\n")
            # Mark for re-indexing on next search
            self._indexed_files.pop(str(file_path), None)
        except Exception as e:
            logger.error("Failed to append to session %s: %s", session_id, e)

    def prune_session(self, session_id: str, max_messages: int = 50) -> None:
        messages = self.load_session(session_id)
        if len(messages) > max_messages:
            if messages and messages[0].get("role") == "system":
                pruned = [messages[0]] + messages[-(max_messages - 1) :]
            else:
                pruned = messages[-max_messages:]
            file_path = self._get_session_file(session_id)
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    for msg in pruned:
                        f.write(json.dumps(msg) + "\n")
                self._indexed_files.pop(str(file_path), None)
            except Exception as e:
                logger.error("Failed to prune session %s: %s", session_id, e)

    def list_sessions(self) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        for f in sorted(
            self.sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            sessions.append(
                {
                    "session_id": f.stem,
                    "modified_at": f.stat().st_mtime,
                    "size_bytes": f.stat().st_size,
                }
            )
        return sessions

    # ── FTS5 Full-Text Search ───────────────────────────────────────

    def search_sessions(
        self,
        query: str,
        limit: int = 10,
        session_id: str | None = None,
        max_content_chars: int = 300,
    ) -> list[dict[str, Any]]:
        """Search across all sessions using a persistent FTS5 index.

        The index is built incrementally — only new/changed session
        files are re-indexed on each call.

        Args:
            query: FTS5 search query (supports standard FTS5 syntax).
            limit: Maximum results to return.
            session_id: If set, only search within this session.
            max_content_chars: Truncate content to this length.

        Returns:
            List of dicts with ``session_id``, ``role``, ``content``,
            ``rank``, and ``matches`` (comma-separated matched terms).
        """
        if not query or not query.strip():
            return []

        conn = self._get_fts_connection()
        self._ensure_index(conn)

        try:
            fts_query = query
            # Auto-append wildcard for partial matching
            if not any(c in query for c in '*"^'):
                fts_query = " OR ".join(
                    f'"{word}"*' if len(word) > 2 else word for word in query.split()
                )

            sql = (
                "SELECT session_id, role, content, rank, highlight(sessions_fts, 2, '‹', '›') AS matches "
                "FROM sessions_fts WHERE sessions_fts MATCH ? "
            )
            params: list[Any] = [fts_query]

            if session_id:
                sql += "AND session_id = ? "
                params.append(session_id)

            sql += "ORDER BY rank LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()

            return [
                {
                    "session_id": r[0],
                    "role": r[1],
                    "content": (r[2] or "")[:max_content_chars],
                    "rank": round(r[3], 4),
                    "matches": (r[4] or "")[:200],
                }
                for r in rows
            ]
        except Exception as exc:
            logger.debug("FTS5 search failed: %s", exc)
            # Fallback: linear scan
            return self._fallback_search(query, limit, session_id, max_content_chars)

    def search_conversations(
        self,
        query: str,
        limit: int = 5,
        context_messages: int = 3,
    ) -> list[dict[str, Any]]:
        """Search sessions and return results with surrounding context.

        Unlike ``search_sessions`` which returns individual matching
        messages, this returns the matching message plus the surrounding
        messages for conversational context.

        Args:
            query: FTS5 search query.
            limit: Maximum results to return.
            context_messages: Number of messages before/after to include.

        Returns:
            List of dicts with ``session_id``, ``messages`` (list of
            messages forming a conversation snippet), ``rank``.
        """
        results = self.search_sessions(query, limit=limit)
        conversations: list[dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()

        for r in results:
            sid = r["session_id"]
            messages = self.load_session(sid)
            # Find the matching message index
            match_idx = -1
            for i, msg in enumerate(messages):
                if query.lower() in (msg.get("content", "") or "").lower():
                    match_idx = i
                    break
            if match_idx < 0:
                continue

            key = (sid, match_idx)
            if key in seen:
                continue
            seen.add(key)

            start = max(0, match_idx - context_messages)
            end = min(len(messages), match_idx + context_messages + 1)
            snippet = messages[start:end]

            conversations.append(
                {
                    "session_id": sid,
                    "rank": r["rank"],
                    "message_index": match_idx,
                    "context_range": {"start": start, "end": end - 1},
                    "messages": [
                        {"role": m.get("role"), "content": (m.get("content") or "")[:500]}
                        for m in snippet
                    ],
                }
            )

        return sorted(conversations, key=lambda x: x["rank"])[:limit]

    # ── FTS5 Index Management ───────────────────────────────────────

    def _get_fts_connection(self) -> sqlite3.Connection:
        if self._fts_conn is None:
            self._fts_conn = sqlite3.connect(str(self._fts_db_path))
            self._fts_conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts "
                "USING fts5(session_id, role, content, tokenize='porter unicode61')"
            )
        return self._fts_conn

    def _ensure_index(self, conn: sqlite3.Connection) -> None:
        for session_file in self.sessions_dir.glob("*.jsonl"):
            file_path = str(session_file)
            mtime = session_file.stat().st_mtime
            last_indexed = self._indexed_files.get(file_path)

            if last_indexed is not None and mtime <= last_indexed:
                continue

            session_id = session_file.stem
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            msg = json.loads(line)
                            content = msg.get("content", "")
                            if content:
                                conn.execute(
                                    "INSERT INTO sessions_fts VALUES (?, ?, ?)",
                                    (session_id, msg.get("role", ""), content),
                                )
                        except Exception:
                            continue
                conn.commit()
                self._indexed_files[file_path] = mtime
            except Exception as e:
                logger.debug("Failed to index session %s: %s", session_id, e)

    def rebuild_index(self) -> dict[str, Any]:
        """Force a full rebuild of the FTS5 index from all session files."""
        try:
            self._fts_db_path.unlink(missing_ok=True)
            self._fts_conn = None
            self._indexed_files.clear()
            conn = self._get_fts_connection()
            count = 0
            for session_file in self.sessions_dir.glob("*.jsonl"):
                session_id = session_file.stem
                try:
                    with open(session_file, "r", encoding="utf-8") as f:
                        for line in f:
                            if not line.strip():
                                continue
                            msg = json.loads(line)
                            content = msg.get("content", "")
                            if content:
                                conn.execute(
                                    "INSERT INTO sessions_fts VALUES (?, ?, ?)",
                                    (session_id, msg.get("role", ""), content),
                                )
                                count += 1
                    self._indexed_files[str(session_file)] = session_file.stat().st_mtime
                except Exception:
                    continue
            conn.commit()
            return {
                "success": True,
                "messages_indexed": count,
                "files_scanned": len(self._indexed_files),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _fallback_search(
        self,
        query: str,
        limit: int,
        session_id: str | None,
        max_content_chars: int,
    ) -> list[dict[str, Any]]:
        """Linear scan fallback when FTS5 is unavailable."""
        query_lower = query.lower()
        results: list[dict[str, Any]] = []
        for session_file in sorted(
            self.sessions_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            sid = session_file.stem
            if session_id and sid != session_id:
                continue
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        msg = json.loads(line)
                        content = msg.get("content", "") or ""
                        if query_lower in content.lower():
                            results.append(
                                {
                                    "session_id": sid,
                                    "role": msg.get("role", ""),
                                    "content": content[:max_content_chars],
                                    "rank": 0.0,
                                    "matches": query,
                                }
                            )
                            if len(results) >= limit:
                                return results
            except Exception:
                continue
        return results

    # ── Session Summary ─────────────────────────────────────────────

    def summarize_session(self, session_id: str, keep_last: int = 12) -> str | None:
        messages = self.load_session(session_id)
        if not messages:
            return None

        head = messages[:-keep_last] if len(messages) > keep_last else []
        tail = messages[-keep_last:] if keep_last else messages

        summary_parts: list[str] = []
        for msg in head:
            role = msg.get("role", "unknown")
            content = str(msg.get("content", "")).strip().replace("\n", " ")
            if content:
                summary_parts.append(f"{role}: {content[:160]}")

        if not summary_parts:
            return None

        summary = "Session summary:\n" + "\n".join(f"- {line}" for line in summary_parts)

        file_path = self._get_session_file(session_id)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(json.dumps({"role": "system", "content": summary}) + "\n")
                for msg in tail:
                    f.write(json.dumps(msg) + "\n")
            self._indexed_files.pop(str(file_path), None)
        except Exception as e:
            logger.error("Failed to summarize session %s: %s", session_id, e)
            return None

        return summary
