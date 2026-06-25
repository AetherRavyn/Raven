"""Unified event envelope — Phase 2.

A single event shape used by the assistant, voice pipeline, monitoring
stack, web dashboard, MCP, and any future sidecar. All boundaries
serialize to this shape; internal in-process buses may use richer
Python objects but boundary crossings always go through the envelope.

Goals:
- **One** shape, one parser, one signer.
- **Bounded** payload: the envelope itself is ≤ 8 KB; larger bodies
  are content-addressed (the envelope carries the SHA-256 hash and
  the body lives in a content store).
- **Signed**: ed25519 envelopes. Each sidecar holds a keypair; the
  orchestrator holds the trust store. Unsigned / unknown-signature
  envelopes are dropped (never raised — see ``Envelope.verify``).
- **Schema-versioned**: every envelope declares its schema version.
  Receivers that don't understand the version reject it.
- **Lazy**: this module has *no* third-party deps at import time.
  ``nacl`` / ``cryptography`` are imported only when ``Envelope.sign``
  or ``Envelope.verify`` is called.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = "1.0"
MAX_ENVELOPE_BYTES = 8 * 1024  # 8 KB


class EventKind(str, Enum):
    """High-level event categories.

    New kinds can be added without bumping the schema version as long
    as existing fields keep their meaning.
    """

    CHAT = "chat"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ALERT = "alert"
    METRIC = "metric"
    LIFE_EVENT = "life_event"
    PLAN_STEP = "plan_step"
    AUDIT = "audit"
    HEALTH = "health"


@dataclass(slots=True)
class Header:
    """Envelope header — always present, always tiny."""

    schema: str = CURRENT_SCHEMA_VERSION
    kind: str = EventKind.CHAT.value
    # ISO-8601 UTC timestamp with millisecond precision.
    timestamp: str = ""
    # Stable correlation id (one per user-visible request chain).
    correlation_id: str = ""
    # Sidecar that produced the event.
    source: str = ""
    # Optional reply-to id (for command/response correlation).
    causation_id: str = ""
    # Idempotency key — same key on retry means same logical event.
    idempotency_key: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = _now_iso()
        if not self.idempotency_key:
            self.idempotency_key = uuid.uuid4().hex


@dataclass(slots=True)
class Envelope:
    """The signed event envelope.

    ``body`` is a small JSON-serialisable dict. For larger payloads,
    put them in a content store and reference them by hash:

        body = {"ref": "sha256:abc...", "size": 12345}
    """

    header: Header = field(default_factory=Header)
    body: dict[str, Any] = field(default_factory=dict)
    # The ed25519 signature over the canonical JSON of header+body.
    # Empty string means "unsigned" — receivers in Strict mode reject
    # these; receivers in Open mode accept and tag them.
    signature: str = ""
    # The signer's public key, hex-encoded. Empty for unsigned.
    signer_pubkey: str = ""

    # ── Serialization ────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        d = {
            "header": asdict(self.header),
            "body": self.body,
            "signature": self.signature,
            "signer_pubkey": self.signer_pubkey,
        }
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> "Envelope":
        d = json.loads(raw)
        h = d.get("header") or {}
        env = cls(
            header=Header(**h),
            body=d.get("body") or {},
            signature=d.get("signature", ""),
            signer_pubkey=d.get("signer_pubkey", ""),
        )
        return env

    def size_bytes(self) -> int:
        return len(self.to_json().encode("utf-8"))

    def assert_within_size_limit(self) -> None:
        """Raise ValueError if the envelope exceeds MAX_ENVELOPE_BYTES."""
        size = self.size_bytes()
        if size > MAX_ENVELOPE_BYTES:
            raise ValueError(
                f"envelope too large: {size} > {MAX_ENVELOPE_BYTES}; "
                f"use a content-addressed body"
            )

    # ── Signing ──────────────────────────────────────────────────

    def sign(self, signing_key: "Any") -> "Envelope":
        """Sign this envelope with an ed25519 private key.

        Returns self for chaining. Signing is a no-op if ``signing_key``
        is None (useful in tests).
        """
        if signing_key is None:
            return self
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PrivateKey,
            )

            if not isinstance(signing_key, Ed25519PrivateKey):
                raise TypeError(
                    f"expected Ed25519PrivateKey, got {type(signing_key).__name__}"
                )
            payload = _canonical_payload(self.header, self.body).encode("utf-8")
            sig = signing_key.sign(payload)
            self.signature = sig.hex()
            self.signer_pubkey = (
                signing_key.public_key().public_bytes_raw().hex()
            )
        except ImportError:
            logger.debug(
                "cryptography not installed — envelope left unsigned"
            )
        return self

    def verify(self, *, strict: bool = True) -> bool:
        """Verify the signature.

        - Returns True if signature is valid.
        - Returns False if signature is missing or invalid.
        - If ``strict`` is False, missing signature returns True
          (the receiver accepts unsigned envelopes).

        Never raises.
        """
        if not self.signature:
            return not strict
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey,
            )

            pub = bytes.fromhex(self.signer_pubkey)
            sig = bytes.fromhex(self.signature)
            payload = _canonical_payload(self.header, self.body).encode("utf-8")
            Ed25519PublicKey.from_public_bytes(pub).verify(sig, payload)
            return True
        except Exception as exc:
            logger.debug("envelope verify failed: %s", exc)
            return False


# ── Helpers ──────────────────────────────────────────────────────────


def _now_iso() -> str:
    """UTC ISO-8601 with millisecond precision (no microseconds)."""
    return (
        time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        + f".{int((time.time() % 1) * 1000):03d}Z"
    )


def _canonical_payload(header: Header, body: dict[str, Any]) -> str:
    """Deterministic JSON for signing: header fields + body, no signature."""
    d = {"header": asdict(header), "body": body}
    return json.dumps(d, separators=(",", ":"), sort_keys=True)


def make_envelope(
    *,
    kind: str | EventKind,
    source: str,
    body: dict[str, Any],
    correlation_id: str | None = None,
    causation_id: str = "",
    idempotency_key: str = "",
) -> Envelope:
    """Convenience constructor that fills in header defaults."""
    kind_str = kind.value if isinstance(kind, EventKind) else str(kind)
    return Envelope(
        header=Header(
            kind=kind_str,
            source=source,
            correlation_id=correlation_id or uuid.uuid4().hex,
            causation_id=causation_id,
            idempotency_key=idempotency_key,
        ),
        body=body,
    )


# ── Trust store (in-memory; replace with KV in production) ──────────


@dataclass(slots=True)
class TrustedSigner:
    """A public key we trust to sign envelopes."""

    name: str
    pubkey_hex: str
    added_at: float = field(default_factory=time.time)


class TrustStore:
    """In-memory trust store for envelope signers.

    Production should swap this for a HelixDB KV-backed store; the
    public API is the same.
    """

    def __init__(self) -> None:
        self._signers: dict[str, TrustedSigner] = {}

    def add(self, signer: TrustedSigner) -> None:
        self._signers[signer.name] = signer

    def remove(self, name: str) -> None:
        self._signers.pop(name, None)

    def is_trusted(self, env: Envelope) -> bool:
        if not env.signer_pubkey:
            return False
        for s in self._signers.values():
            if s.pubkey_hex == env.signer_pubkey:
                return True
        return False

    def names(self) -> list[str]:
        return list(self._signers.keys())


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "MAX_ENVELOPE_BYTES",
    "EventKind",
    "Header",
    "Envelope",
    "TrustedSigner",
    "TrustStore",
    "make_envelope",
]