"""RAVEN skill v2 — manifest, layout, signing, registry.

Phase 9 deliverable.  A skill is a directory at::

    skills/<scope>/<name>/<version>/
        manifest.json   # required — see SkillManifest
        SKILL.md        # required
        signature       # optional — ed25519 hex
        eval.jsonl      # optional — per-invocation records

The submodules:

  * :mod:`app.core.skill_v2.manifest` — dataclasses + validation
  * :mod:`app.core.skill_v2.layout` — on-disk layout helpers
  * :mod:`app.core.skill_v2.signing` — ed25519 sign / verify + trust store
  * :mod:`app.core.skill_v2.registry` — CRUD + quarantine

The old :mod:`app.core.skill_learner` continues to work; this module
is the migration target.
"""
from app.core.skill_v2.manifest import (
    EVAL_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    EvalRecord,
    InputSchema,
    ManifestSource,
    ManifestTrust,
    OutputSchema,
    Permission,
    RiskLevel,
    SkillManifest,
    load_manifest,
    manifest_from_json,
    manifest_to_json,
    validate_manifest,
)
from app.core.skill_v2.layout import (
    VALID_SCOPES,
    SkillLayout,
    SkillLayoutRoot,
)
from app.core.skill_v2.signing import (
    TrustStore,
    TrustedAuthor,
    generate_keypair,
    pubkey_hex,
    sign_manifest,
    verify_manifest,
)
from app.core.skill_v2.registry import RegistryState, SkillRegistryV2

__all__ = [
    # manifest
    "EVAL_SCHEMA_VERSION",
    "MANIFEST_SCHEMA_VERSION",
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
    # layout
    "VALID_SCOPES",
    "SkillLayout",
    "SkillLayoutRoot",
    # signing
    "TrustedAuthor",
    "TrustStore",
    "generate_keypair",
    "pubkey_hex",
    "sign_manifest",
    "verify_manifest",
    # registry
    "RegistryState",
    "SkillRegistryV2",
]