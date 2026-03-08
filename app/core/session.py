import json
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages persistent stateful sessions via JSONL files in the workspace."""

    def __init__(self, workspace_dir: str):
        self.workspace_dir = Path(workspace_dir)
        self.sessions_dir = self.workspace_dir / "sessions"
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
