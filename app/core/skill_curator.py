"""Skill Curator — Auto-scores, prunes, and imports external skills.

Monitors skill health by tracking invocation success rates and confidence
scores. Automatically disables underperforming skills and imports compatible
skills from Hermes (agentskills.io) and OpenClaw formats.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


class SkillCurator:
    """Manages skill quality, lifecycle, and external imports.

    Responsibilities:
    1. Score skills based on invocation history (success rate, frequency)
    2. Demote/disable skills with poor performance
    3. Promote skills with high confidence to 'stable'
    4. Import skills from Hermes and OpenClaw formats
    5. Garbage-collect orphan skill artifacts
    """

    def __init__(
        self,
        project_root: str | Path | None = None,
        min_invocations_for_prune: int = 5,
        prune_threshold: float = 0.3,
        promote_threshold: float = 0.85,
        promote_min_invocations: int = 10,
    ) -> None:
        self._project_root = (
            Path(project_root).resolve() if project_root else _PROJECT_ROOT
        )
        self._skills_root = self._project_root / "skills"
        self._learned_dir = self._skills_root / "learned"
        self._imported_dir = self._skills_root / "imported"
        self._archived_dir = self._skills_root / ".archived"

        for d in (self._learned_dir, self._imported_dir, self._archived_dir):
            d.mkdir(parents=True, exist_ok=True)

        self._min_invocations_for_prune = min_invocations_for_prune
        self._prune_threshold = prune_threshold
        self._promote_threshold = promote_threshold
        self._promote_min_invocations = promote_min_invocations

    # ── Scoring ─────────────────────────────────────────────────────

    def score_all(self) -> list[dict[str, Any]]:
        """Score every skill and return a ranked list."""
        results: list[dict[str, Any]] = []
        for skill_dir in self._iter_skill_dirs():
            manifest = self._read_manifest(skill_dir)
            if manifest is None:
                continue
            score = self._compute_score(manifest)
            results.append({
                "module_id": manifest.get("module_id", "unknown"),
                "name": manifest.get("display_name") or manifest.get("name", ""),
                "score": round(score, 3),
                "success_rate": manifest.get("success_rate", 0),
                "invocation_count": manifest.get("invocation_count", 0),
                "confidence": manifest.get("confidence", 0),
                "stability": manifest.get("stability", "unknown"),
                "origin": manifest.get("origin", "unknown"),
                "path": str(skill_dir),
            })
        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    def _compute_score(self, manifest: dict[str, Any]) -> float:
        """Composite quality score: 0.0 (terrible) → 1.0 (proven)."""
        confidence = manifest.get("confidence", 0.5)
        success_rate = manifest.get("success_rate", 0.5)
        invocations = manifest.get("invocation_count", 0)

        # Usage frequency bonus (log scale, caps at ~0.15)
        import math
        usage_bonus = min(0.15, math.log1p(invocations) * 0.03)

        # Weighted composite
        score = (confidence * 0.35) + (success_rate * 0.50) + usage_bonus
        return min(1.0, score)

    # ── Pruning ─────────────────────────────────────────────────────

    def prune(self) -> list[str]:
        """Disable or archive skills with poor performance.

        Returns list of module_ids that were pruned.
        """
        pruned: list[str] = []
        for skill_dir in self._iter_skill_dirs():
            manifest = self._read_manifest(skill_dir)
            if manifest is None:
                continue

            invocations = manifest.get("invocation_count", 0)
            success_rate = manifest.get("success_rate", 1.0)
            module_id = manifest.get("module_id", "unknown")

            if invocations < self._min_invocations_for_prune:
                continue

            if success_rate < self._prune_threshold:
                logger.info(
                    "Pruning skill %s (success_rate=%.2f, invocations=%d)",
                    module_id, success_rate, invocations,
                )
                self._archive_skill(skill_dir, manifest)
                pruned.append(module_id)

        return pruned

    def _archive_skill(
        self, skill_dir: Path, manifest: dict[str, Any]
    ) -> None:
        """Move a skill to the archive directory."""
        slug = skill_dir.name
        archive_dest = self._archived_dir / f"{slug}_{datetime.now(timezone.utc).strftime('%Y%m%d')}"
        try:
            shutil.move(str(skill_dir), str(archive_dest))
            logger.info("Archived skill to %s", archive_dest)
        except Exception as exc:
            logger.warning("Failed to archive skill %s: %s", slug, exc)

    # ── Promotion ───────────────────────────────────────────────────

    def promote(self) -> list[str]:
        """Promote high-performing skills from 'experimental' to 'stable'.

        Returns list of promoted module_ids.
        """
        promoted: list[str] = []
        for skill_dir in self._iter_skill_dirs():
            manifest = self._read_manifest(skill_dir)
            if manifest is None:
                continue

            if manifest.get("stability") == "stable":
                continue

            invocations = manifest.get("invocation_count", 0)
            success_rate = manifest.get("success_rate", 0)

            if (
                invocations >= self._promote_min_invocations
                and success_rate >= self._promote_threshold
            ):
                manifest["stability"] = "stable"
                manifest["promoted_at"] = datetime.now(timezone.utc).isoformat()
                self._write_manifest(skill_dir, manifest)
                module_id = manifest.get("module_id", "unknown")
                logger.info("Promoted skill %s to stable", module_id)
                promoted.append(module_id)

        return promoted

    # ── External Import ─────────────────────────────────────────────

    def import_hermes_skill(self, source_dir: str | Path) -> dict[str, Any]:
        """Import a Hermes-format skill (SKILL.md + module.yaml).

        Hermes skills use the same SKILL.md + module.yaml format that
        AetherRavyn uses, so this is mostly a copy + metadata tagging.
        """
        source = Path(source_dir)
        if not source.is_dir():
            return {"success": False, "error": f"Not a directory: {source}"}

        # Look for manifest
        manifest_path = None
        for name in ("module.yaml", "module.yml", "manifest.json"):
            candidate = source / name
            if candidate.exists():
                manifest_path = candidate
                break

        if manifest_path is None:
            return {"success": False, "error": "No module.yaml/manifest.json found"}

        # Read and tag
        if manifest_path.suffix in (".yaml", ".yml"):
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        else:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        slug = source.name
        dest = self._imported_dir / slug
        if dest.exists():
            return {"success": False, "error": f"Skill {slug} already imported"}

        # Copy entire directory
        shutil.copytree(str(source), str(dest))

        # Tag as imported from Hermes
        manifest["origin"] = "hermes"
        manifest["imported_at"] = datetime.now(timezone.utc).isoformat()
        manifest["trust_level"] = "community"
        dest_manifest = dest / manifest_path.name
        if manifest_path.suffix in (".yaml", ".yml"):
            dest_manifest.write_text(
                yaml.dump(manifest, default_flow_style=False, allow_unicode=True),
                encoding="utf-8",
            )
        else:
            dest_manifest.write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )

        logger.info("Imported Hermes skill: %s → %s", source, dest)
        return {"success": True, "module_id": manifest.get("module_id", slug), "path": str(dest)}

    def import_openclaw_skill(self, source_dir: str | Path) -> dict[str, Any]:
        """Import an OpenClaw-format skill package.

        OpenClaw skills typically have a config.json + handler files.
        We convert them to our module.yaml format.
        """
        source = Path(source_dir)
        if not source.is_dir():
            return {"success": False, "error": f"Not a directory: {source}"}

        # OpenClaw uses config.json or skill.json
        config_path = None
        for name in ("config.json", "skill.json", "package.json"):
            candidate = source / name
            if candidate.exists():
                config_path = candidate
                break

        if config_path is None:
            return {"success": False, "error": "No config.json/skill.json found"}

        config = json.loads(config_path.read_text(encoding="utf-8"))

        slug = source.name
        dest = self._imported_dir / slug
        if dest.exists():
            return {"success": False, "error": f"Skill {slug} already imported"}

        shutil.copytree(str(source), str(dest))

        # Convert to our module.yaml format
        manifest = {
            "schema_version": "1.0",
            "module_id": f"skill.imported.{slug}",
            "display_name": config.get("name") or config.get("title", slug),
            "name": config.get("name", slug),
            "version": config.get("version", "0.1.0"),
            "category": "skill",
            "description": config.get("description", ""),
            "tags": config.get("tags") or config.get("keywords", []),
            "capabilities": config.get("tools", []),
            "trust_level": "community",
            "enabled_by_default": False,
            "stability": "experimental",
            "maturity": "imported",
            "origin": "openclaw",
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "confidence": 0.5,
            "invocation_count": 0,
            "success_rate": 0.0,
        }
        (dest / "module.yaml").write_text(
            yaml.dump(manifest, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )

        logger.info("Imported OpenClaw skill: %s → %s", source, dest)
        return {"success": True, "module_id": manifest["module_id"], "path": str(dest)}

    def import_from_url(self, url: str) -> dict[str, Any]:
        """Import a skill from a git URL (supports agentskills.io links).

        Clones the repo into a temp dir and then imports via the appropriate
        format detector (Hermes or OpenClaw).
        """
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "skill"
            try:
                subprocess.run(
                    ["git", "clone", "--depth=1", url, str(tmp_path)],
                    check=True, capture_output=True, timeout=30,
                )
            except subprocess.CalledProcessError as exc:
                return {"success": False, "error": f"Git clone failed: {exc.stderr.decode()[:200]}"}
            except FileNotFoundError:
                return {"success": False, "error": "git not found in PATH"}

            # Auto-detect format
            if (tmp_path / "module.yaml").exists() or (tmp_path / "SKILL.md").exists():
                return self.import_hermes_skill(tmp_path)
            elif (tmp_path / "config.json").exists() or (tmp_path / "skill.json").exists():
                return self.import_openclaw_skill(tmp_path)
            else:
                return {"success": False, "error": "Unknown skill format (no module.yaml or config.json)"}

    # ── GC ──────────────────────────────────────────────────────────

    def garbage_collect(self) -> list[str]:
        """Remove orphan skill directories that have no manifest."""
        orphans: list[str] = []
        for skill_dir in self._iter_skill_dirs():
            has_manifest = any(
                (skill_dir / name).exists()
                for name in ("module.yaml", "module.yml", "manifest.json", "SKILL.md")
            )
            if not has_manifest:
                logger.info("GC: removing orphan skill dir %s", skill_dir)
                shutil.rmtree(skill_dir, ignore_errors=True)
                orphans.append(str(skill_dir))
        return orphans

    # ── Helpers ─────────────────────────────────────────────────────

    def _iter_skill_dirs(self):
        """Iterate over all skill directories across all roots."""
        for root in (self._learned_dir, self._imported_dir, self._skills_root / "bundled"):
            if not root.exists():
                continue
            for d in root.iterdir():
                if d.is_dir() and not d.name.startswith("."):
                    yield d

    def _read_manifest(self, skill_dir: Path) -> dict[str, Any] | None:
        for name in ("module.yaml", "module.yml"):
            p = skill_dir / name
            if p.exists():
                try:
                    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                except Exception:
                    return None
        mj = skill_dir / "manifest.json"
        if mj.exists():
            try:
                return json.loads(mj.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def _write_manifest(self, skill_dir: Path, manifest: dict[str, Any]) -> None:
        p = skill_dir / "module.yaml"
        p.write_text(
            yaml.dump(manifest, default_flow_style=False, allow_unicode=True),
            encoding="utf-8",
        )


# ── Module singleton ────────────────────────────────────────────────

_GLOBAL_CURATOR: SkillCurator | None = None


def get_skill_curator(
    project_root: str | Path | None = None,
) -> SkillCurator:
    """Get or create the global SkillCurator instance."""
    global _GLOBAL_CURATOR
    if _GLOBAL_CURATOR is None:
        _GLOBAL_CURATOR = SkillCurator(project_root=project_root)
    return _GLOBAL_CURATOR
