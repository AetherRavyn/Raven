"""Conversational depth: working memory, compression, follow-up.

This package gives the runtime three primitives:

  * :class:`WorkingMemory`  — per-session state (summary,
    recent turns, facts, entities, current topic)
  * :class:`Compressor`     — sliding-window summarisation
  * :class:`FollowUpResolver` — turn a "that thing" reference
    into a specific prior turn

All three are deterministic-friendly: every external hook
is a plain :class:`Callable`, so tests can plug in stubs and
the runtime can plug in an LLM.
"""

from __future__ import annotations

from app.core.conversation.compression import (
    Compressed,
    Compressor,
    apply_to_working_memory,
    deterministic_summary,
)
from app.core.conversation.manager import (
    ConversationManager,
    SummaryFn,
)
from app.core.conversation.memory import (
    Turn,
    WorkingMemory,
    detect_topic,
    extract_entities,
    extract_facts,
)
from app.core.conversation.resolver import (
    FollowUpResolver,
    Resolved,
    resolve_references,
)

__all__ = [
    "Compressed",
    "Compressor",
    "ConversationManager",
    "FollowUpResolver",
    "Resolved",
    "SummaryFn",
    "Turn",
    "WorkingMemory",
    "apply_to_working_memory",
    "detect_topic",
    "deterministic_summary",
    "extract_entities",
    "extract_facts",
    "resolve_references",
]
