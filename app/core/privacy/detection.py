"""PII detection — find sensitive spans in text.

The detector is a stateless list of regex patterns, each
tagged with a :class:`PIIKind` and a confidence score.
The runtime can layer an ML model on top later; for now
this is fully deterministic so tests are stable.

Coverage
--------

The default rule set covers the most common PII shapes
that show up in real conversations:

  * email addresses
  * phone numbers (US / international, with separators)
  * US Social Security numbers
  * credit-card-shaped numbers (Luhn-validated, so the
    detector doesn't trip on every 16-digit string)
  * IPv4 addresses
  * long hex / base64 tokens (API keys, JWT bodies)
  * bearer tokens (``Bearer <token>``)
  * dates of birth (common ``YYYY-MM-DD`` form)

Custom patterns
---------------

A caller can pass a list of :class:`Pattern` to the
detector at construction time, or call :meth:`register`
to add patterns after the fact.  Patterns are pure data
and live in the detector (no global state).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# kinds
# -------------------------------------------------------------------


class PIIKind(str, Enum):
    EMAIL = "email"
    PHONE = "phone"
    SSN = "ssn"
    CREDIT_CARD = "credit_card"
    IP_ADDRESS = "ip"
    API_KEY = "api_key"
    BEARER_TOKEN = "bearer_token"
    DATE_OF_BIRTH = "dob"
    # Generic catch-all for "looks like a secret"; assigned
    # when a long opaque string matches a heuristic.
    OPAQUE_SECRET = "opaque_secret"


# -------------------------------------------------------------------
# detection
# -------------------------------------------------------------------


@dataclass(slots=True)
class PIIDetection:
    """A single PII span found in a text."""

    kind: PIIKind
    value: str
    start: int
    end: int
    confidence: float
    pattern_id: str

    def __len__(self) -> int:  # pragma: no cover - convenience
        return self.end - self.start

    @property
    def masked(self) -> str:
        """Partial mask: keep first/last char where useful."""
        v = self.value
        if self.kind in (PIIKind.EMAIL,):
            local, _, domain = v.partition("@")
            if local and domain:
                head = local[0] if local else ""
                tail = local[-1] if len(local) > 1 else ""
                return f"{head}***{tail}@{domain}"
        if self.kind in (
            PIIKind.PHONE,
            PIIKind.SSN,
            PIIKind.CREDIT_CARD,
            PIIKind.API_KEY,
            PIIKind.BEARER_TOKEN,
            PIIKind.OPAQUE_SECRET,
        ):
            if len(v) <= 4:
                return "*" * len(v)
            return f"{v[:2]}{'*' * (len(v) - 4)}{v[-2:]}"
        if self.kind == PIIKind.IP_ADDRESS:
            parts = v.split(".")
            if len(parts) == 4:
                return f"{parts[0]}.***.***.{parts[3]}"
        if self.kind == PIIKind.DATE_OF_BIRTH:
            return "****-**-**"
        return "*" * min(len(v), 8)


@dataclass(slots=True)
class Pattern:
    """A single detection rule."""

    pattern_id: str
    kind: PIIKind
    regex: str
    confidence: float = 0.9
    # Some patterns need post-validation (e.g. Luhn for cards).
    validator: str | None = None  # name of a built-in validator

    def compiled(self) -> re.Pattern[str]:
        return re.compile(self.regex)


# Built-in validators
def _luhn(number: str) -> bool:
    """Standard Luhn check — used to filter credit-card false positives."""
    digits = [int(d) for d in number if d.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


_VALIDATORS: dict[str, Any] = {
    "luhn": _luhn,
}


# -------------------------------------------------------------------
# detector
# -------------------------------------------------------------------


_DEFAULT_PATTERNS: list[Pattern] = [
    Pattern(
        pattern_id="email.basic",
        kind=PIIKind.EMAIL,
        regex=r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}\b",
        confidence=0.95,
    ),
    Pattern(
        pattern_id="phone.us",
        kind=PIIKind.PHONE,
        regex=r"\b(?:\+?1[\s\-.])?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}\b",
        confidence=0.7,
    ),
    Pattern(
        pattern_id="ssn.us",
        kind=PIIKind.SSN,
        regex=r"\b\d{3}-\d{2}-\d{4}\b",
        confidence=0.95,
    ),
    Pattern(
        pattern_id="credit_card.dashed",
        kind=PIIKind.CREDIT_CARD,
        regex=r"\b\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}\b",
        confidence=0.9,
        validator="luhn",
    ),
    Pattern(
        pattern_id="credit_card.solid",
        kind=PIIKind.CREDIT_CARD,
        regex=r"\b\d{16}\b",
        confidence=0.6,
        validator="luhn",
    ),
    Pattern(
        pattern_id="ip.v4",
        kind=PIIKind.IP_ADDRESS,
        regex=r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        confidence=0.85,
    ),
    Pattern(
        pattern_id="api_key.openai",
        kind=PIIKind.API_KEY,
        regex=r"\bsk-[A-Za-z0-9_\-]{20,}\b",
        confidence=0.95,
    ),
    Pattern(
        pattern_id="api_key.anthropic",
        kind=PIIKind.API_KEY,
        regex=r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b",
        confidence=0.95,
    ),
    Pattern(
        pattern_id="api_key.aws",
        kind=PIIKind.API_KEY,
        regex=r"\bAKIA[0-9A-Z]{16}\b",
        confidence=0.95,
    ),
    Pattern(
        pattern_id="api_key.github",
        kind=PIIKind.API_KEY,
        regex=r"\bgh[pousr]_[A-Za-z0-9]{30,}\b",
        confidence=0.95,
    ),
    Pattern(
        pattern_id="api_key.google",
        kind=PIIKind.API_KEY,
        regex=r"\bAIza[0-9A-Za-z_\-]{30,}\b",
        confidence=0.9,
    ),
    Pattern(
        pattern_id="bearer.basic",
        kind=PIIKind.BEARER_TOKEN,
        regex=r"\bBearer\s+[A-Za-z0-9._\-]{20,}\b",
        confidence=0.95,
    ),
    Pattern(
        pattern_id="dob.iso",
        kind=PIIKind.DATE_OF_BIRTH,
        regex=r"\b(19|20)\d{2}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\b",
        confidence=0.5,
    ),
    Pattern(
        pattern_id="opaque.long_hex",
        kind=PIIKind.OPAQUE_SECRET,
        regex=r"\b[a-f0-9]{40,}\b",
        confidence=0.55,
    ),
]


@dataclass(slots=True)
class PIIDetector:
    """Stateless detector over a list of patterns."""

    patterns: list[Pattern] = field(default_factory=list)
    # IPs are very common in logs and rarely actual PII.  Default
    # off; callers can opt in per use case.
    detect_ip: bool = False
    # Limit detection to a subset of kinds.
    enabled_kinds: set[PIIKind] | None = None
    # Pre-compiled patterns, populated in __post_init__.
    _compiled: list[tuple[Pattern, re.Pattern[str]]] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        if not self.patterns:
            self.patterns = list(_DEFAULT_PATTERNS)
        self._compiled = [(p, p.compiled()) for p in self.patterns]

    def register(self, pattern: Pattern) -> None:
        """Add a custom pattern after construction."""
        self.patterns.append(pattern)
        self._compiled.append((pattern, pattern.compiled()))

    def detect(self, text: str) -> list[PIIDetection]:
        """Return all detections, sorted by start offset."""
        if not text:
            return []
        out: list[PIIDetection] = []
        for pattern, regex in self._compiled:
            if self.enabled_kinds is not None and pattern.kind not in self.enabled_kinds:
                continue
            if pattern.kind == PIIKind.IP_ADDRESS and not self.detect_ip:
                continue
            for m in regex.finditer(text):
                value = m.group(0)
                if pattern.validator is not None:
                    fn = _VALIDATORS.get(pattern.validator)
                    if fn is None or not fn(value):
                        continue
                out.append(
                    PIIDetection(
                        kind=pattern.kind,
                        value=value,
                        start=m.start(),
                        end=m.end(),
                        confidence=pattern.confidence,
                        pattern_id=pattern.pattern_id,
                    )
                )
        # Sort by start; on ties, longer span wins.
        out.sort(key=lambda d: (d.start, -(d.end - d.start)))
        return out

    def kinds_present(self, text: str) -> set[PIIKind]:
        return {d.kind for d in self.detect(text)}


def detector_with_kinds(*kinds: PIIKind) -> PIIDetector:
    """Convenience: build a detector limited to the given kinds."""
    return PIIDetector(enabled_kinds=set(kinds))


def detector_audit_safe() -> PIIDetector:
    """A detector configured for audit log redaction:
    high-precision, no IPs, no DOBs, only the high-confidence patterns."""
    return PIIDetector(
        enabled_kinds={
            PIIKind.EMAIL,
            PIIKind.SSN,
            PIIKind.CREDIT_CARD,
            PIIKind.API_KEY,
            PIIKind.BEARER_TOKEN,
        },
    )


def all_default_kinds() -> Iterable[PIIKind]:
    """Return the set of kinds the default detector knows about."""
    seen: set[PIIKind] = set()
    for p in _DEFAULT_PATTERNS:
        seen.add(p.kind)
    return seen
