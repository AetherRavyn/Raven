"""Quick Command palette for the companion.

The palette is the ⌘K / Ctrl-K command box.  The user types a few
characters and the palette suggests intents it can route.  An
"intent" is a short string (e.g. ``"weather"``, ``"morning_briefing"``,
``"send_email"``) that the orchestrator knows how to dispatch.

Matching strategy:
  1. Exact match on intent name (case-insensitive).
  2. Prefix match.
  3. Substring match on intent OR any keyword.
  4. Fuzzy match — sorted by edit distance, capped at 3 results.

The palette is a pure function of (query, index) so it can run
inside the renderer (Tauri) or the server (this Python module).
The Python implementation is the source of truth — the native ports
replicate the same scoring in Rust/Swift.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(slots=True)
class IntentEntry:
    """One row in the command palette."""

    intent: str
    title: str
    keywords: list[str] = field(default_factory=list)
    # Free-form args the orchestrator will see.  Optional.
    default_args: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "title": self.title,
            "keywords": list(self.keywords),
            "default_args": dict(self.default_args),
        }


# Built-in default index.  Real deployments load from the orchestrator
# via a Subscribe/Event on the "intents" channel.
DEFAULT_INTENTS: list[IntentEntry] = [
    IntentEntry("weather", "Check the weather", ["forecast", "rain", "temperature"]),
    IntentEntry("morning_briefing", "Morning briefing", ["briefing", "today", "news"]),
    IntentEntry("send_email", "Send an email", ["email", "gmail", "compose"]),
    IntentEntry("search_web", "Search the web", ["search", "google", "lookup"]),
    IntentEntry(
        "summarize", "Summarize the last conversation", ["tldr", "summary", "recap"]
    ),
    IntentEntry(
        "play_music", "Play music", ["music", "spotify", "song", "playlist"]
    ),
    IntentEntry("set_reminder", "Set a reminder", ["remind", "alarm", "todo"]),
    IntentEntry(
        "list_tasks", "List today's tasks", ["tasks", "todos", "agenda"]
    ),
    IntentEntry(
        "anomaly_digest",
        "Show the latest anomalies",
        ["anomalies", "alerts", "monitor"],
    ),
    IntentEntry(
        "open_dashboard", "Open the web dashboard", ["dashboard", "web", "ui"]
    ),
]


@dataclass(slots=True)
class Suggestion:
    entry: IntentEntry
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, **self.entry.to_dict()}


def _normalize(s: str) -> str:
    return (s or "").strip().lower()


def _edit_distance(a: str, b: str, cap: int = 4) -> int:
    """Bounded Levenshtein distance.  Stops early if distance > cap.

    This is a deliberately simple DP — good enough for the palette,
    where queries are short (≤ 32 chars) and we want a fast path that
    doesn't allocate a 32×32 matrix on every keystroke.
    """
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > cap:
        return cap + 1
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * lb
        row_min = cur[0]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(
                prev[j] + 1,        # deletion
                cur[j - 1] + 1,     # insertion
                prev[j - 1] + cost,  # substitution
            )
            if cur[j] < row_min:
                row_min = cur[j]
        if row_min > cap:
            return cap + 1
        prev = cur
    return prev[lb]


class CommandPalette:
    """Suggest intents for a partial query."""

    def __init__(self, intents: Iterable[IntentEntry] | None = None) -> None:
        self._intents: list[IntentEntry] = list(intents) if intents is not None else list(DEFAULT_INTENTS)

    def set_intents(self, intents: Iterable[IntentEntry]) -> None:
        """Replace the index.  Used when the orchestrator pushes a new
        intents list via the Subscribe/Event channel."""
        self._intents = list(intents)

    def add_intent(self, entry: IntentEntry) -> None:
        self._intents.append(entry)

    def intents(self) -> list[IntentEntry]:
        return list(self._intents)

    def suggest(self, query: str, limit: int = 5) -> list[Suggestion]:
        """Return up to ``limit`` suggestions, best match first."""
        q = _normalize(query)
        if not q:
            return [Suggestion(e, 1.0) for e in self._intents[:limit]]
        scored: list[Suggestion] = []
        for entry in self._intents:
            score = self._score(q, entry)
            if score > 0:
                scored.append(Suggestion(entry, score))
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:limit]

    @staticmethod
    def _score(q: str, entry: IntentEntry) -> float:
        intent = _normalize(entry.intent)
        if intent == q:
            return 1.0
        if intent.startswith(q):
            return 0.9
        if q in intent:
            return 0.7
        for kw in entry.keywords:
            kw_n = _normalize(kw)
            if kw_n == q:
                return 0.85
            if kw_n.startswith(q):
                return 0.75
            if q in kw_n:
                return 0.55
        # Fuzzy on the intent name; cap edit distance to keep noise out.
        d = _edit_distance(q, intent, cap=3)
        if d <= 3:
            return max(0.1, 0.5 - 0.1 * d)
        return 0.0


__all__ = [
    "IntentEntry",
    "Suggestion",
    "CommandPalette",
    "DEFAULT_INTENTS",
]