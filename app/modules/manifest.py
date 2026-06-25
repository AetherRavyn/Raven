"""Unified Module Manifest schema and raw-mapping parsing.

This module defines the ``ModuleManifest`` dataclass (the full unified schema:
the legacy ``module.yaml`` fields plus the platform's additive ``provides``,
``required_permissions``, ``required_secrets``, and ``compatibility`` sections)
together with the schema constants and ``parse_manifest``.

``parse_manifest`` builds a typed ``ModuleManifest`` from a raw mapping. The raw
mapping is the manifest already loaded by ``SkillRegistry`` (so the four
recognized manifest filenames and the precedence order are unchanged), and the
legacy fields keep the exact meaning and default values ``SkillRegistry`` gives
them (Req 1.1, 1.6, 14.1). The additive fields are parsed from the same mapping
and default to empty/neutral values when absent (Req 1.2, 1.3, 1.4, 1.5).

Manifest *validation* (required-field, format, schema, and version checks) lives
in ``validate_manifest`` (task 2.2); this module only parses.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.modules.models import (
    Compatibility,
    DependencySpec,
    ProvidesEntry,
    ProvidesType,
    ValidationResult,
)

logger = logging.getLogger(__name__)

# Manifest schema versions the Module_Platform understands (Req 3.5).
SUPPORTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({"1.0"})

# The only trust levels a manifest may declare (Req 1.7, 3.3).
VALID_TRUST_LEVELS: frozenset[str] = frozenset({"system", "workspace", "community"})

# The contribution types a single ``provides`` entry may declare (Req 1.2).
VALID_PROVIDES_TYPES: frozenset[str] = frozenset(
    {
        "tool",
        "agent",
        "skill",
        "event_source",
        "anomaly_detector",
        "proactive_reaction",
        "ui_surface",
    }
)

# Fields that must be present for a manifest to validate (Req 1.1, 3.1).
REQUIRED_FIELDS: tuple[str, ...] = (
    "schema_version",
    "module_id",
    "display_name",
    "version",
    "category",
    "description",
)

# A module_id is lowercase alphanumeric segments joined by single dots/underscores.
_MODULE_ID_RE = re.compile(r"^[a-z0-9]+([._][a-z0-9]+)*$")
# A version is a three-part semantic version MAJOR.MINOR.PATCH.
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass(slots=True)
class ModuleManifest:
    """The unified manifest describing everything a module provides.

    The first block of fields are the existing skill-manifest fields, kept with
    the same meaning and defaults ``SkillRegistry`` applies (Req 1.6, 14.1). The
    second block is additive: the capability bundle (``provides``) plus the
    permission, secret, and compatibility declarations (Req 1.2-1.5).
    """

    # ── Existing skill-manifest fields ──
    schema_version: str
    module_id: str
    display_name: str
    version: str
    category: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    trust_level: str = "workspace"
    enabled_by_default: bool = False
    stability: str = "experimental"
    origin: str = "community"
    triggers: list[dict[str, Any]] = field(default_factory=list)
    dependencies: list[DependencySpec] = field(default_factory=list)
    # ── Additive Module_Platform fields ──
    provides: list[ProvidesEntry] = field(default_factory=list)
    required_permissions: list[str] = field(default_factory=list)  # Req 1.3
    required_secrets: list[str] = field(default_factory=list)  # Req 1.4
    compatibility: Compatibility = field(default_factory=Compatibility)  # Req 1.5
    manifest_path: str = ""


def parse_manifest(raw: Mapping[str, Any], manifest_path: str | Path) -> ModuleManifest:
    """Build a ``ModuleManifest`` from a raw mapping loaded by ``SkillRegistry``.

    Legacy fields are read with the same fallback defaults ``SkillRegistry``
    applies so a parsed manifest matches the registry's interpretation (Req 1.6,
    14.1). The additive ``provides``, ``required_permissions``,
    ``required_secrets``, and ``compatibility`` fields are parsed from the same
    mapping and default to empty/neutral values when absent (Req 1.2-1.5).
    """
    schema_version = str(raw.get("schema_version") or "1.0")
    module_id = str(raw.get("module_id") or raw.get("id") or "")
    display_name = str(raw.get("display_name") or raw.get("name") or "")
    version = str(raw.get("version") or "0.1.0")
    category = str(raw.get("category") or "")
    description = str(raw.get("description") or "")
    trust_level = str(raw.get("trust_level") or "workspace")
    enabled_by_default = bool(raw.get("enabled_by_default", False))
    stability = str(raw.get("stability") or "experimental")
    origin = str(raw.get("origin") or "community")

    # ``dependency_status`` is the normalized key SkillRegistry emits; ``dependencies``
    # is the raw manifest key that still carries each declared ``check`` command (A4).
    dependencies = _parse_dependencies(
        raw.get("dependencies")
        if raw.get("dependencies") is not None
        else raw.get("dependency_status")
    )

    return ModuleManifest(
        schema_version=schema_version,
        module_id=module_id,
        display_name=display_name,
        version=version,
        category=category,
        description=description,
        tags=_to_str_list(raw.get("tags")),
        capabilities=_to_str_list(raw.get("capabilities")),
        trust_level=trust_level,
        enabled_by_default=enabled_by_default,
        stability=stability,
        origin=origin,
        triggers=_parse_triggers(raw.get("triggers")),
        dependencies=dependencies,
        provides=_parse_provides(raw.get("provides")),
        required_permissions=_to_str_list(raw.get("required_permissions")),
        required_secrets=_to_str_list(raw.get("required_secrets")),
        compatibility=_parse_compatibility(raw.get("compatibility"), schema_version),
        manifest_path=str(manifest_path),
    )


def _to_str_list(value: Any) -> list[str]:
    """Coerce a raw value into a list of non-empty strings (matches SkillRegistry)."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    item = str(value).strip()
    return [item] if item else []


def _parse_triggers(value: Any) -> list[dict[str, Any]]:
    """Preserve trigger mappings unchanged, dropping non-mapping entries."""
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _parse_dependencies(value: Any) -> list[DependencySpec]:
    """Parse declared dependencies into typed specs, preserving ``check`` (A4)."""
    if not value:
        return []
    if isinstance(value, Mapping):
        return [
            _dependency_from_mapping(name, item)
            for name, item in value.items()
            if isinstance(item, Mapping)
        ]
    if isinstance(value, (list, tuple)):
        specs: list[DependencySpec] = []
        for item in value:
            if isinstance(item, Mapping):
                name = item.get("name") or item.get("module_id") or "unknown"
                specs.append(_dependency_from_mapping(name, item))
            else:
                text = str(item).strip()
                if text:
                    specs.append(DependencySpec(name=text))
        return specs
    text = str(value).strip()
    return [DependencySpec(name=text)] if text else []


def _dependency_from_mapping(name: Any, item: Mapping[str, Any]) -> DependencySpec:
    """Build a ``DependencySpec`` from a dependency mapping.

    ``required`` follows an explicit flag when present; otherwise it is derived
    from ``status`` (only ``required`` is treated as mandatory, matching the
    manifest's ``required | recommended | optional`` scale).
    """
    status = str(item.get("status") or "required")
    if "required" in item:
        required = bool(item.get("required"))
    else:
        required = status == "required"
    check_value = item.get("check")
    check = str(check_value) if check_value else None
    return DependencySpec(
        name=str(name),
        status=status,
        check=check,
        required=required,
    )


def _parse_provides(value: Any) -> list[ProvidesEntry]:
    """Parse the ``provides`` section into typed entries (Req 1.2).

    Entries whose ``type`` is not a recognized contribution type are skipped and
    logged at debug level; manifest rejection for malformed sections is handled
    later by ``validate_manifest``.
    """
    if not isinstance(value, (list, tuple)):
        return []
    entries: list[ProvidesEntry] = []
    for item in value:
        if not isinstance(item, Mapping):
            logger.debug("Skipping non-mapping provides entry: %r", item)
            continue
        type_value = str(item.get("type") or "").strip()
        if type_value not in VALID_PROVIDES_TYPES:
            logger.debug("Skipping provides entry with unknown type: %r", type_value)
            continue
        priority = item.get("priority")
        entries.append(
            ProvidesEntry(
                type=ProvidesType(type_value),
                name=str(item.get("name") or ""),
                entrypoint=_optional_str(item.get("entrypoint")),
                listens_to=_optional_str(item.get("listens_to")),
                priority=_optional_str(priority),
                condition=_optional_str(item.get("condition")),
                response=_as_dict(item.get("response")),
                config=_as_dict(item.get("config")),
            )
        )
    return entries


def _parse_compatibility(value: Any, schema_version: str) -> Compatibility:
    """Parse the ``compatibility`` block, defaulting absent fields (Req 1.5)."""
    if isinstance(value, Mapping):
        return Compatibility(
            min_ravyn_version=str(value.get("min_ravyn_version") or "0.0.0"),
            schema_version=str(value.get("schema_version") or schema_version),
        )
    return Compatibility(min_ravyn_version="0.0.0", schema_version=schema_version)


def _optional_str(value: Any) -> str | None:
    """Return a stripped string, or ``None`` when the value is empty/absent."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_dict(value: Any) -> dict[str, Any]:
    """Return a shallow dict copy of a mapping, or an empty dict otherwise."""
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def validate_manifest(
    manifest: ModuleManifest, running_version: str
) -> ValidationResult:
    """Validate a parsed manifest against the schema, returning structured errors.

    This is a pure function with no side effects: it inspects the manifest and the
    running platform version and returns a ``ValidationResult`` describing every
    problem found. Callers (the Module_Loader) are responsible for logging,
    rejection, and health-report surfacing.

    The checks, in order, cover:

    * required-field presence — ``schema_version``, ``module_id``, ``display_name``,
      ``version``, ``category``, and ``description`` must each be non-empty
      (Req 3.1, 3.2);
    * format validity — ``module_id`` matches the segment pattern, ``version`` is a
      three-part semantic version, and ``trust_level`` is one of the valid levels
      (Req 1.7, 3.3);
    * schema-version support — the declared ``schema_version`` must be one the
      platform understands (Req 3.5);
    * version compatibility — the declared ``compatibility.min_ravyn_version`` must
      not exceed ``running_version`` when compared as a semantic version (Req 3.4).

    Returns:
        A ``ValidationResult`` whose ``ok`` flag is ``True`` only when no missing or
        invalid fields were found. ``missing_fields`` lists absent required field
        names, ``invalid_fields`` holds ``(field, value)`` pairs for malformed or
        incompatible values, and ``reason`` is a human-readable summary.
    """
    missing_fields: list[str] = []
    invalid_fields: list[tuple[str, str]] = []
    reasons: list[str] = []

    # ── Required-field presence (Req 3.1, 3.2) ──
    values: dict[str, str] = {
        "schema_version": manifest.schema_version,
        "module_id": manifest.module_id,
        "display_name": manifest.display_name,
        "version": manifest.version,
        "category": manifest.category,
        "description": manifest.description,
    }
    for name in REQUIRED_FIELDS:
        if not str(values.get(name, "")).strip():
            missing_fields.append(name)
    if missing_fields:
        reasons.append("missing required field(s): " + ", ".join(missing_fields))

    # ── Format validity (Req 1.7, 3.3) ──
    # Only check format when the field is present; absence is already reported above.
    if manifest.module_id and not _MODULE_ID_RE.match(manifest.module_id):
        invalid_fields.append(("module_id", manifest.module_id))
        reasons.append(
            f"module_id {manifest.module_id!r} is not lowercase alphanumeric "
            "segments separated by single dots or underscores"
        )
    if manifest.version and not _SEMVER_RE.match(manifest.version):
        invalid_fields.append(("version", manifest.version))
        reasons.append(
            f"version {manifest.version!r} is not a three-part semantic version "
            "(MAJOR.MINOR.PATCH)"
        )
    if manifest.trust_level and manifest.trust_level not in VALID_TRUST_LEVELS:
        invalid_fields.append(("trust_level", manifest.trust_level))
        reasons.append(
            f"trust_level {manifest.trust_level!r} is not one of "
            + ", ".join(sorted(VALID_TRUST_LEVELS))
        )

    # ── Schema-version support (Req 3.5) ──
    if (
        manifest.schema_version
        and manifest.schema_version not in SUPPORTED_SCHEMA_VERSIONS
    ):
        invalid_fields.append(("schema_version", manifest.schema_version))
        reasons.append(
            f"unsupported schema_version {manifest.schema_version!r}; supported: "
            + ", ".join(sorted(SUPPORTED_SCHEMA_VERSIONS))
        )

    # ── Version compatibility (Req 3.4) ──
    min_version = manifest.compatibility.min_ravyn_version
    required = _parse_semver(min_version)
    running = _parse_semver(running_version)
    if required is None:
        invalid_fields.append(("compatibility.min_ravyn_version", min_version))
        reasons.append(
            f"compatibility.min_ravyn_version {min_version!r} is not a three-part "
            "semantic version (MAJOR.MINOR.PATCH)"
        )
    elif running is None:
        invalid_fields.append(("compatibility.min_ravyn_version", min_version))
        reasons.append(
            f"running version {running_version!r} is not a three-part semantic "
            "version (MAJOR.MINOR.PATCH); cannot verify compatibility"
        )
    elif required > running:
        invalid_fields.append(("compatibility.min_ravyn_version", min_version))
        reasons.append(
            f"requires AetherRavyn >= {min_version} but running version is "
            f"{running_version}"
        )

    ok = not missing_fields and not invalid_fields
    return ValidationResult(
        ok=ok,
        missing_fields=missing_fields,
        invalid_fields=invalid_fields,
        reason="" if ok else "; ".join(reasons),
    )


def _parse_semver(value: str) -> tuple[int, int, int] | None:
    """Parse a three-part semantic version into a comparable tuple, or ``None``.

    Returns ``None`` when ``value`` is not a strict ``MAJOR.MINOR.PATCH`` triple,
    letting callers distinguish a malformed version from a valid comparison.
    """
    if not _SEMVER_RE.match(value):
        return None
    major, minor, patch = value.split(".")
    return (int(major), int(minor), int(patch))
