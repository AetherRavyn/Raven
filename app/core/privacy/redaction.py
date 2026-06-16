"""PII redaction — turn detected spans into placeholders.

The redactor pairs with :mod:`app.core.privacy.detection`.
It walks the text, replaces each :class:`PIIDetection` with
a placeholder chosen by a per-kind policy, and records the
mapping so a trusted caller can reverse the operation
later (e.g. when re-injecting into the user's own session).

Policies
--------

  * ``FULL``    — replace the value entirely (e.g. ``<EMAIL>``)
  * ``PARTIAL`` — keep first / last char, mask the middle
                  (e.g. ``j***@gmail.com``)
  * ``HASH``    — replace with a stable short hash of the value
  * ``TOKEN``   — replace with a unique placeholder per span
                  (e.g. ``<PII-EMAIL-1>``); supports reversal
  * ``KEEP``    — don't touch (used to debug / inspect)

The default policy is ``TOKEN`` for everything — the runtime
needs to be able to re-inject values into the user's own
context, and a token placeholder + mapping makes that safe.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from enum import Enum

from app.core.privacy.detection import PIIDetection, PIIDetector, PIIKind

logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# policies
# -------------------------------------------------------------------


class RedactionPolicy(str, Enum):
    FULL = "full"
    PARTIAL = "partial"
    HASH = "hash"
    TOKEN = "token"
    KEEP = "keep"


# Default mapping: every kind uses TOKEN (reversible).
DEFAULT_POLICIES: dict[PIIKind, RedactionPolicy] = {kind: RedactionPolicy.TOKEN for kind in PIIKind}


# -------------------------------------------------------------------
# redaction record
# -------------------------------------------------------------------


@dataclass(slots=True)
class Redaction:
    """A single redaction — what was replaced, with what."""

    detection: PIIDetection
    placeholder: str
    policy: RedactionPolicy


@dataclass(slots=True)
class RedactionResult:
    """Outcome of a redact() call."""

    text: str
    redactions: list[Redaction] = field(default_factory=list)
    # Mapping: placeholder -> original value (so callers can
    # un-redact inside trusted contexts).
    mapping: dict[str, str] = field(default_factory=dict)
    # Pre-existing tokens in the input — not redacted by us,
    # but tracked so the runtime can warn if collisions occur.
    input_tokens: list[str] = field(default_factory=list)


# -------------------------------------------------------------------
# redactor
# -------------------------------------------------------------------


@dataclass(slots=True)
class Redactor:
    """Apply per-kind policies to detected PII spans."""

    detector: PIIDetector | None = None
    policies: dict[PIIKind, RedactionPolicy] = field(default_factory=lambda: dict(DEFAULT_POLICIES))
    # Optional prefix for TOKEN placeholders, to avoid
    # collisions with user text.
    token_prefix: str = "PII"
    # When True, two occurrences of the same value yield
    # the same placeholder (stable across a session).
    stable_tokens: bool = True

    def policy_for(self, kind: PIIKind) -> RedactionPolicy:
        return self.policies.get(kind, RedactionPolicy.TOKEN)

    def set_policy(self, kind: PIIKind, policy: RedactionPolicy) -> None:
        self.policies[kind] = policy

    def redact(self, text: str) -> RedactionResult:
        if not text:
            return RedactionResult(text=text)
        detector = self.detector or PIIDetector()
        detections = detector.detect(text)
        if not detections:
            return RedactionResult(text=text)

        # Sort by start, then by descending length (longer wins on ties).
        detections.sort(key=lambda d: (d.start, -(d.end - d.start)))

        # Drop overlapping detections (keep the first by start).
        kept: list[PIIDetection] = []
        last_end = -1
        for d in detections:
            if d.start >= last_end:
                kept.append(d)
                last_end = d.end

        # Stable-token table: value -> placeholder
        token_table: dict[str, str] = {}
        # Per-kind counter for the placeholder suffix.
        counters: dict[PIIKind, int] = {k: 0 for k in PIIKind}

        out: list[str] = []
        cursor = 0
        redactions: list[Redaction] = []
        mapping: dict[str, str] = {}

        for d in kept:
            if d.start > cursor:
                out.append(text[cursor : d.start])
            policy = self.policy_for(d.kind)
            if policy == RedactionPolicy.KEEP:
                out.append(text[d.start : d.end])
                cursor = d.end
                continue
            placeholder = self._placeholder(d, policy, token_table, counters)
            out.append(placeholder)
            redactions.append(Redaction(detection=d, placeholder=placeholder, policy=policy))
            if policy == RedactionPolicy.TOKEN:
                mapping[placeholder] = d.value
            cursor = d.end
        if cursor < len(text):
            out.append(text[cursor:])

        redacted_text = "".join(out)
        return RedactionResult(
            text=redacted_text,
            redactions=redactions,
            mapping=mapping,
        )

    def _placeholder(
        self,
        d: PIIDetection,
        policy: RedactionPolicy,
        token_table: dict[str, str],
        counters: dict[PIIKind, int],
    ) -> str:
        if policy == RedactionPolicy.FULL:
            return f"<{d.kind.value.upper()}>"
        if policy == RedactionPolicy.PARTIAL:
            return d.masked
        if policy == RedactionPolicy.HASH:
            digest = hashlib.sha256(d.value.encode("utf-8")).hexdigest()[:10]
            return f"<{d.kind.value}:{digest}>"
        # TOKEN
        if self.stable_tokens and d.value in token_table:
            return token_table[d.value]
        counters[d.kind] += 1
        placeholder = f"<{self.token_prefix}-{d.kind.value.upper()}-{counters[d.kind]}>"
        token_table[d.value] = placeholder
        return placeholder

    # ---- reversal ----

    @staticmethod
    def unredact(
        text: str,
        mapping: dict[str, str],
        *,
        strict: bool = False,
    ) -> str:
        """Reverse a TOKEN redaction.  ``strict`` raises on missing keys."""
        if not mapping:
            return text
        out = text
        # Sort by placeholder length (longest first) so we
        # don't accidentally replace a prefix of a longer
        # placeholder.
        for placeholder in sorted(mapping.keys(), key=len, reverse=True):
            original = mapping[placeholder]
            if placeholder not in out:
                if strict:
                    raise KeyError(f"placeholder not found: {placeholder!r}")
                continue
            out = out.replace(placeholder, original)
        return out


# -------------------------------------------------------------------
# helpers
# -------------------------------------------------------------------


def redact_for_log(text: str, *, audit_safe: bool = False) -> str:
    """One-call helper: redact text for safe logging.

    Default behaviour is aggressive: phones, SSNs, API keys,
    bearer tokens, credit cards, opaque secrets, and emails
    are all replaced with full placeholders.  Pass
    ``audit_safe=True`` to use the conservative detector (no
    phones, no DOBs) — useful when the redaction target is a
    forensic audit log, not a runtime observability stream.
    """
    from app.core.privacy.detection import (
        detector_audit_safe,
    )

    detector = detector_audit_safe() if audit_safe else PIIDetector()
    redactor = Redactor(
        detector=detector,
        policies={
            k: RedactionPolicy.FULL
            for k in (
                PIIKind.EMAIL,
                PIIKind.SSN,
                PIIKind.CREDIT_CARD,
                PIIKind.API_KEY,
                PIIKind.BEARER_TOKEN,
                PIIKind.OPAQUE_SECRET,
                PIIKind.PHONE,
            )
        },
    )
    result = redactor.redact(text)
    return result.text
