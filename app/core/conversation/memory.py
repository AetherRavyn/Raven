"""Working memory for multi-turn conversations.

A :class:`WorkingMemory` is the per-session state the runtime
keeps in addition to the raw event log.  It has four parts:

  * ``summary`` — a rolling summary of older turns (produced
    by :mod:`app.core.conversation.compression`)
  * ``recent_turns`` — the last N turns, verbatim
  * ``facts`` — small structured key/value pairs extracted
    from the conversation ("project=saras", "user=alice",
    "deadline=2026-01-15", ...)
  * ``entities`` — named entities the user has mentioned
  * ``current_topic`` — what we're talking about right now

The working memory is *deterministic* for the deterministic
parts (extraction).  The summary may come from an LLM, but the
interface accepts a plain :class:`Callable` so tests can plug
in a stub.

The class is intentionally side-effect free — it doesn't
talk to the LLM directly.  A :class:`Compressor` does the
heavy lifting, and the runtime wires the LLM into the
compressor.  This keeps the memory module easy to test and
trivial to swap.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# turn
# -------------------------------------------------------------------


@dataclass(slots=True)
class Turn:
    """A single conversational turn.

    Distinct from :class:`app.core.continuity.SessionEvent`
    because it carries the role and content with a stable
    id; session events are the storage form, turns are the
    working-memory form.
    """

    id: str
    role: str  # "user" | "assistant" | "tool" | "system"
    content: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


# -------------------------------------------------------------------
# working memory
# -------------------------------------------------------------------


# Deterministic fact-extraction helpers.  These are intentionally
# conservative — the LLM pass can do better, but the regex
# fallback has to be correct without one.

_KEY_VALUE_PATTERN = re.compile(
    r"\b(?P<key>[a-z][a-z0-9_-]{1,30})\s*[=:]\s*(?P<value>[A-Za-z0-9_./-]{1,80})",
    re.IGNORECASE,
)
# "About Phase D" → capture "Phase D"; "regarding" / "re:" handled similarly.
# Inline (?i:...) limits case-insensitivity to the hint alternation;
# the capture group stays case-sensitive (we want a Capitalized noun).
_TOPIC_HINT = re.compile(
    r"\b(?i:about|regarding|on the topic of|re:)\s+"
    r"([A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*){0,3})"
)
# Multi-word capitalized phrases (HelixDB, Phase D, Home Sentinel).
_MULTI_CAP = re.compile(r"\b([A-Z][a-z]{2,}(?:\s+[A-Z][A-Za-z0-9]{1,})+)\b")
# Single capitalized words — any length, allows compound forms
# (HelixDB, GitHub, PhaseD).  Common English filter does the
# noise reduction.
_SINGLE_CAP = re.compile(r"\b([A-Z][A-Za-z]{2,})\b")


@dataclass(slots=True)
class WorkingMemory:
    """Per-session working state."""

    user_id: str = ""
    summary: str = ""
    recent_turns: deque[Turn] = field(default_factory=lambda: deque(maxlen=20))
    facts: dict[str, str] = field(default_factory=dict)
    entities: Counter[str] = field(default_factory=Counter)
    current_topic: str | None = None
    # Hooks for runtime-supplied extractors.
    fact_extractor: Callable[[Turn], dict[str, str]] | None = None
    topic_extractor: Callable[[Turn, str | None], str | None] | None = None

    # ---- intake ----

    def add_turn(self, turn: Turn) -> None:
        """Ingest a turn: update facts, entities, topic; append verbatim."""
        self.recent_turns.append(turn)
        self._absorb(turn)

    def add_turns(self, turns: Iterable[Turn]) -> None:
        for t in turns:
            self.add_turn(t)

    def _absorb(self, turn: Turn) -> None:
        extractor = self.fact_extractor or extract_facts
        try:
            new_facts = extractor(turn)
        except Exception as exc:  # noqa: BLE001
            logger.debug("fact extractor failed: %s", exc)
            new_facts = {}
        for k, v in new_facts.items():
            if k not in self.facts:
                self.facts[k] = v
        # Track entity mentions.
        for ent in extract_entities(turn.content):
            self.entities[ent] += 1
        # Update topic.
        topic_fn = self.topic_extractor or detect_topic
        try:
            topic = topic_fn(turn, self.current_topic)
        except Exception as exc:  # noqa: BLE001
            logger.debug("topic extractor failed: %s", exc)
            topic = self.current_topic
        if topic is not None:
            self.current_topic = topic

    # ---- serialisation ----

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "summary": self.summary,
            "facts": dict(self.facts),
            "entities": dict(self.entities),
            "current_topic": self.current_topic,
            "recent_turns": [
                {
                    "id": t.id,
                    "role": t.role,
                    "content": t.content,
                    "created_at": t.created_at.isoformat(),
                    "metadata": dict(t.metadata),
                }
                for t in self.recent_turns
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkingMemory:
        wm = cls(user_id=data.get("user_id", ""))
        wm.summary = data.get("summary", "")
        wm.facts = dict(data.get("facts", {}))
        wm.entities = Counter(data.get("entities", {}))
        wm.current_topic = data.get("current_topic")
        wm.recent_turns = deque(maxlen=20)
        for t in data.get("recent_turns", []):
            wm.recent_turns.append(
                Turn(
                    id=t["id"],
                    role=t["role"],
                    content=t["content"],
                    created_at=datetime.fromisoformat(t["created_at"]),
                    metadata=dict(t.get("metadata", {})),
                )
            )
        return wm

    # ---- LLM context ----

    def context_string(self, *, max_facts: int = 20) -> str:
        """Render the working memory as a prompt-ready string.

        Format::

            Summary: <one-paragraph digest>
            Topic: <current topic, or "—">
            Known facts:
              * <k> = <v>
            Recent turns:
              user: <content>
              assistant: <content>
              ...
        """
        lines: list[str] = []
        if self.summary:
            lines.append(f"Summary: {self.summary}")
        lines.append(f"Topic: {self.current_topic or '—'}")
        if self.facts:
            lines.append("Known facts:")
            for k, v in list(self.facts.items())[:max_facts]:
                lines.append(f"  * {k} = {v}")
        if self.recent_turns:
            lines.append("Recent turns:")
            for t in self.recent_turns:
                content = t.content.replace("\n", " ").strip()
                if len(content) > 240:
                    content = content[:237] + "..."
                lines.append(f"  {t.role}: {content}")
        return "\n".join(lines)


# -------------------------------------------------------------------
# deterministic extractors
# -------------------------------------------------------------------


def extract_facts(turn: Turn) -> dict[str, str]:
    """Pull ``key=value`` style facts from a turn.

    Conservative: only matches ``key=value`` where ``key`` is
    a short lowercase identifier.  No inference.  Caller can
    layer an LLM pass on top.
    """
    if turn.role not in ("user", "assistant"):
        return {}
    out: dict[str, str] = {}
    for m in _KEY_VALUE_PATTERN.finditer(turn.content):
        key = m.group("key").lower()
        value = m.group("value").rstrip(".,;:!?")
        if key in out:
            continue  # first-wins
        out[key] = value
    return out


def extract_entities(content: str) -> list[str]:
    """Find capitalized proper-noun phrases.

    Two passes:
      1. Multi-word phrases (HelixDB-style compound words, "Phase D",
         "Home Sentinel") — always included.
      2. Single capitalized words, 4+ chars, not in the
         common-English stopword list.

    The list is deduped (preserves first occurrence).
    """
    seen: set[str] = set()
    out: list[str] = []
    for m in _MULTI_CAP.finditer(content):
        ent = m.group(1).strip()
        # Drop a leading topic-hint word ("About Phase" → "Phase").
        first_word = ent.split(maxsplit=1)[0]
        if first_word in _TOPIC_HINT_FIRST:
            rest = ent.split(maxsplit=1)[1] if " " in ent else ""
            if rest:
                ent = rest
        if not ent or ent in seen:
            continue
        # Drop matches where every word is a stopword ("The I").
        words = ent.split()
        if words and all(w.lower() in _STOPWORDS_LOWER for w in words):
            continue
        seen.add(ent)
        out.append(ent)
    for m in _SINGLE_CAP.finditer(content):
        ent = m.group(1).strip()
        if ent in seen:
            continue
        if ent.lower() in _STOPWORDS_LOWER or ent.lower() in _COMMON_ENGLISH:
            continue
        seen.add(ent)
        out.append(ent)
    return out


_STOPWORDS_LOWER = frozenset(
    {
        "i",
        "you",
        "we",
        "they",
        "the",
        "this",
        "that",
        "these",
        "those",
        "my",
        "your",
        "our",
        "their",
        "what",
        "which",
        "who",
        "whom",
        "whose",
        "where",
        "when",
        "how",
        "why",
        "about",
        "regarding",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "today",
        "yesterday",
        "tomorrow",
        "yes",
        "no",
        "ok",
        "okay",
        "sure",
        "thanks",
        "please",
        "hello",
        "hi",
        "hey",
        "sorry",
    }
)


_TOPIC_HINT_FIRST = {
    "About",
    "Regarding",
    "Re:",
    "Subject",
}


_COMMON_ENGLISH = {
    "what",
    "which",
    "when",
    "where",
    "who",
    "how",
    "why",
    "about",
    "regarding",
    "project",
    "phase",
    "thing",
    "idea",
    "plan",
    "question",
    "answer",
    "task",
    "issue",
    "point",
    "note",
    "message",
    "command",
    "story",
    "side",
    "way",
    "time",
    "year",
    "day",
    "week",
    "month",
    "hour",
    "minute",
    "second",
    "morning",
    "evening",
    "night",
    "afternoon",
    "weekend",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "today",
    "yesterday",
    "tomorrow",
    "world",
    "home",
    "house",
    "work",
    "office",
    "team",
    "group",
    "company",
    "user",
    "users",
    "people",
    "person",
    "place",
    "country",
    "city",
    "state",
    "region",
    "area",
    "system",
    "service",
    "platform",
    "tool",
    "function",
    "method",
    "class",
    "module",
    "package",
    "library",
    "framework",
    "engine",
    "model",
    "data",
    "code",
    "file",
    "folder",
    "directory",
    "page",
    "site",
    "app",
    "bot",
    "agent",
    "thing",
    "stuff",
}


_ENTITY_STOPWORDS = {
    "I",
    "You",
    "We",
    "They",
    "The",
    "This",
    "That",
    "These",
    "Those",
    "My",
    "Your",
    "Our",
    "Their",
    "What",
    "Which",
    "Who",
    "Whom",
    "Whose",
    "Where",
    "When",
    "How",
    "Why",
    "About",
    "Regarding",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
    "Today",
    "Yesterday",
    "Tomorrow",
    "Yes",
    "No",
    "Ok",
    "Okay",
    "Sure",
    "Thanks",
    "Please",
    "Hello",
    "Hi",
    "Hey",
    "Sorry",
}


def detect_topic(turn: Turn, prior_topic: str | None) -> str | None:
    """Identify the topic of a turn.

    Heuristics, in order:
      1. Explicit "about/re: X" hint in the turn
      2. First multi-word capitalized phrase
      3. First sentence as a topic

    Returns the previous topic if the new turn is a short
    follow-up ("ok", "yes", "and?") that doesn't establish a
    new topic.
    """
    text = (turn.content or "").strip()
    if not text:
        return prior_topic

    # Continuation: short affirmations don't change topic.
    if len(text) <= 12 and text.lower() in _FOLLOWUPS:
        return prior_topic

    # 1. Explicit "about X"
    m = _TOPIC_HINT.search(text)
    if m is not None:
        return m.group(1).strip()[:80]

    # 2. First multi-word capitalized phrase
    ent = next(iter(extract_entities(text)), None)
    if ent is not None:
        return ent[:80]

    # 3. First sentence, capped.
    first = re.split(r"[.!?\n]", text, maxsplit=1)[0].strip()
    if first:
        return first[:80]
    return prior_topic


_FOLLOWUPS = {
    "ok",
    "okay",
    "yes",
    "no",
    "and?",
    "and",
    "then?",
    "then",
    "continue",
    "go on",
    "more",
    "right",
    "sure",
    "fine",
    "got it",
    "gotcha",
    "yep",
    "nope",
    "uh huh",
    "mm",
    "hmm",
}
