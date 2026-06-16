"""Sliding-window compression for conversation transcripts.

When a conversation gets long we can't ship the entire
transcript to the LLM on every turn.  This module collapses
older turns into a summary, keeping the most recent N
verbatim.  The contract is:

  * :class:`Compressor` is configurable: window size (how
    many recent turns to keep), and a summary function.
  * The summary function is a plain
    :class:`Callable[[list[Turn], str], str]` so tests can
    use a deterministic stub.  In production, the runtime
    wires an LLM call here.
  * :meth:`Compressor.compress` returns a :class:`Compressed`
    that the runtime can store on the
    :class:`WorkingMemory` (``summary``) and replace the
    recent-turns deque with.

The summary function is intentionally pure (no I/O, no
async).  An LLM-backed summary is built by the runtime
adapter that wraps the LLM in a sync callable.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Callable

from app.core.conversation.memory import Turn

logger = logging.getLogger(__name__)


# A summary function takes the turns-to-summarize and the
# prior summary, and returns the new summary string.
SummaryFn = Callable[[list[Turn], str], str]


@dataclass(slots=True)
class Compressed:
    """Result of a compression pass."""

    summary: str
    kept_turns: list[Turn] = field(default_factory=list)
    dropped_count: int = 0
    # Diagnostics: which turns were summarized, which kept.
    summarized_turns: list[Turn] = field(default_factory=list)


@dataclass(slots=True)
class Compressor:
    """Sliding-window compressor.

    The compressor is *stateless* across calls — the caller
    passes the prior summary in and gets the new summary out.
    That makes the test story trivial and lets the runtime
    layer in checkpointing / persistence as it sees fit.
    """

    window_size: int = 6
    # The summary function.  Defaults to a deterministic
    # no-op that produces a small header + a count.
    summary_fn: SummaryFn | None = None

    def __post_init__(self) -> None:
        if self.summary_fn is None:
            self.summary_fn = deterministic_summary

    def compress(
        self,
        turns: Iterable[Turn],
        prior_summary: str = "",
    ) -> Compressed:
        all_turns = list(turns)
        if len(all_turns) <= self.window_size:
            return Compressed(
                summary=prior_summary,
                kept_turns=all_turns,
                dropped_count=0,
                summarized_turns=[],
            )

        kept = all_turns[-self.window_size :]
        summarized = all_turns[: -self.window_size]

        summary_fn = self.summary_fn
        try:
            if summary_fn is None:
                new_summary = deterministic_summary(summarized, prior_summary)
            else:
                new_summary = summary_fn(summarized, prior_summary)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "summary_fn raised: err=%s; falling back to deterministic",
                exc,
            )
            new_summary = deterministic_summary(summarized, prior_summary)

        return Compressed(
            summary=new_summary,
            kept_turns=kept,
            dropped_count=len(summarized),
            summarized_turns=summarized,
        )

    def should_compress(self, turn_count: int) -> bool:
        """Helper: should we run a compression pass right now?"""
        return turn_count > self.window_size * 2


# -------------------------------------------------------------------
# deterministic summary (default)
# -------------------------------------------------------------------


def deterministic_summary(turns: list[Turn], prior: str = "") -> str:
    """Build a small deterministic digest.

    The output is a one-line-per-turn header, suitable for
    tests and for callers that don't have an LLM handy.  The
    first line carries the prior summary so multiple
    compressions compose.
    """
    if not turns:
        return prior
    header = f"[{len(turns)} turn(s) summarized]"
    lines = [header]
    for t in turns:
        snippet = t.content.replace("\n", " ").strip()
        if len(snippet) > 120:
            snippet = snippet[:117] + "..."
        lines.append(f"- {t.role}: {snippet}")
    body = "\n".join(lines)
    if prior:
        return f"{prior}\n{body}"
    return body


# -------------------------------------------------------------------
# helpers
# -------------------------------------------------------------------


def apply_to_working_memory(
    summary: str,
    kept: list[Turn],
    *,
    maxlen: int = 20,
) -> tuple[str, deque[Turn]]:
    """Replace a working memory's recent_turns + summary atomically."""
    new_deque: deque[Turn] = deque(maxlen=maxlen)
    for t in kept:
        new_deque.append(t)
    return summary, new_deque
