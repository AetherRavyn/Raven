"""Follow-up resolution — turn a reference into a prior turn.

Conversations are full of pronouns, demonstratives, and
"earlier" / "before" / "what about..." that point at
something specific in the transcript.  This module turns a
*reference* (a substring of the current turn) into a
:class:`Resolved` object that names the specific turn /
entity / topic the user is pointing at.

Strategies, in order:

  1. **Pronoun** — "it", "that", "this" → most recent turn
  2. **Demonstrative** — "that thing", "this idea" → most
     recent turn whose content shares the noun
  3. **Temporal** — "earlier", "before", "above" → an older
     turn (skip the most recent N)
  4. **Topic** — a topic name from :class:`WorkingMemory`
  5. **Fallback** — most recent turn

The resolver is read-only — it doesn't mutate the working
memory.  Callers use the resolved turn id / role / content /
position to do whatever follow-up they need.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.core.conversation.memory import Turn, WorkingMemory

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# resolution
# -------------------------------------------------------------------


@dataclass(slots=True)
class Resolved:
    """A resolved reference."""

    turn: Turn | None
    strategy: str  # "pronoun" | "demonstrative" | "temporal" | "topic" | "fallback" | "none"
    confidence: float
    detail: str = ""

    @property
    def found(self) -> bool:
        return self.turn is not None


# Patterns.  Case-insensitive.
_PRONOUN = re.compile(r"^(it|this|that|these|those|they|them)\b", re.I)
_DEMONSTRATIVE_NOUN = re.compile(
    r"^(?:that|this|these|those|the)\s+(?P<noun>[a-z][a-z0-9_-]{2,40})\b", re.I
)
_TEMPORAL = re.compile(
    r"\b(earlier|before|previously|above|earlier today|earlier this|"
    r"a moment ago|just now|before that)\b",
    re.I,
)
# "What about X" / "And X" / "About X" → user is asking for
# a topic turn.
_TOPIC_HINT_PHRASE = re.compile(
    r"^\s*(?:what about|and|but|re:|about|regarding)\s+"
    r"(?P<topic>[A-Za-z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*){0,3})",
    re.I,
)


# Pronoun-only references that resolve to the most recent
# turn regardless of role.
_PRONOUN_REFS = {"it", "this", "that", "these", "those", "they", "them"}


# -------------------------------------------------------------------
# resolver
# -------------------------------------------------------------------


class FollowUpResolver:
    """Resolve a reference in a turn to a prior turn.

    Built from a :class:`WorkingMemory`.  Stateless — every
    :meth:`resolve` call is independent and safe to call
    concurrently.
    """

    def __init__(self, working_memory: WorkingMemory) -> None:
        self.wm = working_memory

    def resolve(self, reference: str) -> Resolved:
        ref = (reference or "").strip()
        if not ref:
            return Resolved(turn=None, strategy="none", confidence=0.0)

        turns = list(self.wm.recent_turns)
        if not turns:
            return Resolved(turn=None, strategy="none", confidence=0.0)

        # 1. demonstrative + noun ("that thing") — checked first.
        #    If the pattern matches, this strategy "owns" the
        #    resolution: returning a not-found Resolved here is
        #    intentional (the user pointed at a noun we don't
        #    have — we shouldn't fall through to a pronoun that
        #    means something different).
        demo_result = self._resolve_demonstrative(ref, turns)
        if demo_result is not None:
            return demo_result

        # 2. bare pronoun ("it", "that") → most recent
        r = self._resolve_pronoun(ref, turns)
        if r.found:
            return r

        # 3. temporal ("earlier", "before")
        r = self._resolve_temporal(ref, turns)
        if r.found:
            return r

        # 4. topic hint
        r = self._resolve_topic(ref, turns)
        if r.found:
            return r

        # 5. fallback: most recent
        return Resolved(
            turn=turns[-1],
            strategy="fallback",
            confidence=0.2,
            detail="most recent turn",
        )

    # ---- strategies ----

    def _resolve_demonstrative(self, ref: str, turns: list[Turn]) -> Resolved | None:
        m = _DEMONSTRATIVE_NOUN.search(ref)
        if m is None:
            return None
        noun = m.group("noun").lower()
        for t in reversed(turns):
            if noun in t.content.lower():
                return Resolved(
                    turn=t,
                    strategy="demonstrative",
                    confidence=0.8,
                    detail=f"noun '{noun}' in turn {t.id}",
                )
        # Pattern matched but noun isn't in any turn — own the
        # resolution, return not-found (don't fall through).
        return Resolved(
            turn=None,
            strategy="demonstrative",
            confidence=0.0,
            detail=f"noun '{noun}' not found in any turn",
        )

    # ---- strategies ----

    def _resolve_pronoun(self, ref: str, turns: list[Turn]) -> Resolved:
        # Only the bare pronoun, optionally with a verb
        # ("it failed", "that worked") — but no extra nouns.
        first = ref.split(maxsplit=1)[0].lower().rstrip(".,;:!?")
        if first not in _PRONOUN_REFS:
            return Resolved(turn=None, strategy="pronoun", confidence=0.0)
        # "it" / "that" → most recent turn
        return Resolved(
            turn=turns[-1],
            strategy="pronoun",
            confidence=0.7,
            detail=f"pronoun '{first}' → most recent",
        )

    def _resolve_temporal(self, ref: str, turns: list[Turn]) -> Resolved:
        if not _TEMPORAL.search(ref):
            return Resolved(turn=None, strategy="temporal", confidence=0.0)
        # "earlier" / "before" → the turn just before the most
        # recent one.  Walk back further only if needed.
        if len(turns) < 2:
            return Resolved(turn=None, strategy="temporal", confidence=0.0)
        return Resolved(
            turn=turns[-2],
            strategy="temporal",
            confidence=0.6,
            detail="temporal reference → turn before most recent",
        )

    def _resolve_topic(self, ref: str, turns: list[Turn]) -> Resolved:
        m = _TOPIC_HINT_PHRASE.search(ref)
        if m is None:
            return Resolved(turn=None, strategy="topic", confidence=0.0)
        topic = m.group("topic").lower()
        if self.wm.current_topic and topic in self.wm.current_topic.lower():
            return Resolved(
                turn=turns[-1],
                strategy="topic",
                confidence=0.7,
                detail=f"matches current topic '{self.wm.current_topic}'",
            )
        # Walk back looking for a turn that mentions the topic.
        for t in reversed(turns):
            if topic in t.content.lower():
                return Resolved(
                    turn=t,
                    strategy="topic",
                    confidence=0.6,
                    detail=f"mentions topic '{topic}'",
                )
        return Resolved(
            turn=None,
            strategy="topic",
            confidence=0.0,
            detail=f"topic '{topic}' not in any turn",
        )


# -------------------------------------------------------------------
# small wrapper
# -------------------------------------------------------------------


def resolve_references(
    working_memory: WorkingMemory,
    references: Iterable[str],
) -> list[Resolved]:
    """Resolve a batch of references — used by the runtime."""
    r = FollowUpResolver(working_memory)
    return [r.resolve(ref) for ref in references]
