"""Email Drafter — compose emails in the user's personal style.

Analyzes the user's past sent emails to learn their communication style,
then drafts new emails that match their tone, vocabulary, and patterns.
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


class EmailDrafterTool(BaseTool):
    """Draft emails in the user's learned communication style."""

    def __init__(self, workspace_dir: str = "workspace") -> None:
        from app.settings.config import Config
        self._dir = Path(workspace_dir or Config.MEMORY_ROOT) / "email_style"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._style_file = self._dir / "style_profile.json"
        self._drafts_file = self._dir / "drafts.jsonl"

    def get_name(self) -> str:
        return "email_drafter"

    def get_description(self) -> str:
        return (
            "Draft emails in the user's personal communication style. "
            "Learns from past sent emails to match tone, vocabulary, and patterns. "
            "Can draft replies, compose new emails, or adjust style."
        )

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["draft", "reply", "learn", "style", "refine"],
                    "description": "draft=new email, reply=respond to thread, learn=analyze past emails, style=show learned style",
                },
                "recipient": {"type": "string", "description": "Email recipient"},
                "subject": {"type": "string", "description": "Email subject"},
                "context": {"type": "string", "description": "What the email is about / original email to reply to"},
                "tone": {"type": "string", "description": "Override tone: formal, casual, friendly, professional, brief"},
                "past_emails": {"type": "array", "description": "Past sent emails for style learning (for 'learn' operation)"},
                "draft_id": {"type": "string", "description": "Draft ID to refine"},
                "feedback": {"type": "string", "description": "Feedback on the draft for refinement"},
            },
            "required": ["operation"],
        }

    async def execute(self, **kwargs: Any) -> dict:
        operation = kwargs.get("operation", "draft")

        if operation == "learn":
            return self._learn_style(kwargs.get("past_emails", []))
        elif operation == "style":
            return self._show_style()
        elif operation == "draft":
            return self._draft_email(kwargs)
        elif operation == "reply":
            return self._draft_reply(kwargs)
        elif operation == "refine":
            return self._refine_draft(kwargs)
        return {"error": f"Unknown operation: {operation}"}

    def _learn_style(self, past_emails: list[str]) -> dict:
        """Analyze past emails to learn communication style."""
        if not past_emails:
            return {"error": "No past emails provided"}

        style = {
            "avg_length": sum(len(e) for e in past_emails) / len(past_emails),
            "avg_words": sum(len(e.split()) for e in past_emails) / len(past_emails),
            "greeting_patterns": [],
            "closing_patterns": [],
            "common_phrases": [],
            "formality_score": 0.5,
            "punctuation_style": "standard",
            "sample_count": len(past_emails),
        }

        greetings = []
        closings = []
        all_words = []

        for email in past_emails:
            lines = email.strip().split('\n')
            if lines:
                first = lines[0].strip()
                if re.match(r'^(Hi|Hello|Hey|Dear|Good\s+\w+)', first, re.I):
                    greetings.append(first)
                last = lines[-1].strip()
                if re.match(r'^(Best|Thanks|Regards|Cheers|Sincerely|Take care)', last, re.I):
                    closings.append(last)
            all_words.extend(email.lower().split())

        # Greeting analysis
        if greetings:
            style["greeting_patterns"] = list(set(greetings))[:5]
            if any("Dear" in g for g in greetings):
                style["formality_score"] = 0.8
            elif any("Hey" in g for g in greetings):
                style["formality_score"] = 0.3

        # Closing analysis
        if closings:
            style["closing_patterns"] = list(set(closings))[:5]

        # Common phrases
        from collections import Counter
        word_freq = Counter(all_words)
        stop_words = {"the", "a", "an", "is", "are", "was", "in", "to", "for", "of", "and", "or", "i", "we", "you", "it", "this", "that"}
        common = [(w, c) for w, c in word_freq.most_common(50) if w not in stop_words and len(w) > 3]
        style["common_phrases"] = [w for w, c in common[:15]]

        # Punctuation
        exclamations = sum(1 for e in past_emails if '!' in e)
        questions = sum(1 for e in past_emails if '?' in e)
        if exclamations > len(past_emails) * 0.3:
            style["punctuation_style"] = "enthusiastic"
        elif questions > len(past_emails) * 0.3:
            style["punctuation_style"] = "inquisitive"

        self._save_style(style)
        return {"success": True, "style": style, "message": f"Learned from {len(past_emails)} emails"}

    def _show_style(self) -> dict:
        """Show the current learned style."""
        style = self._load_style()
        if not style:
            return {"message": "No style learned yet. Use operation=learn with past emails first."}
        return {"style": style}

    def _draft_email(self, kwargs: dict) -> dict:
        """Draft a new email in the user's style."""
        recipient = kwargs.get("recipient", "")
        subject = kwargs.get("subject", "")
        context = kwargs.get("context", "")
        tone = kwargs.get("tone", "")

        if not context:
            return {"error": "context is required (what the email is about)"}

        style = self._load_style()
        formality = style.get("formality_score", 0.5)

        # Build style guidance
        guidance_parts = []
        if tone:
            guidance_parts.append(f"Use a {tone} tone")
        elif formality > 0.7:
            guidance_parts.append("Use formal, professional language")
        elif formality < 0.3:
            guidance_parts.append("Use casual, friendly language")
        else:
            guidance_parts.append("Use a professional but approachable tone")

        if style.get("greeting_patterns"):
            guidance_parts.append(f"Start with a greeting like: {style['greeting_patterns'][0]}")
        if style.get("closing_patterns"):
            guidance_parts.append(f"End with: {style['closing_patterns'][0]}")

        avg_words = style.get("avg_words", 100)
        if avg_words < 50:
            guidance_parts.append("Keep it brief (under 50 words)")
        elif avg_words > 200:
            guidance_parts.append("Can be detailed (200+ words is typical for you)")

        guidance = "; ".join(guidance_parts)

        # Store draft for refinement
        import uuid
        draft_id = f"draft_{uuid.uuid4().hex[:8]}"
        draft = {
            "id": draft_id,
            "recipient": recipient,
            "subject": subject,
            "context": context,
            "style_guidance": guidance,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with open(self._drafts_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(draft, ensure_ascii=False) + "\n")

        return {
            "success": True,
            "draft_id": draft_id,
            "style_guidance": guidance,
            "instructions": (
                f"Draft an email to {recipient or '(recipient)'} "
                f"with subject '{subject or '(subject)'}'. "
                f"Context: {context}. "
                f"Style guidance: {guidance}. "
                f"Make it sound natural and personal, not generic."
            ),
        }

    def _draft_reply(self, kwargs: dict) -> dict:
        """Draft a reply to an email thread."""
        context = kwargs.get("context", "")
        tone = kwargs.get("tone", "")

        if not context:
            return {"error": "context is required (the email to reply to)"}

        style = self._load_style()
        formality = style.get("formality_score", 0.5)

        guidance_parts = ["Reply directly to the email below"]
        if tone:
            guidance_parts.append(f"Use a {tone} tone")
        elif formality > 0.7:
            guidance_parts.append("Use professional, respectful tone")
        else:
            guidance_parts.append("Match the sender's energy level")

        if style.get("closing_patterns"):
            guidance_parts.append(f"Sign off with: {style['closing_patterns'][0]}")

        import uuid
        draft_id = f"draft_{uuid.uuid4().hex[:8]}"

        return {
            "success": True,
            "draft_id": draft_id,
            "instructions": (
                f"Draft a reply to this email: {context[:500]}. "
                f"Style guidance: {'; '.join(guidance_parts)}. "
                f"Address all points raised. Be concise but thorough."
            ),
        }

    def _refine_draft(self, kwargs: dict) -> dict:
        """Refine a draft based on feedback."""
        feedback = kwargs.get("feedback", "")
        if not feedback:
            return {"error": "feedback is required"}

        return {
            "success": True,
            "instructions": (
                f"Revise the email draft based on this feedback: {feedback}. "
                f"Keep the same structure but address the specific changes requested."
            ),
        }

    def _load_style(self) -> dict:
        if not self._style_file.exists():
            return {}
        try:
            return json.loads(self._style_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_style(self, style: dict) -> None:
        self._style_file.write_text(json.dumps(style, indent=2, ensure_ascii=False), encoding="utf-8")
