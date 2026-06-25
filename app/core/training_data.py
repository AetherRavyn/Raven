"""Training Data Generator — compress conversations for model training.

FRIDAY-style: Raven can generate training data from its own
interactions to improve future model performance.

Features:
- Extract tool call patterns from session logs
- Compress long conversations into training examples
- Anonymize sensitive data
- Export in standard formats (JSONL, Parquet)
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TrainingExample:
    """A single training example extracted from a conversation."""
    instruction: str
    input: str
    output: str
    metadata: dict[str, Any] = field(default_factory=dict)


class TrajectoryCompressor:
    """Compresses conversation trajectories into training data.

    Takes raw conversation logs and produces clean training examples
    suitable for fine-tuning or evaluation.
    """

    def __init__(self, workspace_dir: str = "workspace") -> None:
        from app.settings.config import Config
        self._dir = Path(workspace_dir or Config.MEMORY_ROOT) / "training_data"
        self._dir.mkdir(parents=True, exist_ok=True)

    def compress_session(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
    ) -> list[TrainingExample]:
        """Compress a session into training examples.

        Extracts instruction/input/output triples from conversation turns.
        """
        examples: list[TrainingExample] = []

        for i, msg in enumerate(messages):
            if msg.get("role") != "user":
                continue

            # Find the next assistant response
            if i + 1 < len(messages) and messages[i + 1].get("role") == "assistant":
                response = messages[i + 1].get("content", "")
                if response and len(response) > 10:
                    examples.append(TrainingExample(
                        instruction=msg.get("content", ""),
                        input="",
                        output=response[:500],
                        metadata={
                            "session_id": session_id,
                            "turn": i,
                            "has_tool_calls": any(
                                "tool" in m.get("role", "")
                                for m in messages[max(0, i-2):i+2]
                            ),
                        },
                    ))

        return examples

    def export_jsonl(
        self,
        examples: list[TrainingExample],
        output_path: str | None = None,
    ) -> str:
        """Export training examples as JSONL."""
        if output_path is None:
            output_path = str(self._dir / f"training_{int(time.time())}.jsonl")

        with open(output_path, "w", encoding="utf-8") as f:
            for ex in examples:
                f.write(json.dumps({
                    "instruction": ex.instruction,
                    "input": ex.input,
                    "output": ex.output,
                    "metadata": ex.metadata,
                }, ensure_ascii=False) + "\n")

        logger.info("Exported %d training examples to %s", len(examples), output_path)
        return output_path

    def anonymize(self, text: str) -> str:
        """Anonymize sensitive data in text."""
        # Redact emails
        text = re.sub(r'\b[\w.+-]+@[\w-]+\.[\w.-]+\b', '[EMAIL]', text)
        # Redact phone numbers
        text = re.sub(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE]', text)
        # Redact IP addresses
        text = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[IP]', text)
        # Redact API keys
        text = re.sub(r'\b(sk-|ak-|pk-)[\w-]{20,}\b', '[API_KEY]', text)
        return text
