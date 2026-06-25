"""ed25519 signing for skill manifests.

Skills are signed at creation time by their author (a workspace
key, a community key, or the RAVEN core team).  At load time the
orchestrator verifies the signature against a list of trusted
public keys.

A skill is verifiable when:

  * its ``manifest.json`` exists;
  * a ``signature`` file exists alongside it;
  * the signature, decoded from hex, validates the canonical
    manifest bytes under the corresponding public key.

Canonical manifest bytes are the UTF-8 encoding of
``manifest_to_json(m)`` *without* the ``eval_records`` field —
that's per-invocation bookkeeping that we don't want to invalidate
the signature on.  The manifest's hash is taken over
``m.to_dict()`` minus the ``eval_records`` key.

Keys are 32-byte seeds (private) and 32-byte public keys; both are
hex-encoded for transport.  The default trust store is a JSON file
at ``workspace/skill_trust_store.json`` mapping public-key-hex
to :class:`TrustedAuthor` records.  Tests pass an in-memory dict.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from app.core.skill_v2.manifest import (
    SkillManifest,
    manifest_from_json,
    manifest_to_json,
)

logger = logging.getLogger(__name__)


# ── Optional ed25519 ────────────────────────────────────────────────


def _load_ed25519():
    """Return (sign, verify, BadSignatureError) or raise ImportError.

    Uses :mod:`cryptography` if installed; otherwise returns
    HMAC-SHA256 as a fallback so dev/CI environments without
    ed25519 still have a real signature scheme.  The fallback is
    a SECURITY REDUCTION — production must use ed25519.
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # type: ignore[import-not-found]
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
        from cryptography.exceptions import InvalidSignature  # type: ignore[import-not-found]

        def _sign(priv_bytes: bytes, msg: bytes) -> bytes:
            priv = Ed25519PrivateKey.from_private_bytes(priv_bytes)
            return priv.sign(msg)

        def _verify(pub_bytes: bytes, msg: bytes, sig: bytes) -> None:
            pub = Ed25519PublicKey.from_public_bytes(pub_bytes)
            pub.verify(sig, msg)

        return _sign, _verify, InvalidSignature
    except ImportError:
        # Fallback — HMAC-SHA256 keyed by the public key bytes.
        # This is a deviation from the design but lets CI run.
        def _sign(priv_bytes: bytes, msg: bytes) -> bytes:
            return hmac.new(priv_bytes, msg, hashlib.sha256).digest()

        def _verify(pub_bytes: bytes, msg: bytes, sig: bytes) -> None:
            expected = hmac.new(pub_bytes, msg, hashlib.sha256).digest()
            if not hmac.compare_digest(expected, sig):
                raise ValueError("signature mismatch (hmac fallback)")

        return _sign, _verify, ValueError


_SIGN, _VERIFY, _BAD_SIG = _load_ed25519()


# ── Keypair generation ──────────────────────────────────────────────


def generate_keypair() -> tuple[bytes, bytes]:
    """Return (private_seed_bytes, public_key_bytes).

    With the ed25519 backend the private seed is 32 bytes and the
    public key is 32 bytes.  With the HMAC fallback the "private"
    seed is 32 random bytes and the "public key" is a 32-byte
    SHA-256 of the seed.
    """
    try:
        from cryptography.hazmat.primitives import serialization  # type: ignore[import-not-found]
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # type: ignore[import-not-found]
            Ed25519PrivateKey,
        )
        priv = Ed25519PrivateKey.generate()
        seed = priv.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pub = priv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return seed, pub
    except ImportError:
        seed = os.urandom(32)
        pub = hashlib.sha256(b"raven-pub-v1:" + seed).digest()
        return seed, pub


def pubkey_hex(pub: bytes) -> str:
    return pub.hex()


# ── Sign / verify over the canonical manifest bytes ────────────────


def _canonical_manifest_bytes(m: SkillManifest) -> bytes:
    """Bytes that get signed.  Excludes ``eval_records`` (per-invocation)."""
    d = m.to_dict()
    d.pop("eval_records", None)
    # Re-serialise via the helper so we get the same canonical form
    # the manifest writer uses.
    canon = SkillManifest.from_dict(d)
    return manifest_to_json(canon).encode("utf-8")


def sign_manifest(m: SkillManifest, private_seed: bytes) -> str:
    """Sign a manifest.  Returns the hex-encoded signature."""
    msg = _canonical_manifest_bytes(m)
    sig = _SIGN(private_seed, msg)
    return sig.hex()


def verify_manifest(
    m: SkillManifest, signature_hex: str, public_key: bytes
) -> bool:
    """Verify a manifest signature.  Returns True on success.

    Returns False (never raises) on any verification failure so
    the caller can treat it as a boolean predicate.
    """
    try:
        sig = bytes.fromhex(signature_hex)
    except ValueError:
        return False
    msg = _canonical_manifest_bytes(m)
    try:
        _VERIFY(public_key, msg, sig)
        return True
    except _BAD_SIG:  # type: ignore[misc]
        return False
    except Exception:  # noqa: BLE001
        return False


# ── Trust store ─────────────────────────────────────────────────────


@dataclass
class TrustedAuthor:
    """One trusted key."""

    pubkey_hex: str
    label: str = ""
    revoked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"pubkey_hex": self.pubkey_hex, "label": self.label, "revoked": self.revoked}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TrustedAuthor":
        return cls(
            pubkey_hex=d["pubkey_hex"],
            label=d.get("label", ""),
            revoked=bool(d.get("revoked", False)),
        )


class TrustStore:
    """In-memory trust store with optional JSON persistence."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._authors: dict[str, TrustedAuthor] = {}
        self._path: Optional[Path] = Path(path) if path else None
        if self._path is not None and self._path.is_file():
            try:
                data = json.loads(self._path.read_text())
                for entry in data.get("authors", []):
                    a = TrustedAuthor.from_dict(entry)
                    self._authors[a.pubkey_hex] = a
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("trust store load failed: %s", e)

    def add(self, pubkey_hex: str, label: str = "") -> None:
        self._authors[pubkey_hex] = TrustedAuthor(pubkey_hex=pubkey_hex, label=label)

    def revoke(self, pubkey_hex: str) -> bool:
        a = self._authors.get(pubkey_hex)
        if a is None:
            return False
        a.revoked = True
        return True

    def is_trusted(self, pubkey_hex: str) -> bool:
        a = self._authors.get(pubkey_hex)
        return a is not None and not a.revoked

    def lookup(self, pubkey_hex: str) -> Optional[TrustedAuthor]:
        return self._authors.get(pubkey_hex)

    def authors(self) -> list[TrustedAuthor]:
        return list(self._authors.values())

    def save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(
            {"authors": [a.to_dict() for a in self._authors.values()]},
            indent=2,
        ))

    def __len__(self) -> int:
        return len(self._authors)


__all__ = [
    "TrustedAuthor",
    "TrustStore",
    "generate_keypair",
    "pubkey_hex",
    "sign_manifest",
    "verify_manifest",
]