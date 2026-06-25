"""Module_Registry — discovery, typed record cache, and capability-graph tracking.

The ``ModuleRegistry`` generalises the existing ``SkillRegistry``. It *composes*
a ``SkillRegistry`` instance (rather than subclassing it) and adapts the
``list[dict]`` discovery records that registry returns into the platform's typed
:class:`~app.modules.models.ModuleRecord` objects (assumption A1). It never
changes ``SkillRegistry``'s return type (Req 14.1).

Responsibilities (Requirement 2, 12.1, 14.8):

* ``discover`` — scan every configured module root through the composed
  ``SkillRegistry``, adapt each raw record into a typed ``ModuleRecord``, and
  record ``(module_id, category)`` in the ``SystemKernel`` capability graph.
  Missing module roots and directories without a recognised manifest are skipped
  and logged at debug level (Req 2.1, 2.2, 2.5, 2.6).
* Deterministic manifest precedence (delegated to ``SkillRegistry``) plus
  lexicographic duplicate-``module_id`` resolution (Req 2.4, 3.6).
* ``get`` / ``all`` — accessors over the typed record cache, ``all`` ordered by
  ``module_id`` (Req 12.1).
* ``add_skill`` / ``remove_skill`` — track a module-provided skill contribution
  across hot-load / hot-unload (Req 6.1, 10.7).
* ``record_in_graph`` / ``remove_from_graph`` — capability-graph bookkeeping,
  the latter used by uninstall (Req 2.5, 10.5).
* ``counts`` — ``(enabled, disabled)`` tallies for observability (Req 14.8).
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from app.core.kernel import SystemKernel, get_kernel
from app.core.skill_registry import SkillRegistry
from app.modules.manifest import parse_manifest
from app.modules.models import ModuleRecord, ModuleState

if TYPE_CHECKING:
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

# Recognised manifest filenames, mirroring ``SkillRegistry`` (Req 2.1, 2.6).
_MANIFEST_FILENAMES: tuple[str, ...] = (
    "module.yaml",
    "module.yml",
    "manifest.json",
    "SKILL.md",
)

# Raw manifest keys carried straight through from the on-disk manifest so the
# additive Module_Platform sections survive adaptation. ``SkillRegistry``'s
# normalised record drops ``provides``/``required_permissions``/etc. and rewrites
# ``dependencies`` into ``dependency_status`` (losing each ``check`` command), so
# these are merged back in from the raw manifest before parsing.
_RAW_PASSTHROUGH_KEYS: tuple[str, ...] = (
    "provides",
    "required_permissions",
    "required_secrets",
    "compatibility",
    "dependencies",
    "triggers",
)


class ModuleRegistry:
    """Discovers, adapts, and tracks modules over a composed ``SkillRegistry``."""

    def __init__(
        self,
        skill_registry: SkillRegistry | None = None,
        kernel: SystemKernel | None = None,
        roots: list[str | Path] | None = None,
    ) -> None:
        self._skill_registry = skill_registry or SkillRegistry(roots=roots)
        self._kernel = kernel or get_kernel()
        self._records: dict[str, ModuleRecord] = {}
        # module_ids whose skill contribution is currently registered (Req 6.1).
        self._active_skills: set[str] = set()

    @property
    def project_root(self) -> Path:
        """The resolved project root, shared with the composed ``SkillRegistry``.

        Used by path-resolving callers such as ``ModuleCLI.scaffold`` to locate
        the ``app/tools`` and ``app/agents`` trees.
        """
        return self._skill_registry.project_root

    # ── Discovery (Req 2.1-2.6) ────────────────────────────────────────

    async def discover(self) -> list[ModuleRecord]:
        """Scan every configured root, adapt each record, and record in the graph.

        Discovery is delegated to the composed ``SkillRegistry`` (so the four
        recognised manifest filenames and the deterministic per-directory
        precedence order are unchanged), then each raw ``dict`` record is adapted
        into a typed ``ModuleRecord``. Modules sharing a ``module_id`` are
        resolved lexicographically by manifest path (Req 2.4, 3.6). Missing roots
        and manifest-less directories are skipped and logged at debug level
        (Req 2.2, 2.6).
        """
        self._log_skipped_roots()
        self._log_manifestless_directories()

        raw_records = await asyncio.to_thread(self._skill_registry.discover)
        adapted = [self._adapt(raw) for raw in raw_records]
        deduped = self._resolve_duplicates(adapted)

        self._records = {record.module_id: record for record in deduped}
        self._active_skills.intersection_update(self._records)
        for record in deduped:
            self.record_in_graph(record)

        logger.debug("Discovered %d module(s)", len(self._records))
        return self.all()

    # ── Record cache accessors (Req 12.1) ──────────────────────────────

    def get(self, module_id: str) -> ModuleRecord | None:
        """Return the typed record for ``module_id``, or ``None`` if unknown."""
        return self._records.get(module_id)

    def all(self) -> list[ModuleRecord]:
        """Return every discovered module ordered by ``module_id`` (Req 12.1)."""
        return [self._records[key] for key in sorted(self._records)]

    def counts(self) -> tuple[int, int]:
        """Return ``(enabled_count, disabled_count)`` over the cache (Req 14.8)."""
        enabled = sum(
            1
            for record in self._records.values()
            if record.state is ModuleState.ENABLED
        )
        return enabled, len(self._records) - enabled

    # ── Skill contribution tracking (Req 6.1, 10.7) ────────────────────

    def add_skill(self, record: ModuleRecord) -> None:
        """Register a module-provided skill so the registry surfaces it (Req 6.1).

        Idempotent: the record is tracked in the cache and capability graph and
        its ``module_id`` is marked as an active skill contribution.
        """
        self._records[record.module_id] = record
        self._active_skills.add(record.module_id)
        self.record_in_graph(record)
        logger.debug("Registered skill contribution for module %s", record.module_id)

    def remove_skill(self, module_id: str) -> None:
        """Reverse :meth:`add_skill` on hot-unload (Req 10.7).

        Idempotent: removing a module that has no active skill contribution is a
        no-op. The module remains in the cache so a disabled module is still
        listed (Req 12.1); only the active-skill marker is cleared.
        """
        if module_id in self._active_skills:
            self._active_skills.discard(module_id)
            logger.debug("Removed skill contribution for module %s", module_id)

    def active_skill_ids(self) -> list[str]:
        """Return the ``module_id`` of every currently registered skill."""
        return sorted(self._active_skills)

    # ── Capability-graph bookkeeping (Req 2.5, 10.5) ───────────────────

    def record_in_graph(self, record: ModuleRecord) -> None:
        """Record ``(module_id, category)`` in the kernel capability graph (Req 2.5).

        Idempotent: re-recording the same ``module_id`` replaces its entry rather
        than appending a duplicate.
        """
        modules = self._graph_modules()
        entry = {
            "name": record.module_id,
            "category": record.manifest.category,
            "trust_level": record.trust_level,
        }
        for index, existing in enumerate(modules):
            if existing.get("name") == record.module_id:
                modules[index] = entry
                return
        modules.append(entry)

    def remove_from_graph(self, module_id: str) -> None:
        """Drop a module's capability-graph entry; used by uninstall (Req 10.5).

        Idempotent: removing an absent module is a no-op.
        """
        graph = self._kernel.get_capability_graph()
        modules = graph.get("modules")
        if not modules:
            return
        graph["modules"] = [
            entry for entry in modules if entry.get("name") != module_id
        ]

    def _graph_modules(self) -> list[dict[str, Any]]:
        """Return the kernel graph's ``modules`` list, creating it if absent."""
        graph = self._kernel.get_capability_graph()
        modules = graph.get("modules")
        if not isinstance(modules, list):
            modules = []
            graph["modules"] = modules
        return modules

    # ── Adaptation: dict record -> typed ModuleRecord (A1) ─────────────

    def _adapt(self, raw_record: Mapping[str, Any]) -> ModuleRecord:
        """Adapt a ``SkillRegistry`` dict record into a typed ``ModuleRecord``.

        The normalised record supplies ``SkillRegistry``'s resolved/inferred
        legacy fields (preserving their meaning and defaults, Req 1.6, 14.1); the
        on-disk manifest is re-read to recover the additive Module_Platform
        sections (``provides``, ``required_permissions``, ``required_secrets``,
        ``compatibility``) and the raw ``dependencies`` carrying each ``check``
        command. Author-declared values override the inferred ones.
        """
        manifest_path = str(raw_record.get("manifest_path") or "")
        raw_manifest = self._load_raw_manifest(manifest_path)
        merged: dict[str, Any] = {**dict(raw_record), **raw_manifest}
        for key in _RAW_PASSTHROUGH_KEYS:
            if key in raw_manifest:
                merged[key] = raw_manifest[key]

        manifest = parse_manifest(merged, manifest_path)
        return ModuleRecord(
            manifest=manifest,
            state=ModuleState.DISCOVERED,
            trust_level=manifest.trust_level,
        )

    def _load_raw_manifest(self, manifest_path: str) -> dict[str, Any]:
        """Load the on-disk manifest mapping, or ``{}`` when it cannot be read.

        Failures (missing file, parse error) are swallowed and logged at debug
        level: the normalised record from ``SkillRegistry`` still provides the
        legacy fields, so adaptation degrades gracefully.
        """
        if not manifest_path:
            return {}
        full_path = Path(manifest_path)
        if not full_path.is_absolute():
            full_path = self._skill_registry.project_root / full_path
        if not full_path.is_file():
            return {}
        try:
            text = full_path.read_text(encoding="utf-8")
            if full_path.name == "SKILL.md":
                data, _body, _error = SkillRegistry._parse_frontmatter(text)  # noqa: SLF001
            elif full_path.suffix in {".yaml", ".yml"}:
                data = yaml.safe_load(text) or {}
            elif full_path.suffix == ".json":
                data = json.loads(text)
            else:
                return {}
        except (OSError, ValueError, yaml.YAMLError):
            logger.debug("Could not load raw manifest %s", full_path, exc_info=True)
            return {}
        return data if isinstance(data, dict) else {}

    # ── Duplicate resolution (Req 2.4, 3.6) ────────────────────────────

    @staticmethod
    def _resolve_duplicates(records: list[ModuleRecord]) -> list[ModuleRecord]:
        """Keep one record per ``module_id``, preferring the first manifest path.

        When two or more records share a ``module_id``, the record whose manifest
        path sorts first lexicographically wins; the rest are rejected and the
        conflict is logged identifying the duplicated id and the rejected paths
        (Req 2.4, 3.6).
        """
        winners: dict[str, ModuleRecord] = {}
        for record in records:
            module_id = record.module_id
            incumbent = winners.get(module_id)
            if incumbent is None:
                winners[module_id] = record
                continue
            kept, rejected = (
                (incumbent, record)
                if incumbent.manifest.manifest_path <= record.manifest.manifest_path
                else (record, incumbent)
            )
            winners[module_id] = kept
            logger.warning(
                "Duplicate module_id %r: keeping %s, rejecting %s",
                module_id,
                kept.manifest.manifest_path,
                rejected.manifest.manifest_path,
            )
        return list(winners.values())

    # ── Debug logging for skipped paths (Req 2.2, 2.6) ─────────────────

    def _log_skipped_roots(self) -> None:
        """Log every configured module root that does not exist (Req 2.2)."""
        for root in self._skill_registry.roots:
            if not root.exists():
                logger.debug("Skipping missing module root: %s", root)

    def _log_manifestless_directories(self) -> None:
        """Log immediate child directories without a recognised manifest (Req 2.6)."""
        for root in self._skill_registry.roots:
            if not root.is_dir():
                continue
            try:
                children = sorted(root.iterdir())
            except OSError:
                logger.debug("Could not list module root: %s", root, exc_info=True)
                continue
            for child in children:
                if not child.is_dir():
                    continue
                if not any((child / name).is_file() for name in _MANIFEST_FILENAMES):
                    logger.debug(
                        "Skipping directory without a module manifest: %s", child
                    )
