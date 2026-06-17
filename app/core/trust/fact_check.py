"""Phase F1 — Trust & Explainability: Fact Checker.

Flags claims the agent makes that are not backed by evidence
in memory, files, web, tools, or the knowledge graph.

The checker is intentionally a thin orchestrator.  It does
not contain an LLM or a retrieval engine — those are
injected by the runtime.  The interface is just:

* :class:`EvidenceProvider` — a callable that takes a claim
  and returns a list of :class:`Citation` objects.
* :class:`ClaimExtractor` — splits text into individual claims
  (a heuristic splitter; the runtime can swap in an LLM-based
  extractor).

Typical usage::

    fc = FactChecker()
    claims = fc.extract_claims(llm_text)
    results = await fc.check_text(llm_text, evidence_provider=memory_search)
    for r in results:
        if not r.supported:
            log.warning("unsupported claim: %s", r.claim)

The :meth:`FactChecker.check_text` is async because real-world
evidence providers are async (memory search, web fetch, tool
calls).  A sync version is also available for tests.
"""

from __future__ import annotations

import asyncio
import re
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.trust.citations import Citation, CitationSource


# -- evidence provider protocol ------------------------------------------------

EvidenceProvider = Callable[[str], "list[Citation] | Awaitable[list[Citation]]"]
"""Signature for any function that returns evidence for a claim.

A sync or async callable.  The fact checker awaits the result
when needed; sync providers are wrapped automatically.
"""


# -- claim data model ----------------------------------------------------------


@dataclass(slots=True)
class Claim:
    """A single assertion extracted from a larger text."""

    text: str
    index: int  # 0-based position in the original text
    start: int  # char offset in the original text
    end: int  # char offset in the original text (exclusive)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "index": self.index,
            "start": self.start,
            "end": self.end,
        }


@dataclass(slots=True)
class FactCheckResult:
    """Outcome of checking a single claim."""

    claim: Claim
    supported: bool
    confidence: float  # 0.0–1.0; how sure we are about the verdict
    evidence: list[Citation] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim.to_dict(),
            "supported": self.supported,
            "confidence": self.confidence,
            "evidence": [c.short() for c in self.evidence],
            "reason": self.reason,
        }

    @property
    def has_evidence(self) -> bool:
        return bool(self.evidence)


@dataclass(slots=True)
class FactCheckReport:
    """Aggregate result for a whole text."""

    text: str
    results: list[FactCheckResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def supported_count(self) -> int:
        return sum(1 for r in self.results if r.supported)

    @property
    def unsupported_count(self) -> int:
        return sum(1 for r in self.results if not r.supported)

    @property
    def support_rate(self) -> float:
        if not self.results:
            return 1.0
        return self.supported_count / len(self.results)

    def unsupported(self) -> list[FactCheckResult]:
        """Return only the unsupported results."""
        return [r for r in self.results if not r.supported]

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "total": self.total,
            "supported": self.supported_count,
            "unsupported": self.unsupported_count,
            "support_rate": self.support_rate,
            "results": [r.to_dict() for r in self.results],
        }


# -- claim extraction ----------------------------------------------------------


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
"""Naive sentence splitter.  Good enough for LLM-generated prose."""


def _default_extract_claims(text: str) -> list[Claim]:
    """Split ``text`` into sentences, dropping empties and whitespace."""
    parts = _SENTENCE_END.split(text.strip())
    claims: list[Claim] = []
    cursor = 0
    for idx, part in enumerate(parts):
        s = part.strip()
        if not s:
            continue
        start = text.find(s, cursor)
        end = start + len(s)
        cursor = end
        claims.append(Claim(text=s, index=idx, start=start, end=end))
    return claims


# -- fact checker --------------------------------------------------------------


class FactChecker:
    """Orchestrate claim extraction + evidence lookup + verdict."""

    def __init__(
        self,
        *,
        min_confidence: float = 0.4,
        min_evidence: int = 1,
    ) -> None:
        self._lock = threading.RLock()
        self._min_confidence = min_confidence
        self._min_evidence = min_evidence

    # -- configuration ---------------------------------------------------

    @property
    def min_confidence(self) -> float:
        return self._min_confidence

    @property
    def min_evidence(self) -> int:
        return self._min_evidence

    # -- claim extraction ------------------------------------------------

    def extract_claims(self, text: str) -> list[Claim]:
        """Split ``text`` into individual claims (default: sentence split)."""
        return _default_extract_claims(text)

    # -- single-claim check ----------------------------------------------

    def _score_claim(
        self, claim: Claim, evidence: list[Citation]
    ) -> FactCheckResult:
        """Decide whether ``claim`` is supported by ``evidence``."""
        if not evidence:
            return FactCheckResult(
                claim=claim,
                supported=False,
                confidence=0.9,
                evidence=[],
                reason="no evidence found",
            )
        if len(evidence) < self._min_evidence:
            return FactCheckResult(
                claim=claim,
                supported=False,
                confidence=0.7,
                evidence=evidence,
                reason=f"only {len(evidence)} evidence (need {self._min_evidence})",
            )
        # Heuristic: more evidence + diverse sources → higher confidence.
        unique_sources = {e.source for e in evidence}
        confidence = min(0.6 + 0.1 * len(unique_sources) + 0.05 * len(evidence), 0.99)
        supported = confidence >= self._min_confidence
        reason = (
            f"{len(evidence)} citations across {len(unique_sources)} sources"
        )
        return FactCheckResult(
            claim=claim,
            supported=supported,
            confidence=round(confidence, 3),
            evidence=evidence,
            reason=reason,
        )

    async def check_claim(
        self,
        claim_text: str,
        *,
        evidence_provider: EvidenceProvider,
    ) -> FactCheckResult:
        """Check a single claim string."""
        claim = Claim(text=claim_text, index=0, start=0, end=len(claim_text))
        evidence = await _resolve_evidence(evidence_provider, claim_text)
        return self._score_claim(claim, evidence)

    # -- full-text check ------------------------------------------------

    async def check_text(
        self,
        text: str,
        *,
        evidence_provider: EvidenceProvider,
    ) -> FactCheckReport:
        """Extract every claim from ``text`` and check each one."""
        claims = self.extract_claims(text)
        results: list[FactCheckResult] = []
        for claim in claims:
            evidence = await _resolve_evidence(evidence_provider, claim.text)
            results.append(self._score_claim(claim, evidence))
        return FactCheckReport(text=text, results=results)

    def check_text_sync(
        self,
        text: str,
        *,
        evidence_provider: EvidenceProvider,
    ) -> FactCheckReport:
        """Sync version of :meth:`check_text` — for tests and CLI use."""
        return asyncio.run(self.check_text(text, evidence_provider=evidence_provider))


# -- helpers -------------------------------------------------------------------


async def _resolve_evidence(
    provider: EvidenceProvider, claim_text: str
) -> list[Citation]:
    """Call a sync or async evidence provider, normalising the result."""
    result = provider(claim_text)
    if asyncio.iscoroutine(result):
        result = await result
    if not isinstance(result, list):
        return []
    return result


# -- module-level singleton helpers --------------------------------------------


_DEFAULT_CHECKER: FactChecker | None = None
_LOCK = threading.RLock()


def get_default_fact_checker() -> FactChecker:
    """Return the process-singleton :class:`FactChecker`."""
    global _DEFAULT_CHECKER
    with _LOCK:
        if _DEFAULT_CHECKER is None:
            _DEFAULT_CHECKER = FactChecker()
        return _DEFAULT_CHECKER


def set_default_fact_checker(checker: FactChecker | None) -> None:
    """Replace the singleton.  Pass ``None`` to clear."""
    global _DEFAULT_CHECKER
    with _LOCK:
        _DEFAULT_CHECKER = checker


def reset_default_fact_checker() -> None:
    """Drop the singleton.  Tests use this between cases."""
    global _DEFAULT_CHECKER
    with _LOCK:
        _DEFAULT_CHECKER = None


# -- convenience: build a simple sync provider from a dict ---------------------


def dict_evidence_provider(
    evidence_map: dict[str, list[Citation]],
) -> Callable[[str], list[Citation]]:
    """Build a sync evidence provider from a ``claim → citations`` map.

    Useful for tests and for bootstrapping without a real memory
    backend.  Matches whole-phrase first, then falls back to
    substring match.
    """
    def _lookup(claim: str) -> list[Citation]:
        # Exact match.
        if claim in evidence_map:
            return list(evidence_map[claim])
        # Substring match: any key that appears in the claim.
        for key, cites in evidence_map.items():
            if key and key in claim:
                return list(cites)
        return []
    return _lookup


__all__ = [
    "Claim",
    "EvidenceProvider",
    "FactCheckReport",
    "FactCheckResult",
    "FactChecker",
    "dict_evidence_provider",
    "get_default_fact_checker",
    "reset_default_fact_checker",
    "set_default_fact_checker",
]

# Avoid unused-import lint for CitationSource (re-exported for callers
# who want to build providers with the right enum).
_ = CitationSource
