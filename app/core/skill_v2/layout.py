"""On-disk layout for skill v2.

A skill lives at::

    <root>/<scope>/<name>/<version>/
        manifest.json   # required
        SKILL.md        # required
        signature       # optional — ed25519 signature (hex)
        eval.jsonl      # optional — append-only eval records

Scopes:

  * ``bundled``   — ships with RAVEN
  * ``learned``   — produced by SkillLearner
  * ``community`` — downloaded
  * ``installed`` — user-installed

The :class:`SkillLayout` is a small wrapper around a root directory
that knows how to discover, read, and write skill directories.  It
never deletes anything outside of its root.

The :class:`SkillLayout` also exposes a :meth:`migrate_from_v1`
helper that copies the legacy ``module.yaml`` + ``SKILL.md`` layout
into the v2 directory layout.  Existing skills keep working; the
learner is responsible for re-saving them as v2 manifests.
"""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from app.core.skill_v2.manifest import (
    ManifestSource,
    SkillManifest,
    manifest_from_json,
    manifest_to_json,
)

logger = logging.getLogger(__name__)


VALID_SCOPES = ("bundled", "learned", "community", "installed")


@dataclass
class SkillLayout:
    """One skill directory on disk."""

    root: Path
    scope: str
    name: str
    version: str

    @property
    def dir(self) -> Path:
        return self.root / self.scope / self.name / self.version

    @property
    def manifest_path(self) -> Path:
        return self.dir / "manifest.json"

    @property
    def skill_md_path(self) -> Path:
        return self.dir / "SKILL.md"

    @property
    def signature_path(self) -> Path:
        return self.dir / "signature"

    @property
    def eval_path(self) -> Path:
        return self.dir / "eval.jsonl"

    def exists(self) -> bool:
        return self.dir.is_dir()

    def has_manifest(self) -> bool:
        return self.manifest_path.is_file()

    def read_manifest(self) -> Optional[SkillManifest]:
        if not self.has_manifest():
            return None
        return manifest_from_json(self.manifest_path.read_text())

    def write_manifest(self, m: SkillManifest) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(manifest_to_json(m))

    def read_skill_md(self) -> str:
        if not self.skill_md_path.is_file():
            return ""
        return self.skill_md_path.read_text()

    def write_skill_md(self, text: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.skill_md_path.write_text(text)

    def read_signature(self) -> Optional[str]:
        if not self.signature_path.is_file():
            return None
        return self.signature_path.read_text().strip()

    def write_signature(self, signature_hex: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.signature_path.write_text(signature_hex)

    def append_eval_record(self, record_dict: dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with self.eval_path.open("a") as f:
            f.write(json.dumps(record_dict) + "\n")

    def read_eval_records(self) -> list[dict[str, Any]]:
        if not self.eval_path.is_file():
            return []
        out: list[dict[str, Any]] = []
        for line in self.eval_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out


class SkillLayoutRoot:
    """Discover and manipulate skills under one root directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def list(
        self, *, scope: str | None = None
    ) -> list[SkillLayout]:
        """List all skill layouts under the root.

        Walks the directory tree at most 3 levels deep
        (scope / name / version).  Returns layouts whose ``manifest.json``
        exists.
        """
        out: list[SkillLayout] = []
        if not self.root.is_dir():
            return out
        scopes = [scope] if scope else list(VALID_SCOPES)
        for sc in scopes:
            scope_dir = self.root / sc
            if not scope_dir.is_dir():
                continue
            for skill_dir in sorted(scope_dir.iterdir()):
                if not skill_dir.is_dir():
                    continue
                for ver_dir in sorted(skill_dir.iterdir()):
                    if not ver_dir.is_dir():
                        continue
                    layout = SkillLayout(
                        root=self.root,
                        scope=sc,
                        name=skill_dir.name,
                        version=ver_dir.name,
                    )
                    if layout.has_manifest():
                        out.append(layout)
        return out

    def list_names(self, *, scope: str | None = None) -> list[str]:
        return sorted({layout.name for layout in self.list(scope=scope)})

    def versions_of(self, name: str, *, scope: str | None = None) -> list[str]:
        out: list[str] = []
        for layout in self.list(scope=scope):
            if layout.name == name:
                out.append(layout.version)
        return sorted(out)

    def find(
        self, name: str, *, version: str | None = None, scope: str | None = None
    ) -> Optional[SkillLayout]:
        """Find a skill by name + (optional) version + (optional) scope."""
        candidates = [
            l for l in self.list(scope=scope) if l.name == name
        ]
        if version is not None:
            candidates = [l for l in candidates if l.version == version]
        if not candidates:
            return None
        # If multiple scopes match, prefer bundled > installed > community > learned.
        priority = {"bundled": 0, "installed": 1, "community": 2, "learned": 3}
        candidates.sort(key=lambda l: priority.get(l.scope, 9))
        return candidates[0]

    def install(self, layout: SkillLayout) -> SkillLayout:
        """Copy a layout (e.g. from a downloaded tarball) into ``installed/``.

        Returns the layout in its final installed location.
        """
        target = SkillLayout(
            root=self.root,
            scope="installed",
            name=layout.name,
            version=layout.version,
        )
        target.dir.mkdir(parents=True, exist_ok=True)
        for src in layout.dir.iterdir():
            dst = target.dir / src.name
            if src.is_file():
                shutil.copy2(src, dst)
        return target

    def uninstall(self, name: str, *, version: str | None = None) -> int:
        """Remove a skill from ``installed/``.  Returns count of dirs removed."""
        scopes = ["installed"]
        count = 0
        for sc in scopes:
            scope_dir = self.root / sc
            if not scope_dir.is_dir():
                continue
            skill_dir = scope_dir / name
            if not skill_dir.is_dir():
                continue
            if version is None:
                shutil.rmtree(skill_dir)
                count += 1
            else:
                ver_dir = skill_dir / version
                if ver_dir.is_dir():
                    shutil.rmtree(ver_dir)
                    count += 1
                # If the skill dir is now empty, remove it too.
                if not any(skill_dir.iterdir()):
                    shutil.rmtree(skill_dir)
        return count

    # ── v1 migration ────────────────────────────────────────────

    def migrate_from_v1(self, v1_root: str | Path) -> list[SkillLayout]:
        """Copy skills from a legacy ``module.yaml`` layout into v2.

        Reads each ``<v1_root>/<name>/module.yaml`` + ``SKILL.md``,
        builds a minimal v2 manifest, and writes it under
        ``<root>/bundled/<name>/0.1.0/``.

        Returns the list of newly-created layouts.
        """
        v1_root = Path(v1_root)
        if not v1_root.is_dir():
            return []
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError:
            logger.warning("PyYAML not available; v1 migration skipped")
            return []
        created: list[SkillLayout] = []
        for skill_dir in sorted(v1_root.iterdir()):
            if not skill_dir.is_dir():
                continue
            yaml_path = skill_dir / "module.yaml"
            md_path = skill_dir / "SKILL.md"
            if not yaml_path.is_file():
                continue
            try:
                cfg = yaml.safe_load(yaml_path.read_text()) or {}
            except Exception as e:  # noqa: BLE001
                logger.warning("v1 migrate: bad yaml at %s: %s", yaml_path, e)
                continue
            name = str(cfg.get("name") or skill_dir.name)
            # Build a slug.
            slug = _slugify(name)
            version = str(cfg.get("version") or "0.1.0")
            manifest = SkillManifest(
                name=slug,
                version=version,
                author=str(cfg.get("author") or ""),
                description=str(cfg.get("description") or "").strip(),
                source=ManifestSource.BUNDLED,
                tags=list(cfg.get("tags") or []),
            )
            target = SkillLayout(
                root=self.root, scope="bundled", name=slug, version=version
            )
            target.write_manifest(manifest)
            if md_path.is_file():
                target.write_skill_md(md_path.read_text())
            created.append(target)
        return created


def _slugify(name: str) -> str:
    out: list[str] = []
    for ch in name.lower():
        if ch.isalnum() or ch in "-_.":
            out.append(ch)
        elif ch in " ":
            out.append("-")
    s = "".join(out).strip("-")
    return s or "skill"


__all__ = [
    "VALID_SCOPES",
    "SkillLayout",
    "SkillLayoutRoot",
]