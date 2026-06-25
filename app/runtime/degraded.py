"""Mode-aware provider gating and canned answers.

When the system is in ``degraded`` or ``offline`` mode the cost router
must refuse to call the cloud and may need to fall back to canned
answers.  This module:

  * exposes a small :func:`gate_request` helper that rewrites a
    :class:`RouteRequest` to be safe for the current mode
    (caps the tier, forces local providers, etc.);
  * provides a :class:`CannedAnswerBank` — a small JSON-backed lookup
    for common intents whose answers we can return even when the
    network is down;
  * exposes :func:`pick_canned` which picks a canned answer for an
    intent.  The bank is small (≤ 200 KB on disk) and lives in
    :mod:`app.runtime.canned_answers` (a tiny JSON literal).

The bank is intentionally small and explicit.  It is *not* an
attempt to fake intelligence.  It is a polite "I'm rebooting my
brain" plus a few answers we *know* we should always be able to give
without the network (status, mode, where things are on disk, etc.).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from app.core.cost_router.types import ModelTier, RouteRequest
from app.runtime.mode import Mode

logger = logging.getLogger(__name__)


# ── Tier gating ─────────────────────────────────────────────────────

#: In ``degraded`` mode we only allow the smallest local tier.
#: In ``offline`` mode the router should not call any cloud at all —
#: it should return a canned answer or refuse.
DEGRADED_ALLOWED_TIERS: tuple[ModelTier, ...] = (ModelTier.NANO,)
OFFLINE_ALLOWED_TIERS: tuple[ModelTier, ...] = ()


def gate_request(
    request: RouteRequest, mode: Mode
) -> RouteRequest | None:
    """Rewrite a :class:`RouteRequest` for the current mode.

    Returns the (possibly rewritten) request, or ``None`` if the
    request should be served from canned answers (i.e. it would only
    have been routed to a cloud model and we are offline).

    In ``online`` mode the request is returned unchanged.
    """
    if mode == Mode.ONLINE:
        return request
    if mode == Mode.DEGRADED:
        # Force min_tier and max_tier to NANO (the local tier).
        return RouteRequest(
            task=request.task,
            input_tokens=request.input_tokens,
            max_output_tokens=request.max_output_tokens,
            requires=request.requires,
            min_tier=ModelTier.NANO,
            max_tier=ModelTier.NANO,
            budget_usd=0.0,  # local-only, no USD
            user_id=request.user_id,
            plan_id=request.plan_id,
            source_id=request.source_id,
            source_trust=request.source_trust,
        )
    # OFFLINE.
    # The router will not find a candidate (NANO is local and may not
    # be up).  Tell the caller to use canned answers.
    return None


# ── Canned answers ──────────────────────────────────────────────────


@dataclass
class CannedEntry:
    """One canned answer."""

    intent: str            # canonical lowercase intent key
    patterns: list[str]    # regex patterns (case-insensitive) that match
    text: str              # the canned answer
    priority: int = 0      # higher wins on ambiguity

    def matches(self, query: str) -> bool:
        for p in self.patterns:
            try:
                if re.search(p, query, flags=re.IGNORECASE):
                    return True
            except re.error:
                continue
        return False


# A small, opinionated list.  Keep it under 200 KB on disk; the in-memory
# size is much smaller because the JSON literals are short.
_DEFAULT_BANK: list[dict[str, Any]] = [
    {
        "intent": "status",
        "patterns": [
            r"\b(are\s+you\s+ok|how\s+are\s+you|status|alive|there\?)\b",
        ],
        "text": "I'm reachable, but my brain is in offline mode right now. Ask me something simple or check `raven mode show`.",
        "priority": 5,
    },
    {
        "intent": "mode",
        "patterns": [
            r"\b(what\s+mode|which\s+mode|current\s+mode|are\s+you\s+online|are\s+you\s+offline)\b",
        ],
        "text": "I'm in offline mode. Run `raven mode show` for details, or wait — I'll come back online when connectivity returns.",
        "priority": 5,
    },
    {
        "intent": "help",
        "patterns": [
            r"^\s*(help|what\s+can\s+you\s+do|commands?)\s*\??\s*$",
        ],
        "text": "Right now I can answer status / mode / help questions. For everything else, please reconnect — I'll catch up when I'm back.",
        "priority": 5,
    },
    {
        "intent": "thanks",
        "patterns": [r"\b(thanks|thank\s+you|ty|cheers)\b"],
        "text": "You're welcome. I'll be back to full capacity once connectivity returns.",
        "priority": 1,
    },
    {
        "intent": "greeting",
        "patterns": [r"^\s*(hi|hello|hey|yo)\b"],
        "text": "Hi — I'm online but limited. Try `raven mode show` if you'd like the details.",
        "priority": 0,
    },
]


class CannedAnswerBank:
    """In-memory bank of canned answers, with optional JSON persistence."""

    def __init__(self, entries: Iterable[CannedEntry] | None = None) -> None:
        self._entries: list[CannedEntry] = list(entries) if entries is not None else [
            CannedEntry(**d) for d in _DEFAULT_BANK
        ]
        # Sort by descending priority so the best match wins.
        self._entries.sort(key=lambda e: -e.priority)

    @classmethod
    def from_json_file(cls, path: str | Path) -> "CannedAnswerBank":
        path = Path(path)
        if not path.is_file():
            return cls()
        try:
            data = json.loads(path.read_text())
            entries = [CannedEntry(**d) for d in data]
            return cls(entries)
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            logger.warning("canned bank load failed: %s", exc)
            return cls()

    def to_json(self) -> str:
        return json.dumps(
            [
                {
                    "intent": e.intent,
                    "patterns": e.patterns,
                    "text": e.text,
                    "priority": e.priority,
                }
                for e in self._entries
            ],
            indent=2,
        )

    def add(self, entry: CannedEntry) -> None:
        self._entries.append(entry)
        self._entries.sort(key=lambda e: -e.priority)

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._entries)


def pick_canned(query: str, bank: CannedAnswerBank | None = None) -> Optional[CannedEntry]:
    """Find the best canned answer for ``query``.  ``None`` if nothing matches."""
    if not query:
        return None
    bank = bank or CannedAnswerBank()
    for entry in bank:
        if entry.matches(query):
            return entry
    return None


__all__ = [
    "CannedAnswerBank",
    "CannedEntry",
    "DEGRADED_ALLOWED_TIERS",
    "OFFLINE_ALLOWED_TIERS",
    "gate_request",
    "pick_canned",
]
