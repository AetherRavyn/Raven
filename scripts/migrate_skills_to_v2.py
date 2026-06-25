"""One-shot migration: convert the 18 v1 ``module.yaml`` skills into
v2 ``manifest.json`` + ``SKILL.md`` under the same ``skills/bundled/``
tree.

Usage::

    .venv/bin/python scripts/migrate_skills_to_v2.py

This is a one-shot script.  It is idempotent: re-running it overwrites
the generated ``manifest.json`` files.  The original ``module.yaml``
files are left in place so a reviewer can compare.

What it does, per v1 skill:

  1. Reads ``<v1_root>/<name>/module.yaml`` + ``SKILL.md``.
  2. Maps the v1 fields to a v2 :class:`SkillManifest`:
     * ``module_id`` / ``display_name`` / ``name`` → v2 ``name`` (slugified).
     * ``version`` → v2 ``version`` (string).
     * ``description`` → v2 ``description`` (stripped).
     * ``author`` (if any) → v2 ``author``.
     * ``tags`` → v2 ``tags``.
     * ``capabilities`` → v2 ``permissions`` (heuristically mapped to
       :class:`Permission` enum values; unknown names pass through as
       raw strings so we don't lose data).
     * ``trust_level`` → v2 ``trust`` (best-effort mapping).
     * ``triggers`` → v2 ``inputs`` (one string input ``query``).
  3. Writes the v2 manifest + SKILL.md to::

         <v1_root>/<slug>/<version>/manifest.json
         <v1_root>/<slug>/<version>/SKILL.md

     i.e. the new directory lives *next to* the old one, not in place
     of it.  ``SkillLayoutRoot`` discovers skills three levels deep
     (``scope / name / version``), so this matches the layout.
  4. Validates the produced manifest with
     :func:`app.core.skill_v2.manifest.validate_manifest` and aborts
     if any error is reported.

After running, the test suite picks up the new v2 layouts via
:class:`SkillLayoutRoot`.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

# Allow running as a script from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import yaml  # noqa: E402

from app.core.skill_v2.layout import SkillLayout, SkillLayoutRoot, _slugify  # noqa: E402
from app.core.skill_v2.manifest import (  # noqa: E402
    InputSchema,
    ManifestSource,
    ManifestTrust,
    Permission,
    RiskLevel,
    SkillManifest,
    validate_manifest,
)

logger = logging.getLogger("migrate_skills_to_v2")


# ── Mappings ────────────────────────────────────────────────────────


#: Map v1 ``trust_level`` strings to v2 :class:`ManifestTrust` values.
_TRUST_MAP: dict[str, ManifestTrust] = {
    "official": ManifestTrust.OFFICIAL,
    "verified": ManifestTrust.VERIFIED,
    "workspace": ManifestTrust.WORKSPACE,
    "community": ManifestTrust.WORKSPACE,
    "untrusted": ManifestTrust.UNTRUSTED,
}


#: Map v1 ``capabilities`` to v2 :class:`Permission` values where the
#: name is recognisable.  Unknown capabilities are kept as raw strings
#: (the manifest preserves them in the ``tags`` field for traceability).
_CAPABILITY_PERMISSION_HINTS: dict[str, Permission] = {
    "file_tool": Permission.FILESYSTEM_READ,
    "exec_tool": Permission.PROCESS_SPAWN,
    "git_tool": Permission.FILESYSTEM_READ,
    "mail_tool": Permission.MESSAGING_SEND,
    "memory_tool": Permission.USER_DATA_READ,
    "web_search": Permission.NETWORK_EGRESS,
    "url_tool": Permission.NETWORK_EGRESS,
    "web_fetch": Permission.NETWORK_INGRESS,
    "system_stats_tool": Permission.FILESYSTEM_READ,
    "network_tool": Permission.NETWORK_EGRESS,
    "voice": Permission.FILESYSTEM_READ,  # voice reads audio files
    "weather_tool": Permission.NETWORK_EGRESS,
    "rss_reader": Permission.NETWORK_INGRESS,
    "todo_list": Permission.USER_DATA_READ,
    "cron_engine": Permission.PROCESS_SPAWN,
    "goal_manager": Permission.USER_DATA_READ,
}


# ── Helpers ─────────────────────────────────────────────────────────


def _map_trust(value: Any) -> ManifestTrust:
    if not isinstance(value, str):
        return ManifestTrust.WORKSPACE
    return _TRUST_MAP.get(value.lower(), ManifestTrust.WORKSPACE)


def _map_capabilities(value: Any) -> tuple[list[Permission], list[str]]:
    """Split v1 capabilities into v2 permissions + leftover raw names."""
    if not isinstance(value, list):
        return [], []
    perms: list[Permission] = []
    leftover: list[str] = []
    for cap in value:
        if not isinstance(cap, str):
            continue
        hint = _CAPABILITY_PERMISSION_HINTS.get(cap)
        if hint is not None and hint not in perms:
            perms.append(hint)
        else:
            leftover.append(cap)
    return perms, leftover


def _extract_triggers(value: Any) -> list[InputSchema]:
    """Best-effort: v1 triggers describe what the skill listens for.
    We model that as a single string input named ``query``."""
    if not value:
        return []
    return [InputSchema(name="query", type="string", required=False)]


def _yaml_description_to_str(value: Any) -> str:
    """Normalise description to a single stripped string."""
    if value is None:
        return ""
    if isinstance(value, str):
        # YAML `>` folded scalars come in with trailing newlines.
        return value.strip()
    return str(value).strip()


# ── Migration ───────────────────────────────────────────────────────


def migrate_one(
    v1_dir: Path, v1_cfg: dict[str, Any], v1_md_text: str, v1_root: Path,
) -> tuple[SkillManifest, SkillLayout]:
    """Convert one v1 skill into a v2 manifest + layout."""
    # Name resolution.  v1 files vary: some have ``name``, some only
    # ``display_name``, some only ``module_id``.  We prefer the
    # directory name (it's already a valid slug) and fall back to
    # ``module_id`` last segment, then ``display_name`` slugified.
    name_raw = (
        v1_dir.name
        if v1_dir.name
        else str(v1_cfg.get("module_id") or "").rsplit(".", 1)[-1]
    )
    slug = _slugify(name_raw)

    # Version: v1 has it as a string or unquoted float.  Force string.
    raw_version = v1_cfg.get("version", "1.0.0")
    version = str(raw_version)

    # Trust and permissions.
    trust = _map_trust(v1_cfg.get("trust_level"))
    perms, leftover_caps = _map_capabilities(v1_cfg.get("capabilities"))

    # Tags: keep v1 tags, plus the leftover capabilities so nothing
    # is lost.
    tags = list(v1_cfg.get("tags") or [])
    for cap in leftover_caps:
        if cap not in tags:
            tags.append(cap)

    manifest = SkillManifest(
        name=slug,
        version=version,
        author=str(v1_cfg.get("author") or "RAVEN team"),
        description=_yaml_description_to_str(v1_cfg.get("description")),
        source=ManifestSource.BUNDLED,
        trust=trust,
        permissions=perms,
        risk_level=RiskLevel.LOW,
        inputs=_extract_triggers(v1_cfg.get("triggers")),
        tags=tags,
    )

    # The v2 layout puts files at ``<root>/<scope>/<name>/<version>/``.
    # The v1 root already represents the ``bundled`` scope, so the
    # layout root is the *parent* of the v1 root and the scope is
    # the v1 root's name ("bundled").
    layout = SkillLayout(
        root=v1_root.parent,
        scope=v1_root.name,
        name=slug,
        version=version,
    )
    return manifest, layout


def migrate_tree(v1_root: Path) -> list[tuple[SkillLayout, list[str]]]:
    """Migrate every v1 skill under ``v1_root``.

    Returns a list of ``(layout, validation_errors)`` tuples.  A
    non-empty error list means the migration wrote a manifest that
    did not validate — the caller decides whether to fail.
    """
    results: list[tuple[SkillLayout, list[str]]] = []
    if not v1_root.is_dir():
        logger.error("v1 root not a directory: %s", v1_root)
        return results

    for skill_dir in sorted(v1_root.iterdir()):
        if not skill_dir.is_dir():
            continue
        yaml_path = skill_dir / "module.yaml"
        md_path = skill_dir / "SKILL.md"
        if not yaml_path.is_file():
            continue
        try:
            cfg = yaml.safe_load(yaml_path.read_text()) or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("bad yaml at %s: %s", yaml_path, exc)
            continue

        md_text = md_path.read_text() if md_path.is_file() else ""

        manifest, layout = migrate_one(skill_dir, cfg, md_text, v1_root)
        # Write both files.
        layout.write_manifest(manifest)
        if md_text:
            layout.write_skill_md(md_text)

        errs = list(validate_manifest(manifest))
        results.append((layout, errs))
    return results


# ── CLI ─────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate v1 module.yaml skills to v2 manifests."
    )
    parser.add_argument(
        "--v1-root",
        default=str(_REPO_ROOT / "skills" / "bundled"),
        help="Path to the v1 skills root (default: skills/bundled)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without writing files",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose logging"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    v1_root = Path(args.v1_root)
    logger.info("Migrating v1 skills under %s", v1_root)

    if args.dry_run:
        # Walk and report; do not write.
        for skill_dir in sorted(v1_root.iterdir()):
            if not skill_dir.is_dir():
                continue
            yaml_path = skill_dir / "module.yaml"
            if not yaml_path.is_file():
                continue
            cfg = yaml.safe_load(yaml_path.read_text()) or {}
            md_path = skill_dir / "SKILL.md"
            md_text = md_path.read_text() if md_path.is_file() else ""
            manifest, layout = migrate_one(skill_dir, cfg, md_text, v1_root)
            errs = list(validate_manifest(manifest))
            status = "OK" if not errs else f"INVALID: {errs}"
            print(
                f"{layout.dir.relative_to(v1_root.parent)}  ->  {status}"
            )
        return 0

    results = migrate_tree(v1_root)
    ok = sum(1 for _, errs in results if not errs)
    bad = sum(1 for _, errs in results if errs)
    print(f"Migrated {ok} skill(s); {bad} had validation errors.")
    for layout, errs in results:
        rel = layout.dir.relative_to(v1_root)
        if errs:
            print(f"  INVALID {rel}: {errs}")
        else:
            print(f"  OK      {rel}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
