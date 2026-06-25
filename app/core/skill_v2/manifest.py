"""Skill manifest dataclasses + validation.

The manifest is the contract a skill publishes to the orchestrator.
The orchestrator refuses to load a skill that:

  * has a malformed manifest (validation fails);
  * is unsigned and ``strict_signing`` is on;
  * declares a permission it doesn't have;
  * has a version that doesn't follow semver.

Validation is pure: a :func:`validate_manifest` call returns a list
of human-readable errors (empty = OK).  No I/O.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Optional


MANIFEST_SCHEMA_VERSION = "1.0"
EVAL_SCHEMA_VERSION = "1.0"

# Semver — only the shape is enforced; numeric ranges are not.
_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)


class RiskLevel(str, Enum):
    """How dangerous is invoking this skill?

    ``low``      — read-only / pure compute.
    ``medium``   — sends messages, writes to user's own files.
    ``high``     — mutates external systems, spends money.
    ``critical`` — irreversible, security-sensitive.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ManifestSource(str, Enum):
    """Where the skill came from."""

    BUNDLED = "bundled"     # ships with RAVEN
    LEARNED = "learned"     # produced by SkillLearner from traces
    COMMUNITY = "community"  # downloaded from the community registry
    INSTALLED = "installed"  # manually dropped by the user


class ManifestTrust(str, Enum):
    """How much the orchestrator should trust the skill author."""

    OFFICIAL = "official"   # signed by RAVEN core team
    VERIFIED = "verified"   # signed by a known community author
    WORKSPACE = "workspace"  # signed by the local user
    UNTRUSTED = "untrusted"  # unsigned or unverified


class Permission(str, Enum):
    """Permissions a skill may request."""

    NETWORK_EGRESS = "network.egress"
    NETWORK_INGRESS = "network.ingress"
    FILESYSTEM_READ = "filesystem.read"
    FILESYSTEM_WRITE = "filesystem.write"
    PROCESS_SPAWN = "process.spawn"
    SECRETS_READ = "secrets.read"
    SECRETS_WRITE = "secrets.write"
    USER_DATA_READ = "user_data.read"
    USER_DATA_WRITE = "user_data.write"
    MESSAGING_SEND = "messaging.send"
    PAYMENTS = "payments"


@dataclass
class InputSchema:
    """One input parameter the skill accepts."""

    name: str
    type: str = "string"  # "string" | "number" | "boolean" | "object" | "array"
    required: bool = True
    description: str = ""
    default: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "required": self.required,
            "description": self.description,
            "default": self.default,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "InputSchema":
        return cls(
            name=d["name"],
            type=d.get("type", "string"),
            required=bool(d.get("required", True)),
            description=d.get("description", ""),
            default=d.get("default"),
        )


@dataclass
class OutputSchema:
    """One output field the skill produces."""

    name: str
    type: str = "string"
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "OutputSchema":
        return cls(
            name=d["name"],
            type=d.get("type", "string"),
            description=d.get("description", ""),
        )


@dataclass
class EvalRecord:
    """One row in the per-invocation eval log.

    A skill graduates from ``learned`` to ``enabled`` once it has
    :attr:`success_count` records with ``passed=True``.
    """

    invocation_id: str
    passed: bool
    score: float = 0.0
    latency_ms: int = 0
    timestamp: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "invocation_id": self.invocation_id,
            "passed": self.passed,
            "score": self.score,
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EvalRecord":
        return cls(
            invocation_id=d["invocation_id"],
            passed=bool(d.get("passed", False)),
            score=float(d.get("score", 0.0)),
            latency_ms=int(d.get("latency_ms", 0)),
            timestamp=d.get("timestamp", ""),
            note=d.get("note", ""),
        )


@dataclass
class SkillManifest:
    """The full skill contract."""

    # Identity
    name: str
    version: str
    author: str = ""
    description: str = ""
    # Provenance
    source: ManifestSource = ManifestSource.BUNDLED
    trust: ManifestTrust = ManifestTrust.WORKSPACE
    # Capabilities
    permissions: list[Permission] = field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    inputs: list[InputSchema] = field(default_factory=list)
    outputs: list[OutputSchema] = field(default_factory=list)
    # Promotion
    promotion_threshold: int = 20
    # Free-form tags
    tags: list[str] = field(default_factory=list)
    # Eval results (filled in by the registry as the skill is invoked)
    eval_records: list[EvalRecord] = field(default_factory=list)
    # Schema version (set on write; checked on read)
    schema_version: str = MANIFEST_SCHEMA_VERSION

    # ── serialization ───────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "source": self.source.value,
            "trust": self.trust.value,
            "permissions": [p.value for p in self.permissions],
            "risk_level": self.risk_level.value,
            "inputs": [i.to_dict() for i in self.inputs],
            "outputs": [o.to_dict() for o in self.outputs],
            "promotion_threshold": self.promotion_threshold,
            "tags": list(self.tags),
            "eval_records": [r.to_dict() for r in self.eval_records],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SkillManifest":
        return cls(
            name=d["name"],
            version=d["version"],
            author=d.get("author", ""),
            description=d.get("description", ""),
            source=ManifestSource(d.get("source", "bundled")),
            trust=ManifestTrust(d.get("trust", "workspace")),
            permissions=[Permission(p) for p in d.get("permissions", [])],
            risk_level=RiskLevel(d.get("risk_level", "low")),
            inputs=[InputSchema.from_dict(i) for i in d.get("inputs", [])],
            outputs=[OutputSchema.from_dict(o) for o in d.get("outputs", [])],
            promotion_threshold=int(d.get("promotion_threshold", 20)),
            tags=list(d.get("tags", [])),
            eval_records=[EvalRecord.from_dict(r) for r in d.get("eval_records", [])],
            schema_version=d.get("schema_version", MANIFEST_SCHEMA_VERSION),
        )

    # ── convenience ─────────────────────────────────────────────

    def success_count(self) -> int:
        return sum(1 for r in self.eval_records if r.passed)

    def is_promoted(self) -> bool:
        return self.success_count() >= self.promotion_threshold

    def eval_pass_rate(self) -> float:
        if not self.eval_records:
            return 0.0
        return self.success_count() / len(self.eval_records)


# ── Validation ──────────────────────────────────────────────────────


def validate_manifest(
    m: SkillManifest, *, strict_signing: bool = False
) -> list[str]:
    """Return a list of human-readable validation errors.

    Empty list means the manifest is valid.  The optional
    ``strict_signing`` flag upgrades a missing signature to a
    validation error (the manifest dataclass doesn't carry a
    signature field — that's stored alongside on disk — but the
    caller can pre-check it and pass that info in via this flag).
    """
    errs: list[str] = []
    if not m.name or not isinstance(m.name, str):
        errs.append("name: must be a non-empty string")
    elif not _is_valid_identifier(m.name):
        errs.append(
            f"name: {m.name!r} must be lowercase, alphanumeric, dots/dashes"
        )
    if not _SEMVER_RE.match(m.version or ""):
        errs.append(
            f"version: {m.version!r} must follow semver (e.g. 1.0.0)"
        )
    if not isinstance(m.author, str):
        errs.append("author: must be a string")
    if m.promotion_threshold < 0:
        errs.append("promotion_threshold: must be ≥ 0")
    if m.promotion_threshold > 1000:
        errs.append("promotion_threshold: suspiciously large (> 1000)")
    # Input names must be unique.
    seen_in: set[str] = set()
    for inp in m.inputs:
        if inp.name in seen_in:
            errs.append(f"inputs: duplicate name {inp.name!r}")
        seen_in.add(inp.name)
        if not _is_valid_identifier(inp.name):
            errs.append(f"inputs: {inp.name!r} is not a valid identifier")
    seen_out: set[str] = set()
    for out in m.outputs:
        if out.name in seen_out:
            errs.append(f"outputs: duplicate name {out.name!r}")
        seen_out.add(out.name)
    # A critical-risk skill must request at least one permission so
    # the policy engine can audit what it touches.
    if m.risk_level is RiskLevel.CRITICAL and not m.permissions:
        errs.append("risk_level=critical requires at least one permission")
    # Tags must be strings.
    for tag in m.tags:
        if not isinstance(tag, str):
            errs.append(f"tags: {tag!r} is not a string")
    if strict_signing and m.trust is ManifestTrust.UNTRUSTED:
        errs.append("trust=untrusted rejected in strict_signing mode")
    return errs


def _is_valid_identifier(s: str) -> bool:
    return bool(re.match(r"^[a-z0-9][a-z0-9._-]*$", s or ""))


# ── JSON helpers ────────────────────────────────────────────────────


def manifest_to_json(m: SkillManifest, *, indent: int | None = 2) -> str:
    return json.dumps(m.to_dict(), indent=indent, sort_keys=True)


def manifest_from_json(text: str) -> SkillManifest:
    return SkillManifest.from_dict(json.loads(text))


def load_manifest(path: str) -> SkillManifest:
    """Read a manifest from a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return manifest_from_json(f.read())


__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "EVAL_SCHEMA_VERSION",
    "RiskLevel",
    "ManifestSource",
    "ManifestTrust",
    "Permission",
    "InputSchema",
    "OutputSchema",
    "EvalRecord",
    "SkillManifest",
    "validate_manifest",
    "manifest_to_json",
    "manifest_from_json",
    "load_manifest",
]