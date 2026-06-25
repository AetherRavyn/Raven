"""Module_CLI — list, inspect, and (later) manage modules from the command line.

The ``ModuleCLI`` is the ``ravyn modules ...`` command surface. It composes the
:class:`~app.modules.registry.ModuleRegistry` (the authoritative typed record
cache) and the :class:`~app.modules.loader.ModuleLoader` (the lifecycle
orchestrator) and renders human-readable output that mirrors the existing
``cmd_skills`` formatting conventions in ``app/cli/main.py``.

This module implements the read-only discoverability commands (Requirement 12):

* ``list_modules`` — every discovered module ordered by ``module_id`` with its
  ``module_id``, ``display_name``, ``version``, trust level, and enabled/disabled
  state, or a clear "no modules" message when nothing has been discovered
  (Req 12.1, 12.2).
* ``inspect`` — a single module's capability bundle, ``required_permissions``,
  ``required_secrets`` (names only — never values), dependency status, and latest
  health-check result ("no health-check result available" when none has run); an
  unknown ``module_id`` returns a not-found error and leaves the running system
  unchanged (Req 12.3, 12.4).

The ``scaffold`` command (task 11.2) creates a new module skeleton; the
``install`` command (task 11.3) is implemented separately and intentionally
omitted here.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from app.modules.manifest import parse_manifest, validate_manifest
from app.modules.models import ProvidesType, ScaffoldResult

if TYPE_CHECKING:
    from app.modules.loader import ModuleLoader
    from app.modules.models import HealthStatus, ModuleRecord
    from app.modules.registry import ModuleRegistry

logger = logging.getLogger(__name__)

# Fallback running platform version used for the scaffolded-manifest smoke check
# when the installed package metadata cannot be read (matches pyproject version).
_FALLBACK_RUNNING_VERSION = "0.1.0"

# The two categories a scaffolded module may declare; selects the target tree.
_CATEGORY_DIRS: dict[str, str] = {"tool": "tools", "agent": "agents"}

# Inclusive bounds for a raw module name (Req 11.1, 11.3).
_NAME_MIN_LEN = 1
_NAME_MAX_LEN = 64


def _running_version() -> str:
    """Return the running AetherRavyn version for the manifest smoke check.

    Reads the installed package version, falling back to the pinned project
    version when the metadata is unavailable (e.g. running from a source tree
    that was never installed). Mirrors ``app.modules.loader._running_version``.
    """
    try:
        from importlib.metadata import version

        return version("raven")
    except Exception:  # noqa: BLE001 - metadata is best-effort; fall back to pinned
        return _FALLBACK_RUNNING_VERSION


# A short glyph per health state, mirroring the check marks ``cmd_skills`` uses.
_HEALTH_GLYPHS: dict[str, str] = {
    "healthy": "✓",
    "degraded": "!",
    "unhealthy": "✗",
    "unknown": "?",
}

# Stable display order for capability-bundle entries grouped by contribution type.
_PROVIDES_ORDER: tuple[ProvidesType, ...] = (
    ProvidesType.TOOL,
    ProvidesType.AGENT,
    ProvidesType.SKILL,
    ProvidesType.EVENT_SOURCE,
    ProvidesType.ANOMALY_DETECTOR,
    ProvidesType.PROACTIVE_REACTION,
    ProvidesType.UI_SURFACE,
)


class ModuleCLI:
    """Command handlers for the ``ravyn modules`` CLI surface.

    Composes a :class:`ModuleRegistry` (record cache + discovery) and a
    :class:`ModuleLoader` (lifecycle transitions). The handlers in this class are
    read-only; the lifecycle-mutating subcommands are dispatched directly to the
    loader by ``app/cli/main.py``.
    """

    def __init__(self, registry: ModuleRegistry, loader: ModuleLoader) -> None:
        self._registry = registry
        self._loader = loader

    # ── List (Req 12.1, 12.2) ──────────────────────────────────────────

    async def list_modules(self) -> str:
        """Return every discovered module ordered by ``module_id`` as a table.

        The registry already orders :meth:`ModuleRegistry.all` by ``module_id``
        (Req 12.1). Each row shows the module's ``module_id``, ``display_name``,
        ``version``, trust level, and enabled/disabled state. When no modules have
        been discovered a clear message is returned instead of an empty table
        (Req 12.2).
        """
        records = self._registry.all()
        if not records:
            return "No modules found. Drop a module directory into a configured module root."

        lines = [
            f"\n🦅 AetherRavyn Modules ({len(records)} total)\n",
            f"{'Module ID':<32} {'Name':<24} {'Version':<10} {'Trust':<11} {'State':<13}",
            "─" * 94,
        ]
        for record in records:
            manifest = record.manifest
            lines.append(
                f"{manifest.module_id:<32} "
                f"{self._truncate(manifest.display_name, 24):<24} "
                f"{self._truncate(manifest.version, 10):<10} "
                f"{record.trust_level:<11} "
                f"{record.state.value:<13}"
            )
        return "\n".join(lines)

    # ── Inspect (Req 12.3, 12.4) ───────────────────────────────────────

    async def inspect(self, module_id: str) -> str:
        """Return a detailed view of one module, or a not-found error.

        Shows the module's capability bundle (its declared ``provides`` entries),
        ``required_permissions``, ``required_secrets`` (names only — secret values
        are never read or displayed), dependency-resolution status, and the latest
        health-check result, indicating "no health-check result available" when no
        check has run (Req 12.3). When ``module_id`` is not among the discovered
        modules a not-found error string is returned; this method performs no
        mutation, so the running system is left unchanged (Req 12.4).
        """
        record = self._registry.get(module_id)
        if record is None:
            logger.debug("Inspect requested for unknown module %r", module_id)
            return f"Module not found: {module_id!r}. Run 'ravyn modules list' to see available modules."

        manifest = record.manifest
        sections: list[str] = [
            f"\n🦅 Module: {manifest.display_name} ({manifest.module_id})",
            f"  Version:     {manifest.version}",
            f"  Category:    {manifest.category}",
            f"  Trust level: {record.trust_level}",
            f"  State:       {record.state.value}",
            "",
            self._render_bundle(record),
            "",
            self._render_permissions(record),
            "",
            self._render_secrets(record),
            "",
            self._render_dependencies(record),
            "",
            self._render_health(record.health),
        ]
        return "\n".join(sections)

    # ── Scaffold (Req 11.1, 11.2, 11.3) ────────────────────────────────

    def scaffold(self, name: str, category: str) -> ScaffoldResult:
        """Create a new module skeleton, or reject an invalid/colliding request.

        Validates that ``name`` is 1-64 characters and normalizes it into a legal
        ``module_id`` (lowercased, with each run of non-alphanumeric characters
        collapsed to a single underscore), and that ``category`` is ``tool`` or
        ``agent`` (Req 11.1). On success it atomically creates a module directory
        under ``app/tools/`` (for ``tool``) or ``app/agents/`` (for ``agent``)
        containing a ``module.yaml``, a ``SKILL.md``, and one placeholder
        implementation file; the generated ``module.yaml`` passes the Requirement
        3 manifest validation without further edits (Req 11.2).

        Creation is atomic: the files are written into a temporary directory,
        the generated manifest is smoke-checked with ``parse_manifest`` +
        ``validate_manifest``, and only then is the directory moved into place
        with a single rename. An empty name, an over-length name, a name that does
        not yield a legal ``module_id``, an invalid category, or a name that
        resolves to an existing module directory is rejected with no files created
        and the filesystem left unchanged (Req 11.3).
        """
        raw_name = name.strip()
        if not (_NAME_MIN_LEN <= len(raw_name) <= _NAME_MAX_LEN):
            return ScaffoldResult(
                ok=False,
                detail=(
                    f"Invalid module name: must be {_NAME_MIN_LEN}-{_NAME_MAX_LEN} "
                    f"characters (got {len(raw_name)})."
                ),
            )

        if category not in _CATEGORY_DIRS:
            return ScaffoldResult(
                ok=False,
                detail=(
                    f"Invalid category {category!r}: must be one of "
                    + ", ".join(sorted(_CATEGORY_DIRS))
                    + "."
                ),
            )

        module_id = self._normalize_module_id(raw_name)
        if not module_id:
            return ScaffoldResult(
                ok=False,
                detail=(
                    f"Invalid module name {name!r}: does not yield a legal module_id "
                    "(lowercase alphanumeric segments separated by underscores)."
                ),
            )

        parent = self._registry.project_root / "app" / _CATEGORY_DIRS[category]
        target_dir = parent / module_id
        if target_dir.exists():
            return ScaffoldResult(
                ok=False,
                module_id=module_id,
                detail=f"Module directory already exists: {target_dir}. Choose a different name.",
            )

        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.debug("Could not create parent directory %s", parent, exc_info=True)
            return ScaffoldResult(
                ok=False,
                module_id=module_id,
                detail=f"Could not prepare target directory {parent}: {exc}.",
            )

        return self._materialize(raw_name, module_id, category, parent, target_dir)

    def _materialize(
        self,
        display_name: str,
        module_id: str,
        category: str,
        parent: Path,
        target_dir: Path,
    ) -> ScaffoldResult:
        """Write the skeleton into a temp dir, smoke-check it, then move it atomically.

        Any failure (write error, manifest validation failure, or a collision
        detected at the final rename) discards the temporary directory so no
        partial output is left behind (Req 11.2, 11.3).
        """
        class_name = self._class_name(module_id, category)
        placeholder_name = f"{module_id}.py"
        manifest_text = self._render_manifest(
            display_name, module_id, category, placeholder_name, class_name
        )
        skill_text = self._render_skill_md(display_name, module_id, category)
        placeholder_text = (
            self._render_tool_placeholder(module_id, class_name)
            if category == "tool"
            else self._render_agent_placeholder(display_name, class_name)
        )

        tmp_dir = Path(tempfile.mkdtemp(prefix=f".{module_id}.scaffold.", dir=parent))
        try:
            (tmp_dir / "module.yaml").write_text(manifest_text, encoding="utf-8")
            (tmp_dir / "SKILL.md").write_text(skill_text, encoding="utf-8")
            (tmp_dir / placeholder_name).write_text(placeholder_text, encoding="utf-8")

            self._smoke_check_manifest(tmp_dir / "module.yaml")

            os.replace(tmp_dir, target_dir)
        except (OSError, ValueError) as exc:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            logger.debug(
                "Scaffold for %r failed; rolled back", module_id, exc_info=True
            )
            return ScaffoldResult(
                ok=False,
                module_id=module_id,
                detail=f"Failed to scaffold module {module_id!r}: {exc}.",
            )

        created = [
            str(target_dir / "module.yaml"),
            str(target_dir / "SKILL.md"),
            str(target_dir / placeholder_name),
        ]
        logger.info("Scaffolded %s module %r at %s", category, module_id, target_dir)
        return ScaffoldResult(
            ok=True,
            created_paths=created,
            module_id=module_id,
            detail=f"Created {category} module {module_id!r} at {target_dir}.",
        )

    @staticmethod
    def _smoke_check_manifest(manifest_path: Path) -> None:
        """Parse and validate the generated manifest, raising ``ValueError`` on failure.

        Guarantees the scaffolded ``module.yaml`` satisfies the Requirement 3
        manifest validation before the skeleton is published (Req 11.2).
        """
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("generated manifest is not a mapping")
        manifest = parse_manifest(raw, str(manifest_path))
        result = validate_manifest(manifest, _running_version())
        if not result.ok:
            raise ValueError(f"generated manifest failed validation: {result.reason}")

    @staticmethod
    def _normalize_module_id(name: str) -> str:
        """Normalize a raw name into a legal ``module_id`` (empty if none results).

        The name is lowercased and every run of characters outside ``[a-z0-9]`` is
        collapsed to a single underscore, with leading/trailing underscores
        trimmed. The result is a lowercase alphanumeric/underscore identifier that
        satisfies the manifest ``module_id`` pattern, or the empty string when the
        name contains no usable characters.
        """
        slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
        return slug

    @staticmethod
    def _class_name(module_id: str, category: str) -> str:
        """Derive a PascalCase class name for the placeholder, suffixed by category."""
        parts = [segment for segment in module_id.split("_") if segment]
        pascal = "".join(segment.capitalize() for segment in parts) or "Module"
        return f"{pascal}{category.capitalize()}"

    @staticmethod
    def _render_manifest(
        display_name: str,
        module_id: str,
        category: str,
        placeholder_name: str,
        class_name: str,
    ) -> str:
        """Render a ``module.yaml`` whose required fields pass validation (Req 11.2)."""
        data: dict[str, object] = {
            "schema_version": "1.0",
            "module_id": module_id,
            "display_name": display_name,
            "version": "0.1.0",
            "category": category,
            "description": f"Scaffolded {category} module: {display_name}.",
            "trust_level": "workspace",
            "stability": "experimental",
            "origin": "community",
            "enabled_by_default": False,
            "compatibility": {"min_ravyn_version": "0.0.0", "schema_version": "1.0"},
            "provides": [
                {
                    "type": category,
                    "name": module_id,
                    "entrypoint": f"{placeholder_name}:{class_name}",
                }
            ],
            "required_permissions": [],
            "required_secrets": [],
        }
        header = (
            "# Generated by `ravyn modules scaffold`. Edit to implement your module.\n"
        )
        return header + yaml.safe_dump(data, sort_keys=False)

    @staticmethod
    def _render_skill_md(display_name: str, module_id: str, category: str) -> str:
        """Render a minimal ``SKILL.md`` describing the scaffolded module."""
        return (
            f"# {display_name}\n\n"
            f"- **Module ID:** `{module_id}`\n"
            f"- **Category:** `{category}`\n"
            f"- **Status:** scaffolded placeholder — replace with your implementation.\n\n"
            "## Overview\n\n"
            f"Describe what this {category} module does, its triggers, and the "
            "permissions or secrets it needs.\n"
        )

    @staticmethod
    def _render_tool_placeholder(module_id: str, class_name: str) -> str:
        """Render a ``BaseTool`` subclass stub (matches ``app/tools/base.py``)."""
        return (
            '"""Placeholder tool generated by `ravyn modules scaffold`."""\n\n'
            "from __future__ import annotations\n\n"
            "from typing import Any\n\n"
            "from app.tools.base import BaseTool, ToolSchema\n\n\n"
            f"class {class_name}(BaseTool):\n"
            '    """Auto-generated placeholder tool. Replace with your implementation."""\n\n'
            f'    group = "{module_id}"\n\n'
            "    def get_name(self) -> str:\n"
            f'        return "{module_id}"\n\n'
            "    def get_description(self) -> str:\n"
            '        return "Placeholder tool scaffolded by `ravyn modules scaffold`."\n\n'
            "    def get_schema(self) -> ToolSchema:\n"
            "        return ToolSchema(\n"
            "            name=self.get_name(),\n"
            "            description=self.get_description(),\n"
            "            parameters=[],\n"
            "        )\n\n"
            "    async def execute(self, **kwargs: Any) -> dict[str, Any]:\n"
            '        return {"ok": False, "detail": "Not implemented yet."}\n'
        )

    @staticmethod
    def _render_agent_placeholder(display_name: str, class_name: str) -> str:
        """Render a ``BaseAgent`` subclass stub (matches ``app/agents/base.py``)."""
        return (
            '"""Placeholder agent generated by `ravyn modules scaffold`."""\n\n'
            "from __future__ import annotations\n\n"
            "from app.agents.base import BaseAgent\n"
            "from app.tools.base import BaseTool\n\n\n"
            f"class {class_name}(BaseAgent):\n"
            '    """Auto-generated placeholder agent. Replace with your implementation."""\n\n'
            "    @property\n"
            "    def name(self) -> str:\n"
            f'        return "{display_name}"\n\n'
            "    @property\n"
            "    def role_prompt(self) -> str:\n"
            '        return "Placeholder agent scaffolded by `ravyn modules scaffold`."\n\n'
            "    @property\n"
            "    def tools(self) -> list[BaseTool]:\n"
            "        return []\n"
        )

    # ── Inspect section renderers ──────────────────────────────────────

    def _render_bundle(self, record: ModuleRecord) -> str:
        """Render the module's capability bundle from its declared ``provides``."""
        provides = record.manifest.provides
        if not provides:
            return "Capability bundle:\n  (none declared)"

        grouped: dict[ProvidesType, list[str]] = {}
        for entry in provides:
            grouped.setdefault(entry.type, []).append(entry.name or "(unnamed)")

        lines = ["Capability bundle:"]
        for provides_type in _PROVIDES_ORDER:
            names = grouped.get(provides_type)
            if not names:
                continue
            label = provides_type.value.replace("_", " ")
            lines.append(f"  {label}: {', '.join(names)}")
        return "\n".join(lines)

    def _render_permissions(self, record: ModuleRecord) -> str:
        """Render required permissions plus any granted/pending detail."""
        required = record.manifest.required_permissions
        lines = [
            "Required permissions: " + (", ".join(required) if required else "(none)")
        ]
        if record.granted_permissions:
            lines.append("  Granted: " + ", ".join(record.granted_permissions))
        if record.pending_permissions:
            lines.append(
                "  Pending operator approval: " + ", ".join(record.pending_permissions)
            )
        return "\n".join(lines)

    def _render_secrets(self, record: ModuleRecord) -> str:
        """Render required-secret *names* only, never any secret value (Req 12.3)."""
        required = record.manifest.required_secrets
        if not required:
            return "Required secrets: (none)"

        lines = ["Required secrets (names only):"]
        for key in required:
            presence = record.secret_presence.get(key)
            if presence is True:
                status = "present"
            elif presence is False:
                status = "absent"
            else:
                status = "not checked"
            lines.append(f"  {key}: {status}")
        return "\n".join(lines)

    def _render_dependencies(self, record: ModuleRecord) -> str:
        """Render dependency-resolution status, falling back to declared deps."""
        resolved = record.resolved_dependencies
        if resolved:
            lines = ["Dependency status:"]
            for dep in resolved:
                kind = "required" if dep.required else "optional"
                detail = f" — {dep.message}" if dep.message else ""
                lines.append(f"  {dep.name}: {dep.status} ({kind}){detail}")
            return "\n".join(lines)

        declared = record.manifest.dependencies
        if not declared:
            return "Dependency status: (none declared)"
        lines = ["Dependency status:"]
        for dep in declared:
            kind = "required" if dep.required else "optional"
            lines.append(f"  {dep.name}: not yet resolved ({kind})")
        return "\n".join(lines)

    def _render_health(self, health: HealthStatus | None) -> str:
        """Render the latest health-check result, or the "none available" message."""
        if health is None or not health.has_run:
            return "Latest health: no health-check result available"

        glyph = _HEALTH_GLYPHS.get(health.state, "?")
        lines = [f"Latest health: {glyph} {health.state}"]
        if health.summary:
            lines.append(f"  {health.summary}")
        for check in health.checks:
            name = check.get("name", "check")
            status = check.get("status", "")
            message = check.get("message", "")
            lines.append(f"    - {name}: {status} — {message}")
        return "\n".join(lines)

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _truncate(value: str, width: int) -> str:
        """Truncate ``value`` to ``width`` characters with an ellipsis when longer."""
        if len(value) <= width:
            return value
        return value[: max(0, width - 1)] + "…"
