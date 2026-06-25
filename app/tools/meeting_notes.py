"""Meeting Notes — extract action items, decisions, and summaries from meeting transcripts.

Processes raw meeting transcripts (text or audio) and generates structured
output with: summary, action items, decisions, key topics, and follow-ups.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class MeetingNotesTool(BaseTool):
    """Extract structured notes from meeting transcripts."""

    def __init__(self, workspace_dir: str = "workspace") -> None:
        from app.settings.config import Config
        self._dir = Path(workspace_dir or Config.MEMORY_ROOT) / "meetings"
        self._dir.mkdir(parents=True, exist_ok=True)

    def get_name(self) -> str:
        return "meeting_notes"

    def get_description(self) -> str:
        return (
            "Process meeting transcripts into structured notes: "
            "summary, action items with assignees, decisions made, "
            "key topics discussed, and follow-up items."
        )

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["process", "transcribe", "search", "list"],
                    "description": "process=extract from transcript, transcribe=audio to text, search=find past meetings",
                },
                "transcript": {"type": "string", "description": "Meeting transcript text"},
                "audio_path": {"type": "string", "description": "Path to audio file for transcription"},
                "title": {"type": "string", "description": "Meeting title"},
                "attendees": {"type": "array", "description": "List of attendees"},
                "query": {"type": "string", "description": "Search query for past meetings"},
                "meeting_id": {"type": "string", "description": "Meeting ID for retrieval"},
            },
            "required": ["operation"],
        }

    async def execute(self, **kwargs: Any) -> dict:
        operation = kwargs.get("operation", "process")

        if operation == "process":
            return self._process_transcript(kwargs)
        elif operation == "transcribe":
            return await self._transcribe_audio(kwargs.get("audio_path", ""))
        elif operation == "search":
            return self._search_meetings(kwargs.get("query", ""))
        elif operation == "list":
            return self._list_meetings()

        return {"error": f"Unknown operation: {operation}"}

    def _process_transcript(self, kwargs: dict) -> dict:
        """Process a transcript into structured meeting notes."""
        transcript = kwargs.get("transcript", "")
        title = kwargs.get("title", "Meeting")
        attendees = kwargs.get("attendees", [])

        if not transcript:
            return {"error": "transcript is required"}

        # Extract structured data from transcript
        notes = {
            "title": title,
            "attendees": attendees,
            "summary": self._extract_summary(transcript),
            "action_items": self._extract_action_items(transcript),
            "decisions": self._extract_decisions(transcript),
            "key_topics": self._extract_topics(transcript),
            "follow_ups": self._extract_follow_ups(transcript),
            "timestamps": self._extract_timestamps(transcript),
            "raw_length": len(transcript),
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }

        # Save meeting notes
        import uuid
        meeting_id = f"meeting_{uuid.uuid4().hex[:8]}"
        notes["meeting_id"] = meeting_id

        meeting_file = self._dir / f"{meeting_id}.json"
        meeting_file.write_text(json.dumps(notes, indent=2, ensure_ascii=False), encoding="utf-8")

        return {"success": True, "meeting_id": meeting_id, "notes": notes}

    def _extract_action_items(self, transcript: str) -> list[dict[str, Any]]:
        """Extract action items with assignees."""
        action_items = []
        lines = transcript.split('\n')

        # Pattern 1: "X will Y" or "X should Y" or "X needs to Y"
        patterns = [
            re.compile(r'(\w+(?:\s+\w+){0,2})\s+(?:will|should|needs to|is going to|must)\s+(.{10,100})', re.I),
            re.compile(r'ACTION:\s*(.+)', re.I),
            re.compile(r'TODO:\s*(.+)', re.I),
            re.compile(r'@(\w+)\s+(.{10,100})', re.I),
        ]

        for line in lines:
            for pattern in patterns:
                matches = pattern.finditer(line)
                for match in matches:
                    groups = match.groups()
                    if len(groups) == 2:
                        assignee, task = groups
                        action_items.append({
                            "assignee": assignee.strip(),
                            "task": task.strip(),
                            "source": line.strip()[:200],
                        })
                    elif len(groups) == 1:
                        action_items.append({
                            "assignee": "unassigned",
                            "task": groups[0].strip(),
                            "source": line.strip()[:200],
                        })

        # Deduplicate
        seen = set()
        unique = []
        for item in action_items:
            key = item["task"].lower()[:50]
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique

    def _extract_decisions(self, transcript: str) -> list[str]:
        """Extract decisions made during the meeting."""
        decisions = []
        patterns = [
            re.compile(r'(?:DECISION|decided|agreed|approved|confirmed)[:\s]+(.{10,200})', re.I),
            re.compile(r'(?:we\'ll go with|we decided to|final decision)[:\s]+(.{10,200})', re.I),
        ]

        for line in transcript.split('\n'):
            for pattern in patterns:
                match = pattern.search(line)
                if match:
                    decisions.append(match.group(1).strip())

        return list(set(decisions))[:10]

    def _extract_topics(self, transcript: str) -> list[str]:
        """Extract key topics discussed."""
        topics = []

        # Look for topic markers
        topic_patterns = [
            re.compile(r'(?:TOPIC|topic|议题|主题)[:\s]+(.{5,80})', re.I),
            re.compile(r'^#{1,3}\s+(.+)', re.M),  # Markdown headers
            re.compile(r'^(?:RE:|Subject:)\s*(.+)', re.I),
        ]

        for pattern in topic_patterns:
            for match in pattern.finditer(transcript):
                topics.append(match.group(1).strip())

        # Fallback: extract key noun phrases from capitalized words
        if not topics:
            cap_words = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b', transcript)
            from collections import Counter
            freq = Counter(cap_words)
            topics = [word for word, count in freq.most_common(5) if count >= 2]

        return topics[:10]

    def _extract_follow_ups(self, transcript: str) -> list[str]:
        """Extract follow-up items."""
        follow_ups = []
        patterns = [
            re.compile(r'(?:follow.?up|follow.?back)[:\s]+(.{5,200})', re.I),
            re.compile(r'(?:next steps|next action)[:\s]+(.{5,200})', re.I),
            re.compile(r'(?:we\'ll revisit|let\'s circle back|pick this up)[:\s]*(.{5,200})', re.I),
        ]

        for line in transcript.split('\n'):
            for pattern in patterns:
                match = pattern.search(line)
                if match:
                    follow_ups.append(match.group(1).strip() if match.lastindex else line.strip())

        return follow_ups[:10]

    def _extract_timestamps(self, transcript: str) -> list[dict[str, str]]:
        """Extract timestamps if present."""
        timestamps = []
        pattern = re.compile(r'(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AP]M)?)\s*[-–]\s*(.{5,200})', re.I)
        for match in pattern.finditer(transcript):
            timestamps.append({"time": match.group(1), "content": match.group(2).strip()})
        return timestamps[:20]

    def _extract_summary(self, transcript: str) -> str:
        """Generate a summary from the transcript."""
        sentences = re.split(r'[.!?]+', transcript)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 20]

        if len(sentences) <= 3:
            return transcript[:500]

        # Take first sentence (intro), middle (main content), last (conclusion)
        summary_parts = []
        if sentences:
            summary_parts.append(sentences[0])
        if len(sentences) > 2:
            mid = len(sentences) // 2
            summary_parts.append(sentences[mid])
        if len(sentences) > 1:
            summary_parts.append(sentences[-1])

        return ". ".join(summary_parts)[:500]

    async def _transcribe_audio(self, audio_path: str) -> dict:
        """Transcribe an audio file to text."""
        if not audio_path:
            return {"error": "audio_path is required"}
        if not Path(audio_path).exists():
            return {"error": f"Audio file not found: {audio_path}"}

        try:
            from app.voice.transcribe import transcribe_file
            text = transcribe_file(audio_path)
            return {"success": True, "text": text, "word_count": len(text.split())}
        except Exception as e:
            return {"error": str(e)[:500]}

    def _search_meetings(self, query: str) -> list[dict]:
        """Search past meeting notes."""
        if not query:
            return []

        results = []
        query_lower = query.lower()

        for f in self._dir.glob("meeting_*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                searchable = json.dumps(data, ensure_ascii=False).lower()
                if query_lower in searchable:
                    results.append({
                        "meeting_id": data.get("meeting_id", ""),
                        "title": data.get("title", ""),
                        "date": data.get("processed_at", ""),
                        "action_items": len(data.get("action_items", [])),
                        "decisions": len(data.get("decisions", [])),
                    })
            except Exception:
                continue

        return results[:20]

    def _list_meetings(self) -> list[dict]:
        """List all stored meetings."""
        meetings = []
        for f in sorted(self._dir.glob("meeting_*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                meetings.append({
                    "meeting_id": data.get("meeting_id", ""),
                    "title": data.get("title", ""),
                    "date": data.get("processed_at", ""),
                    "attendees": data.get("attendees", []),
                })
            except Exception:
                continue
        return meetings[-20:]
