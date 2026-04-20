import json
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages persistent stateful sessions via JSONL files in the workspace."""

    def __init__(self, workspace_dir: str | None = None):
        from app.settings.config import Config

        self.workspace_dir = (
            Path(workspace_dir) if workspace_dir else Path(Config.MEMORY_ROOT)
        )
        self.sessions_dir = Path(Config.MEMORY_ROOT) / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _get_session_file(self, session_id: str) -> Path:
        return self.sessions_dir / f"{session_id}.jsonl"

    def load_session(self, session_id: str) -> List[Dict[str, Any]]:
        """Loads a session's message history from disk."""
        file_path = self._get_session_file(session_id)
        messages = []
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            messages.append(json.loads(line))
            except Exception as e:
                logger.error(f"Failed to load session {session_id}: {e}")
        return messages

    def append_message(self, session_id: str, message: Dict[str, Any]) -> None:
        """Appends a single message to the session's JSONL file."""
        file_path = self._get_session_file(session_id)
        try:
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(message) + "\n")
        except Exception as e:
            logger.error(f"Failed to append to session {session_id}: {e}")

    def prune_session(self, session_id: str, max_messages: int = 50) -> None:
        """Implements a sliding window memory by keeping the system prompt and the latest N messages."""
        messages = self.load_session(session_id)
        if len(messages) > max_messages:
            # Preserve system prompt if it's the first message
            if messages and messages[0].get("role") == "system":
                pruned = [messages[0]] + messages[-(max_messages - 1) :]
            else:
                pruned = messages[-max_messages:]
            file_path = self._get_session_file(session_id)
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    for msg in pruned:
                        f.write(json.dumps(msg) + "\n")
            except Exception as e:
                logger.error(f"Failed to prune session {session_id}: {e}")

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

        summary = "Session summary:\n" + "\n".join(
            f"- {line}" for line in summary_parts
        )

        file_path = self._get_session_file(session_id)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(json.dumps({"role": "system", "content": summary}) + "\n")
                for msg in tail:
                    f.write(json.dumps(msg) + "\n")
        except Exception as e:
            logger.error(f"Failed to summarize session {session_id}: {e}")
            return None

        return summary
