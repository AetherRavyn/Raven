"""Rate-limit persistence layer.

The default :class:`InMemoryRateLimitStore` is fine for single-process
tests and the demo.  In production, swap in a SQLite- or Redis-backed
implementation.  The protocol is intentionally small so a swap is
trivial — see :class:`app.core.proactive_core.silence.RateLimitStore`.

The in-memory store is the *only* implementation we ship today; a
SQLite store will land in a follow-up commit.
"""

from app.core.proactive_core.silence import InMemoryRateLimitStore, RateLimitStore

__all__ = ["InMemoryRateLimitStore", "RateLimitStore"]
