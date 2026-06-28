"""Learning-aware messaging layer.

Wraps BotSignal to inject learning context into outbound messages
and record user interactions back into the LearningStore.

Also provides platform-specific adaptation hints so that
Telegram, Discord, and Slack messages carry the right metadata
for future retrieval.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.botsignal import BotSignal, ReplyTarget
from app.core.learning_db import get_learning_store

logger = logging.getLogger(__name__)

# Platform hints injected into metadata for learning context
_PLATFORM_DOMAIN: dict[str, str] = {
    "telegram": "messaging.social",
    "discord": "messaging.social",
    "slack": "messaging.workplace",
    "web": "messaging.web",
    "websocket": "messaging.realtime",
}

# Platform-specific context queries for relevant knowledge injection
_PLATFORM_CONTEXT_HINTS: dict[str, list[str]] = {
    "telegram": [
        "user preference communication style",
        "quick tip shortcut",
        "casual response pattern",
    ],
    "discord": [
        "community guideline",
        "shared knowledge topic",
        "conversation thread context",
    ],
    "slack": [
        "workplace procedure workflow",
        "professional communication standard",
        "team collaboration pattern",
    ],
    "web": [
        "user preference",
        "general knowledge fact",
        "interaction history",
    ],
    "websocket": [
        "real-time update preference",
        "streaming response pattern",
        "user preference",
    ],
}


class LearningMessenger:
    """Enriches BotSignal messages with learning context.

    Usage::

        messenger = LearningMessenger.get_instance()
        await messenger.send_text(
            target, text,
            source_kind="chat",
            learning_context="Tell the user about their project progress"
        )
    """

    def __init__(self, botsignal: BotSignal | None = None) -> None:
        self._signal = botsignal
        self._store: Any = None

    @property
    def store(self):
        if self._store is None:
            self._store = get_learning_store()
        return self._store

    async def send_text(
        self,
        target: ReplyTarget,
        text: str,
        *,
        source_kind: str | None = None,
        learning_context: str | None = None,
        record_interaction: bool = True,
        tool_traces: list | None = None,
        evidence: list[str] | None = None,
    ) -> None:
        """Send text with optional learning context injection.

        When *learning_context* is not provided, platform-specific context
        hints are used automatically (Telegram gets casual tips, Slack
        gets workplace knowledge, etc.).
        """

        platform = target.platform.lower()
        platform_domain = _PLATFORM_DOMAIN.get(platform, "messaging.unknown")
        enriched_kind = source_kind or platform_domain

        # Determine context query: explicit or platform-specific
        if learning_context is None:
            ctx = self._build_platform_context(platform)
        elif learning_context:
            ctx = self._build_learning_context(learning_context)
        else:
            ctx = ""

        full_text = f"[Context]\n{ctx}\n\n{text}" if ctx else text

        await self._signal.send_text(
            target,
            full_text,
            source_kind=enriched_kind,
            tool_traces=tool_traces,
            evidence=evidence,
        )

        if record_interaction:
            self._record_interaction(target, text, enriched_kind)

    def _build_platform_context(self, platform: str) -> str:
        """Build context from platform-specific knowledge domains."""
        hints = _PLATFORM_CONTEXT_HINTS.get(platform, ["user preference", "general knowledge"])
        parts: list[str] = []
        seen: set[int] = set()
        for hint in hints:
            try:
                results = self.store.search(hint, limit=2, min_confidence=0.3)
                for r in results:
                    if r["id"] not in seen:
                        seen.add(r["id"])
                        tag = r["type"].replace("_", " ").title()
                        parts.append(f"- [{tag}] {r['content'][:150]}")
                        self.store.record_use(r["id"])
            except Exception:
                continue
        return "\n".join(parts) if parts else ""

    def _build_learning_context(self, query: str) -> str:
        """Retrieve relevant learnings and format as context block."""
        try:
            results = self.store.search(query, limit=3, min_confidence=0.3)
            if not results:
                return ""
            lines: list[str] = []
            for r in results:
                tag = r["type"].replace("_", " ").title()
                lines.append(f"- [{tag}] {r['content'][:150]}")
                self.store.record_use(r["id"])
            return "\n".join(lines)
        except Exception as exc:
            logger.debug("Learning context build failed: %s", exc)
            return ""

    def _record_interaction(
        self,
        target: ReplyTarget,
        text: str,
        source_kind: str,
    ) -> None:
        """Log the message as a learning signal."""
        try:
            self.store.add(
                type_="message",
                content=text[:300],
                topic=source_kind or "messaging",
                confidence=0.3,
                metadata={
                    "platform": target.platform,
                    "chat_id": target.chat_id,
                    "char_count": len(text),
                },
                source="learning_messenger",
            )
        except Exception as exc:
            logger.debug("Failed to record interaction: %s", exc)

    @classmethod
    def get_instance(cls, botsignal: BotSignal | None = None) -> LearningMessenger:
        instance = getattr(cls, "_instance", None)
        if instance is None:
            instance = cls(botsignal=botsignal)
            cls._instance = instance
        return instance

    @classmethod
    def reset_instance(cls) -> None:
        if hasattr(cls, "_instance"):
            del cls._instance


class BotSignalWrapper:
    """Drop-in replacement for BotSignal that routes all send_text calls through LearningMessenger.

    Every other method (send, send_to_platform, register_sender, etc.)
    is delegated directly to the underlying BotSignal — zero code changes
    needed in the 44+ call sites across the orchestrator.
    """

    def __init__(self, botsignal: BotSignal) -> None:
        self._signal = botsignal
        self._messenger = LearningMessenger(botsignal)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._signal, name)

    async def send_text(
        self,
        target: ReplyTarget,
        text: str,
        *,
        source_kind: str | None = None,
        tool_traces: list | None = None,
        evidence: list[str] | None = None,
    ) -> None:
        await self._messenger.send_text(
            target,
            text,
            source_kind=source_kind,
            tool_traces=tool_traces,
            evidence=evidence,
            record_interaction=True,
            learning_context=text,
        )
