"""Skill Marketplace — discover, install, publish, and share skills.

Provides a ``SkillMarketplace`` that manages:
- Multi-source skill discovery (bundled, installed, community, remote hubs)
- Remote hub sources: GitHub repos, raw URLs, well-known endpoints
- Security scanning and trust levels before install
- Skill versioning and update checks
- Publishing to community directory
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Well-known skill hub sources (mirrors Hermes Agent's approach)
WELL_KNOWN_HUBS: list[dict[str, Any]] = [
    {
        "name": "skills.sh",
        "type": "api",
        "url": "https://skills.sh/api/v1/skills",
        "description": "Official skills.sh community registry",
    },
    {
        "name": "github-taps",
        "type": "github-tap",
        "taps": [
            "https://github.com/topics/hermes-skill",
            "https://github.com/topics/ai-skill",
        ],
        "description": "GitHub topic-based skill discovery",
    },
    {
        "name": "lobehub",
        "type": "api",
        "url": "https://chat-agents.lobehub.com/api/agents",
        "description": "LobeHub agent marketplace",
    },
]

# Suspicious patterns flagged during security scanning
_SUSPICIOUS_PATTERNS: list[tuple[str, str, str]] = [
    ("env_read", r"os\.environ\[", "Reads environment variables (potential secret leak)"),
    ("env_getenv", r"os\.getenv\(", "Reads environment variables (potential secret leak)"),
    (
        "subprocess_shell",
        r"subprocess\.(Popen|call|run|check_output).*shell=True",
        "Shell execution with shell=True",
    ),
    ("eval_exec", r"\beval\(", "Dynamic code execution"),
    ("exec_call", r"\bexec\(", "Dynamic code execution"),
    ("compile", r"\bcompile\(", "Dynamic code compilation"),
    ("base64_decode", r"base64\.b64decode", "Base64 decode (potential obfuscation)"),
    ("requests_post", r"requests\.(post|put|patch|delete)\(", "Outbound HTTP write operation"),
    ("file_write", r"open\(.*['\"][^'\"]*['\"],\s*['\"]w['\"]", "Write to arbitrary file paths"),
    ("file_delete", r"os\.(remove|unlink)\(", "Deletes files"),
    ("rm_rf", r"shutil\.rmtree", "Recursive directory deletion"),
    ("chmod", r"os\.chmod\(", "Changes file permissions"),
    ("import_http", r"import\s+http\.server", "Starts an HTTP server"),
    ("import_socket", r"import\s+socket", "Raw network access"),
]


# ─── Security Scanner ─────────────────────────────────────────────


class SkillSecurityScanner:
    """Scans skill files for suspicious patterns before installation."""

    def __init__(self) -> None:
        self._suspicious = _SUSPICIOUS_PATTERNS

    def scan(self, skill_dir: Path) -> dict[str, Any]:
        """Scan a skill directory for security issues.

        Returns a report with:
        - ``safe``: True if no high-severity issues found
        - ``warnings``: list of potential concerns
        - ``severity``: overall severity level
        """
        warnings: list[dict[str, Any]] = []
        for py_file in skill_dir.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
                for pattern_id, pattern, description in self._suspicious:
                    if re.search(pattern, content):
                        warnings.append(
                            {
                                "file": str(py_file.relative_to(skill_dir)),
                                "pattern_id": pattern_id,
                                "description": description,
                                "severity": "medium"
                                if pattern_id in ("env_read", "env_getenv")
                                else "high",
                            }
                        )
            except Exception:
                continue

        severities = [w["severity"] for w in warnings]
        has_high = "high" in severities

        return {
            "safe": not has_high,
            "warning_count": len(warnings),
            "warnings": warnings[:20],
            "severity": "high" if has_high else ("medium" if severities else "low"),
        }


# ─── Skill Marketplace ────────────────────────────────────────────


class SkillMarketplace:
    """Discovers, installs, publishes, and manages skills."""

    def __init__(self, project_root: str | Path | None = None) -> None:
        self._project_root = Path(project_root).resolve() if project_root else _PROJECT_ROOT
        self._skills_dir = self._project_root / "skills"
        self._bundled_dir = self._skills_dir / "bundled"
        self._community_dir = self._skills_dir / "community"
        self._installed_dir = self._skills_dir / "installed"
        self._hubs_cache_dir = self._skills_dir / ".hub_cache"
        self._hubs_cache_dir.mkdir(parents=True, exist_ok=True)

    # ── Discovery ──────────────────────────────────────────────────

    def search(self, query: str, include_remote: bool = False) -> list[dict[str, Any]]:
        """Search for skills by name, description, or tags across sources."""
        results: list[dict[str, Any]] = []
        query_lower = query.lower()

        for source, base_dir in [
            ("bundled", self._bundled_dir),
            ("installed", self._installed_dir),
            ("community", self._community_dir),
        ]:
            if base_dir.exists():
                for skill_dir in base_dir.iterdir():
                    if not skill_dir.is_dir():
                        continue
                    meta = self._read_skill_meta(skill_dir)
                    if meta and self._matches_query(meta, query_lower):
                        meta["source"] = source
                        results.append(meta)

        if include_remote:
            remote = self._search_remote(query_lower)
            results.extend(remote)

        return results

    def list_all(self) -> dict[str, list[dict[str, Any]]]:
        """List all skills grouped by source."""
        catalog: dict[str, list[dict[str, Any]]] = {
            "bundled": [],
            "installed": [],
            "community": [],
        }
        for source, base_dir in [
            ("bundled", self._bundled_dir),
            ("installed", self._installed_dir),
            ("community", self._community_dir),
        ]:
            if base_dir.exists():
                for skill_dir in base_dir.iterdir():
                    if not skill_dir.is_dir():
                        continue
                    meta = self._read_skill_meta(skill_dir)
                    if meta:
                        meta["source"] = source
                        meta["path"] = str(skill_dir)
                        catalog[source].append(meta)
        return catalog

    def get_info(self, skill_name: str) -> dict[str, Any] | None:
        """Get detailed info about a skill from any source."""
        for base_dir in [self._bundled_dir, self._installed_dir, self._community_dir]:
            skill_dir = base_dir / skill_name
            if skill_dir.exists():
                meta = self._read_skill_meta(skill_dir)
                if meta:
                    skill_md = skill_dir / "SKILL.md"
                    if skill_md.exists():
                        meta["body"] = skill_md.read_text(encoding="utf-8")[:3000]
                    meta["path"] = str(skill_dir)
                    meta["source"] = (
                        "bundled"
                        if "bundled" in str(base_dir)
                        else "installed"
                        if "installed" in str(base_dir)
                        else "community"
                    )
                    return meta
        return None

    # ── Installation with Security Scanning ────────────────────────

    def install(
        self,
        source: str,
        name: str | None = None,
        trust_level: str = "warn",
    ) -> dict[str, Any]:
        """Install a skill from a URL, GitHub repo, or local path.

        Args:
            source: GitHub URL (``https://github.com/...``), raw file URL,
                    or local path (``/path/to/skill``).
            name: Override skill name (default: inferred from source).
            trust_level: ``"trust"`` (skip scan), ``"warn"`` (scan + warn),
                         ``"block"`` (scan + reject if unsafe).

        Returns:
            dict with ``success``, ``name``, ``path``, ``meta``, ``scan``.
        """
        skill_name = (name or source.rstrip("/").split("/")[-1].replace(".git", "")).strip()
        if not skill_name:
            return {"success": False, "error": "Could not determine skill name from source"}

        target_dir = self._installed_dir / skill_name
        if target_dir.exists():
            return {"success": False, "error": f"Skill '{skill_name}' is already installed"}

        temp_dir = self._hubs_cache_dir / f".install_{skill_name}"
        if temp_dir.exists():
            shutil.rmtree(str(temp_dir))
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            if source.startswith("/") or source.startswith("./") or source.startswith("~"):
                local = Path(source).expanduser().resolve()
                if not local.exists():
                    return {"success": False, "error": f"Local path not found: {source}"}
                shutil.copytree(str(local), str(temp_dir), dirs_exist_ok=True)
            elif "github.com" in source:
                clone_url = source.rstrip("/")
                if not clone_url.endswith(".git"):
                    clone_url += ".git"
                proc = subprocess.run(
                    ["git", "clone", "--depth=1", clone_url, str(temp_dir)],
                    capture_output=True,
                    timeout=120,
                )
                if proc.returncode != 0:
                    stderr = proc.stderr.decode("utf-8", errors="replace")[:300]
                    return {"success": False, "error": f"Git clone failed: {stderr}"}
            else:
                # Raw file or archive URL
                import urllib.request

                try:
                    urllib.request.urlretrieve(source, temp_dir / "skill.zip")
                    shutil.unpack_archive(str(temp_dir / "skill.zip"), str(temp_dir))
                except Exception:
                    return {
                        "success": False,
                        "error": f"Unsupported source or download failed: {source}",
                    }

            # Validate: must have module.yaml or SKILL.md
            has_manifest = (temp_dir / "module.yaml").exists() or (temp_dir / "SKILL.md").exists()
            if not has_manifest:
                shutil.rmtree(str(temp_dir))
                return {
                    "success": False,
                    "error": "Source does not contain a valid skill (no module.yaml or SKILL.md)",
                }

            # Security scan
            scanner = SkillSecurityScanner()
            scan_result = scanner.scan(temp_dir)

            if trust_level == "block" and not scan_result["safe"]:
                shutil.rmtree(str(temp_dir))
                return {
                    "success": False,
                    "error": "Skill blocked by security scan",
                    "scan": scan_result,
                }

            # Move to installed directory
            shutil.copytree(str(temp_dir), str(target_dir), dirs_exist_ok=True)
            shutil.rmtree(str(temp_dir))

            meta = self._read_skill_meta(target_dir)
            result: dict[str, Any] = {
                "success": True,
                "name": skill_name,
                "path": str(target_dir),
                "scan": scan_result,
            }
            if meta:
                result["meta"] = meta
            if not scan_result["safe"]:
                result["warning"] = "Skill installed with security warnings"
                result["warnings"] = scan_result["warnings"]

            logger.info("Installed skill '%s' from %s", skill_name, source)
            return result

        except Exception as e:
            if temp_dir.exists():
                shutil.rmtree(str(temp_dir))
            return {"success": False, "error": f"Installation failed: {e}"}

    def remove(self, skill_name: str) -> dict[str, Any]:
        """Remove an installed skill."""
        target = self._installed_dir / skill_name
        if not target.exists():
            return {
                "success": False,
                "error": f"Skill '{skill_name}' not found in installed directory",
            }
        shutil.rmtree(str(target))
        return {"success": True, "message": f"Removed skill '{skill_name}'"}

    # ── Publishing ─────────────────────────────────────────────────

    def publish(
        self,
        skill_dir: str,
        description: str = "",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Publish a skill to the community directory."""
        source = Path(skill_dir)
        if not source.exists():
            return {"success": False, "error": f"Skill directory not found: {skill_dir}"}

        name = source.name
        target = self._community_dir / name

        manifest_path = source / "module.yaml"
        if not manifest_path.exists():
            manifest = {
                "schema_version": "1.0",
                "module_id": f"skill.community.{name}",
                "display_name": name.replace("_", " ").title(),
                "version": "1.0.0",
                "category": "skill",
                "description": description or f"Community skill: {name}",
                "tags": tags or [],
                "origin": "community",
                "published_at": datetime.now(timezone.utc).isoformat(),
            }
            manifest_path.write_text(
                yaml.dump(manifest, default_flow_style=False, allow_unicode=True),
                encoding="utf-8",
            )

        shutil.copytree(str(source), str(target), dirs_exist_ok=True)
        return {"success": True, "name": name, "path": str(target)}

    # ── Remote Hub Discovery ───────────────────────────────────────

    def list_hubs(self) -> list[dict[str, Any]]:
        """List available remote skill hub sources."""
        return [
            {
                "name": h["name"],
                "description": h["description"],
                "type": h["type"],
            }
            for h in WELL_KNOWN_HUBS
        ]

    def browse_hub(self, hub_name: str, query: str = "") -> list[dict[str, Any]]:
        """Browse skills from a remote hub by name."""
        hub = next((h for h in WELL_KNOWN_HUBS if h["name"] == hub_name), None)
        if not hub:
            return []

        if hub["type"] == "api":
            return self._fetch_hub_api(hub["url"], query)
        elif hub["type"] == "github-tap":
            return self._fetch_github_taps(hub["taps"], query)
        return []

    def _search_remote(self, query: str) -> list[dict[str, Any]]:
        """Search across all remote hubs."""
        results: list[dict[str, Any]] = []
        for hub in WELL_KNOWN_HUBS:
            try:
                results.extend(self.browse_hub(hub["name"], query))
            except Exception as e:
                logger.debug("Hub '%s' search failed: %s", hub["name"], e)
        return results

    def _fetch_hub_api(self, url: str, query: str) -> list[dict[str, Any]]:
        import urllib.parse
        import urllib.request

        try:
            fetch_url = f"{url}?q={urllib.parse.quote(query)}" if query else url
            with urllib.request.urlopen(fetch_url, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            skills_list = (
                data if isinstance(data, list) else data.get("skills", data.get("data", []))
            )
            return [
                {
                    "name": s.get("name", s.get("id", "unknown")),
                    "description": s.get("description", ""),
                    "tags": s.get("tags", []),
                    "source": f"hub:{url}",
                    "remote": True,
                }
                for s in skills_list[:20]
            ]
        except Exception as e:
            logger.debug("Hub API fetch failed for %s: %s", url, e)
            return []

    def _fetch_github_taps(self, taps: list[str], query: str) -> list[dict[str, Any]]:
        import urllib.request

        results: list[dict[str, Any]] = []
        for tap_url in taps:
            try:
                if "topics" in tap_url:
                    api_url = tap_url.replace(
                        "github.com/topics/", "api.github.com/search/repositories?q=topic:"
                    )
                    with urllib.request.urlopen(api_url, timeout=10) as resp:
                        data = json.loads(resp.read().decode())
                    for repo in data.get("items", [])[:10]:
                        desc = repo.get("description", "") or ""
                        if not query or query in (repo.get("name", "") + desc).lower():
                            results.append(
                                {
                                    "name": repo.get("name", "unknown"),
                                    "description": desc[:200],
                                    "tags": repo.get("topics", []),
                                    "source": repo.get("clone_url", repo.get("html_url", "")),
                                    "remote": True,
                                }
                            )
            except Exception as e:
                logger.debug("GitHub tap fetch failed for %s: %s", tap_url, e)
        return results

    # ── Version Management ─────────────────────────────────────────

    def check_updates(self) -> list[dict[str, Any]]:
        """Check if installed skills have updates available."""
        updates: list[dict[str, Any]] = []
        for skill_dir in self._installed_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            meta = self._read_skill_meta(skill_dir)
            if not meta:
                continue
            version = meta.get("version", "0.0.0")
            remote_version = self._check_remote_version(skill_dir.name, version)
            if remote_version and remote_version != version:
                updates.append(
                    {
                        "name": skill_dir.name,
                        "current_version": version,
                        "available_version": remote_version,
                    }
                )
        return updates

    def _check_remote_version(self, skill_name: str, current: str) -> str | None:
        return None

    # ── Helpers ────────────────────────────────────────────────────

    def _read_skill_meta(self, skill_dir: Path) -> dict[str, Any] | None:
        manifest = skill_dir / "module.yaml"
        meta: dict[str, Any] = {"name": skill_dir.name}
        if manifest.exists():
            try:
                data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
                meta["name"] = data.get("display_name", data.get("name", skill_dir.name))
                meta["module_id"] = data.get("module_id", "")
                meta["version"] = data.get("version", "0.1.0")
                meta["description"] = data.get("description", "")
                meta["tags"] = data.get("tags", [])
                meta["category"] = data.get("category", "skill")
                meta["stability"] = data.get("stability", "unknown")
                meta["trust_level"] = data.get("trust_level", "workspace")
                meta["origin"] = data.get("origin", "")
                return meta
            except Exception:
                pass

        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            meta["description"] = skill_md.read_text(encoding="utf-8")[:200]
            return meta
        return None

    @staticmethod
    def _matches_query(meta: dict, query: str) -> bool:
        searchable = " ".join(
            str(v)
            for v in [
                meta.get("name", ""),
                meta.get("description", ""),
                " ".join(meta.get("tags", [])),
            ]
        ).lower()
        return query in searchable


# Singleton
_marketplace: SkillMarketplace | None = None


def get_skill_marketplace() -> SkillMarketplace:
    global _marketplace
    if _marketplace is None:
        _marketplace = SkillMarketplace()
    return _marketplace
