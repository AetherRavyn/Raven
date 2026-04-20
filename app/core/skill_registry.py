from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_MANIFEST_FILENAMES: tuple[tuple[str, int], ...] = (
    ("module.yaml", 0),
    ("module.yml", 0),
    ("manifest.json", 1),
    ("SKILL.md", 2),
)

_DEFAULT_ROOTS: tuple[str, ...] = ("skills", "plugins", "agent_reach/skill")


class SkillRegistry:
    """Discover skill and plugin manifests from the repository tree."""

    def __init__(
        self,
        project_root: str | Path | None = None,
        roots: list[str | Path] | None = None,
    ) -> None:
        base_root = project_root or Path(__file__).resolve().parents[2]
        self.project_root = Path(base_root).resolve()
        self.roots = [
            self._resolve_root(root) for root in (roots or list(_DEFAULT_ROOTS))
        ]

    def _resolve_root(self, root: str | Path) -> Path:
        root_path = Path(root)
        if root_path.is_absolute():
            return root_path
        return self.project_root / root_path

    @staticmethod
    def _titleize(value: str) -> str:
        title = re.sub(r"[._-]+", " ", value).strip()
        return title.title() if title else "Untitled"

    @staticmethod
    def _module_id_from_name(name: str, package_kind: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")
        slug = slug or "module"
        prefix = (
            package_kind
            if package_kind in {"skill", "plugin", "integration"}
            else "skill"
        )
        return f"{prefix}.{slug}"

    @staticmethod
    def _to_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, tuple):
            return [str(item).strip() for item in value if str(item).strip()]
        item = str(value).strip()
        return [item] if item else []

    @staticmethod
    def _body_summary(body: str) -> str:
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("-"):
                continue
            return stripped[:180]
        return ""

    @staticmethod
    def _package_kind(path: Path) -> str:
        parts = {part.lower() for part in path.parts}
        if "plugins" in parts:
            return "plugin"
        if "agent_reach" in parts:
            return "integration"
        return "skill"

    def _discover_manifest_files(self) -> list[Path]:
        candidates: dict[Path, tuple[int, Path]] = {}
        for root in self.roots:
            if not root.exists():
                continue
            for filename, priority in _MANIFEST_FILENAMES:
                for path in root.rglob(filename):
                    if not path.is_file():
                        continue
                    directory = path.parent.resolve()
                    current = candidates.get(directory)
                    if (
                        current is None
                        or priority < current[0]
                        or (priority == current[0] and str(path) < str(current[1]))
                    ):
                        candidates[directory] = (priority, path)
        return [
            item[1]
            for item in sorted(candidates.values(), key=lambda item: str(item[1]))
        ]

    @staticmethod
    def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str, str | None]:
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            return {}, text, None
        end_index: int | None = None
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                end_index = index
                break
        if end_index is None:
            return {}, text, "Frontmatter end marker missing"
        frontmatter_text = "\n".join(lines[1:end_index])
        body = "\n".join(lines[end_index + 1 :])
        try:
            data = yaml.safe_load(frontmatter_text) or {}
        except Exception as exc:
            return {}, body, str(exc)
        if not isinstance(data, dict):
            return {}, body, "Frontmatter did not parse to a mapping"
        return data, body, None

    def _load_manifest(self, path: Path) -> tuple[dict[str, Any], str, str | None, str]:
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception as exc:
            return {}, "", str(exc), path.name

        if path.name == "SKILL.md":
            data, body, error = self._parse_frontmatter(raw)
            return data, body, error, path.name

        try:
            if path.suffix in {".yaml", ".yml"}:
                data = yaml.safe_load(raw) or {}
            elif path.suffix == ".json":
                data = json.loads(raw)
            else:
                data = {}
        except Exception as exc:
            return {}, "", str(exc), path.name

        if not isinstance(data, dict):
            return {}, "", f"{path.name} did not parse to a mapping", path.name
        return data, "", None, path.name

    def _normalize_record(
        self,
        path: Path,
        raw: dict[str, Any],
        body: str,
        parse_error: str | None,
        manifest_kind: str,
    ) -> dict[str, Any]:
        package_kind = self._package_kind(path)
        metadata_raw = raw.get("metadata")
        metadata: dict[str, Any] = (
            metadata_raw if isinstance(metadata_raw, dict) else {}
        )
        explicit_name = raw.get("display_name") or raw.get("name")
        display_name = str(explicit_name or self._titleize(path.parent.name))
        module_id = str(
            raw.get("module_id")
            or raw.get("id")
            or self._module_id_from_name(
                explicit_name or path.parent.name, package_kind
            )
        )
        version_explicit = raw.get("version")
        version = str(version_explicit or "0.1.0")
        category = str(raw.get("category") or package_kind)
        description = str(raw.get("description") or self._body_summary(body) or "")
        trust_level = str(
            raw.get("trust_level")
            or ("external" if package_kind == "integration" else "workspace")
        )
        canonical_manifest = manifest_kind in {
            "module.yaml",
            "module.yml",
            "manifest.json",
        }
        enabled_by_default = bool(raw.get("enabled_by_default", canonical_manifest))
        tags = self._to_list(raw.get("tags") or metadata.get("tags"))
        capabilities = self._to_list(
            raw.get("capabilities") or metadata.get("capabilities") or tags
        )
        maintainers = self._to_list(
            raw.get("maintainers") or metadata.get("maintainers")
        )
        homepage = raw.get("homepage") or metadata.get("homepage")
        openclaw_meta = metadata.get("openclaw")
        if not homepage and isinstance(openclaw_meta, dict):
            homepage = openclaw_meta.get("homepage")

        try:
            source_path = str(path.parent.relative_to(self.project_root))
        except Exception:
            source_path = str(path.parent)

        try:
            manifest_path = str(path.relative_to(self.project_root))
        except Exception:
            manifest_path = str(path)

        try:
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        except Exception:
            modified_at = datetime.now(timezone.utc)

        record = {
            "schema_version": str(raw.get("schema_version") or "1.0"),
            "module_id": module_id,
            "display_name": display_name,
            "version": version,
            "category": category,
            "description": description,
            "owner": raw.get("owner"),
            "maintainers": maintainers,
            "tags": tags,
            "subcategory": raw.get("subcategory"),
            "stability": str(
                raw.get("stability")
                or ("beta" if canonical_manifest else "experimental")
            ),
            "maturity": str(raw.get("maturity") or "development"),
            "homepage": homepage,
            "docs": raw.get("docs") or manifest_path,
            "source_path": source_path,
            "entrypoint": raw.get("entrypoint"),
            "license": raw.get("license"),
            "enabled_by_default": enabled_by_default,
            "trust_level": trust_level,
            "package_kind": package_kind,
            "manifest_kind": manifest_kind,
            "canonical_manifest": canonical_manifest,
            "capabilities": capabilities,
            "active_capabilities": capabilities,
            "degraded_capabilities": [],
            "dependency_status": self._normalize_dependencies(raw.get("dependencies")),
            "manifest_path": manifest_path,
            "last_modified": modified_at.isoformat(),
            "parse_error": parse_error,
            "body": body,
        }
        record["health"] = self._build_health_report(
            record, raw, parse_error, modified_at
        )
        record["health_state"] = record["health"]["state"]
        record["onboarding_hint"] = self._onboarding_hint(record)
        return record

    @staticmethod
    def _normalize_dependencies(value: Any) -> list[dict[str, Any]]:
        if not value:
            return []
        if isinstance(value, list):
            deps: list[dict[str, Any]] = []
            for item in value:
                if isinstance(item, dict):
                    deps.append(
                        {
                            "name": item.get("name")
                            or item.get("module_id")
                            or "unknown",
                            "status": item.get("status") or "unknown",
                            "required": bool(item.get("required", True)),
                            "message": item.get("message") or "",
                        }
                    )
                else:
                    deps.append(
                        {
                            "name": str(item),
                            "status": "unknown",
                            "required": True,
                            "message": "",
                        }
                    )
            return deps
        if isinstance(value, dict):
            return [
                {
                    "name": key,
                    "status": str(item.get("status") or "unknown"),
                    "required": bool(item.get("required", True)),
                    "message": str(item.get("message") or ""),
                }
                for key, item in value.items()
                if isinstance(item, dict)
            ]
        return [
            {"name": str(value), "status": "unknown", "required": True, "message": ""}
        ]

    @staticmethod
    def _add_check(
        checks: list[dict[str, Any]],
        name: str,
        status: str,
        severity: str,
        message: str,
    ) -> None:
        checks.append(
            {
                "name": name,
                "status": status,
                "severity": severity,
                "message": message,
                "last_success_at": None,
                "last_failure_at": None,
            }
        )

    def _build_health_report(
        self,
        record: dict[str, Any],
        raw: dict[str, Any],
        parse_error: str | None,
        modified_at: datetime,
    ) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        error_count = 0
        warning_count = 0

        if parse_error:
            self._add_check(checks, "manifest_parse", "fail", "critical", parse_error)
            error_count += 1
        else:
            self._add_check(
                checks, "manifest_parse", "pass", "info", "Manifest parsed successfully"
            )

        critical_missing = []
        for field in ("display_name", "description"):
            has_value = bool(raw.get(field))
            if field == "display_name" and not has_value:
                has_value = bool(raw.get("name"))
            if not has_value:
                critical_missing.append(field)

        if critical_missing:
            self._add_check(
                checks,
                "identity_fields",
                "fail",
                "critical",
                f"Missing required fields: {', '.join(sorted(critical_missing))}",
            )
            error_count += 1
        else:
            self._add_check(
                checks,
                "identity_fields",
                "pass",
                "info",
                "Display name and description are present",
            )

        inferred_missing = []
        for field in ("schema_version", "module_id", "version", "category"):
            has_value = bool(raw.get(field))
            if field == "module_id" and not has_value:
                has_value = bool(raw.get("name") or raw.get("display_name"))
            if not has_value:
                inferred_missing.append(field)

        if inferred_missing:
            if record["canonical_manifest"]:
                self._add_check(
                    checks,
                    "canonical_fields",
                    "fail",
                    "error",
                    f"Missing required canonical fields: {', '.join(sorted(inferred_missing))}",
                )
                error_count += 1
            else:
                self._add_check(
                    checks,
                    "canonical_fields",
                    "warn",
                    "warning",
                    "Add module.yaml or manifest.json to make this a canonical manifest.",
                )
                warning_count += 1
        else:
            self._add_check(
                checks,
                "canonical_fields",
                "pass",
                "info",
                "Canonical manifest fields are present",
            )

        version_value = str(record.get("version") or "")
        if re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version_value):
            self._add_check(
                checks,
                "version_format",
                "pass",
                "info",
                "Version string looks semantic",
            )
        else:
            self._add_check(
                checks,
                "version_format",
                "warn",
                "warning",
                "Version is missing or non-semantic; add a proper semantic version.",
            )
            warning_count += 1

        category = str(record.get("category") or "")
        if category in {"skill", "plugin", "integration", "connector", "tool"}:
            self._add_check(
                checks,
                "category",
                "pass",
                "info",
                f"Category set to {category}",
            )
        else:
            self._add_check(
                checks,
                "category",
                "warn",
                "warning",
                f"Category {category!r} is outside the common registry set.",
            )
            warning_count += 1

        module_id = str(record.get("module_id") or "")
        if re.fullmatch(r"[a-z0-9]+(?:[._][a-z0-9]+)*", module_id):
            self._add_check(
                checks,
                "module_id",
                "pass",
                "info",
                "Module identifier is normalized",
            )
        else:
            self._add_check(
                checks,
                "module_id",
                "warn",
                "warning",
                "Module identifier should be lowercase and dot/underscore separated.",
            )
            warning_count += 1

        if record["canonical_manifest"]:
            self._add_check(
                checks,
                "manifest_kind",
                "pass",
                "info",
                f"Using canonical manifest file ({record['manifest_kind']})",
            )
        else:
            self._add_check(
                checks,
                "manifest_kind",
                "warn",
                "warning",
                "Only SKILL.md frontmatter was found; add a canonical manifest file.",
            )
            warning_count += 1

        active_capabilities = record.get("active_capabilities", []) or []
        if active_capabilities:
            self._add_check(
                checks,
                "capabilities",
                "pass",
                "info",
                f"Declared {len(active_capabilities)} capability/capabilities",
            )
        else:
            self._add_check(
                checks,
                "capabilities",
                "warn",
                "warning",
                "No capabilities were declared; add a capability list for routing.",
            )
            warning_count += 1

        if error_count:
            state = "unhealthy"
        elif warning_count:
            state = "degraded"
        else:
            state = "healthy"

        summary = (
            f"{record['display_name']} is ready"
            if state == "healthy"
            else f"{record['display_name']} needs registry cleanup"
            if state == "degraded"
            else f"{record['display_name']} has manifest issues"
        )

        return {
            "module_id": record["module_id"],
            "state": state,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "summary": summary,
            "checks": checks,
            "active_capabilities": active_capabilities,
            "degraded_capabilities": record.get("degraded_capabilities", []),
            "dependency_status": record.get("dependency_status", []),
            "last_error": parse_error,
            "uptime_seconds": max(
                0,
                int((datetime.now(timezone.utc) - modified_at).total_seconds()),
            ),
        }

    def _onboarding_hint(self, record: dict[str, Any]) -> str:
        if record["health_state"] == "healthy" and record["canonical_manifest"]:
            return ""
        if not record["canonical_manifest"]:
            return "Add module.yaml or manifest.json to make this registry entry canonical."
        return "Complete the manifest fields before enabling this module."

    def discover(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in self._discover_manifest_files():
            raw, body, parse_error, manifest_kind = self._load_manifest(path)
            record = self._normalize_record(path, raw, body, parse_error, manifest_kind)
            records.append(record)
        return sorted(records, key=lambda item: item["display_name"].lower())

    def summary(self, records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        entries = records or self.discover()
        package_counts: Counter[str] = Counter()
        state_counts: Counter[str] = Counter()
        onboarding_queue = 0
        for entry in entries:
            package_counts[entry.get("package_kind", "skill")] += 1
            state_counts[entry.get("health_state", "unknown")] += 1
            if entry.get("health_state") != "healthy" or not entry.get(
                "canonical_manifest"
            ):
                onboarding_queue += 1
        return {
            "count": len(entries),
            "healthy": state_counts.get("healthy", 0),
            "degraded": state_counts.get("degraded", 0),
            "unhealthy": state_counts.get("unhealthy", 0),
            "canonical": sum(1 for entry in entries if entry.get("canonical_manifest")),
            "inferred": sum(
                1 for entry in entries if not entry.get("canonical_manifest")
            ),
            "onboarding_queue": onboarding_queue,
            "package_kinds": dict(package_counts),
        }

    def onboarding_queue(
        self, records: list[dict[str, Any]] | None = None
    ) -> list[dict[str, Any]]:
        entries = records or self.discover()
        return [
            entry
            for entry in entries
            if entry.get("health_state") != "healthy"
            or not entry.get("canonical_manifest")
        ]

    def get_active_skill_texts(self) -> str:
        texts = []
        for record in self.discover():
            if record.get("health_state") == "healthy" and record.get(
                "enabled_by_default"
            ):
                body = record.get("body", "").strip()
                if body:
                    texts.append(f"### {record.get('display_name')}\n{body}")
        return "\n\n".join(texts)

    def load_plugin_tools(self) -> list[Any]:
        import importlib.util
        import sys

        tools = []
        for record in self.discover():
            entrypoint = record.get("entrypoint")
            if not entrypoint or ":" not in entrypoint:
                continue

            # Need to get the path relative to project_root to load the module
            manifest_path_str = record.get("manifest_path")
            if not manifest_path_str:
                continue

            manifest_path = self.project_root / manifest_path_str
            plugin_dir = manifest_path.parent

            module_file, func_name = entrypoint.split(":", 1)
            module_path = plugin_dir / module_file

            if not module_path.exists():
                logger.warning("Plugin entrypoint not found: %s", module_path)
                continue

            try:
                module_name = f"plugin_{record['module_id'].replace('.', '_')}"
                spec = importlib.util.spec_from_file_location(
                    module_name, str(module_path)
                )
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)

                    if hasattr(module, func_name):
                        get_tools_func = getattr(module, func_name)
                        plugin_tools = get_tools_func()
                        if isinstance(plugin_tools, list):
                            tools.extend(plugin_tools)
                        else:
                            logger.warning(
                                "Plugin %s returned non-list for tools",
                                record["module_id"],
                            )
            except Exception as e:
                logger.error("Failed to load plugin %s: %s", record["module_id"], e)

        return tools
