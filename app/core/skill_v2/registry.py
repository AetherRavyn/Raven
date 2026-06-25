"""Skill registry v2 — CRUD + quarantine.

The registry is a stateful layer on top of :class:`SkillLayoutRoot`.
It owns the *enabled* set and the *quarantine* set.  Skills in
quarantine are visible to the operator (and the dashboard) but
the orchestrator refuses to auto-invoke them.

Operations:

  * ``list()``         — every known skill, regardless of state.
  * ``list_enabled()`` — only the skills the orchestrator may use.
  * ``enable(name)``   — flip a skill to enabled.
  * ``disable(name)``  — flip a skill to disabled.
  * ``quarantine(name, reason)`` — disable + record why.
  * ``clear_quarantine(name)``   — re-enable.
  * ``record_eval(name, record)`` — append an EvalRecord and
      re-evaluate the promotion gate.  The eval failure path
      auto-quarantines the skill.

State is stored in a tiny JSON file at ``<root>/registry.json`` so
the registry survives a process restart.  Tests pass an in-memory
state object.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from app.core.skill_v2.layout import SkillLayout, SkillLayoutRoot
from app.core.skill_v2.manifest import (
    EvalRecord,
    ManifestSource,
    ManifestTrust,
    SkillManifest,
    validate_manifest,
)
from app.core.skill_v2.signing import TrustStore

logger = logging.getLogger(__name__)


@dataclass
class RegistryState:
    """Persisted state of the registry."""

    enabled: set[str] = field(default_factory=set)  # skill names
    disabled: set[str] = field(default_factory=set)
    quarantined: dict[str, str] = field(default_factory=dict)  # name → reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": sorted(self.enabled),
            "disabled": sorted(self.disabled),
            "quarantined": dict(self.quarantined),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RegistryState":
        return cls(
            enabled=set(d.get("enabled", [])),
            disabled=set(d.get("disabled", [])),
            quarantined=dict(d.get("quarantined", {})),
        )


class SkillRegistryV2:
    """CRUD over the skill directory root, with enabled/disabled state."""

    def __init__(
        self,
        layout_root: SkillLayoutRoot,
        state: RegistryState | None = None,
        state_path: str | Path | None = None,
        trust: TrustStore | None = None,
        *,
        strict_signing: bool = False,
    ) -> None:
        self.layout_root = layout_root
        self.state = state or RegistryState()
        self._state_path: Optional[Path] = (
            Path(state_path) if state_path else None
        )
        self.trust = trust or TrustStore()
        self.strict_signing = strict_signing
        if self._state_path is not None and self._state_path.is_file():
            try:
                self.state = RegistryState.from_dict(
                    json.loads(self._state_path.read_text())
                )
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("registry state load failed: %s", e)

    # ── persistence ─────────────────────────────────────────────

    def save(self) -> None:
        if self._state_path is None:
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(self.state.to_dict(), indent=2))

    # ── discovery ───────────────────────────────────────────────

    def list(self) -> list[SkillLayout]:
        """Every skill the registry can see."""
        return self.layout_root.list()

    def list_enabled(self) -> list[SkillLayout]:
        return [
            l for l in self.list() if l.name in self.state.enabled
        ]

    def list_quarantined(self) -> list[tuple[SkillLayout, str]]:
        out: list[tuple[SkillLayout, str]] = []
        for l in self.list():
            reason = self.state.quarantined.get(l.name)
            if reason:
                out.append((l, reason))
        return out

    def get(self, name: str) -> Optional[SkillLayout]:
        return self.layout_root.find(name)

    def is_enabled(self, name: str) -> bool:
        return name in self.state.enabled

    def is_quarantined(self, name: str) -> bool:
        return name in self.state.quarantined

    # ── state mutations ─────────────────────────────────────────

    def enable(self, name: str) -> bool:
        layout = self.layout_root.find(name)
        if layout is None:
            return False
        self.state.enabled.add(name)
        self.state.disabled.discard(name)
        self.state.quarantined.pop(name, None)
        self.save()
        return True

    def disable(self, name: str) -> bool:
        layout = self.layout_root.find(name)
        if layout is None:
            return False
        self.state.disabled.add(name)
        self.state.enabled.discard(name)
        self.save()
        return True

    def quarantine(self, name: str, reason: str) -> bool:
        layout = self.layout_root.find(name)
        if layout is None:
            return False
        self.state.quarantined[name] = reason
        self.state.enabled.discard(name)
        self.state.disabled.add(name)
        self.save()
        return True

    def clear_quarantine(self, name: str) -> bool:
        if name not in self.state.quarantined:
            return False
        self.state.quarantined.pop(name)
        self.state.disabled.discard(name)
        # Don't auto-enable — operator decides.
        self.save()
        return True

    # ── validation + verification ───────────────────────────────

    def validate(self, name: str) -> list[str]:
        """Return validation errors for the named skill (empty = OK)."""
        layout = self.layout_root.find(name)
        if layout is None:
            return [f"skill not found: {name!r}"]
        m = layout.read_manifest()
        if m is None:
            return [f"no manifest at {layout.manifest_path}"]
        errs = list(validate_manifest(m, strict_signing=self.strict_signing))
        if self.strict_signing:
            sig = layout.read_signature()
            if not sig:
                errs.append("missing signature in strict_signing mode")
            else:
                # Verification needs a trusted key — operator must add
                # the author's pubkey to the trust store first.
                if not self.trust.authors():
                    errs.append("trust store empty in strict_signing mode")
        return errs

    # ── eval + promotion ────────────────────────────────────────

    def record_eval(
        self, name: str, record: EvalRecord
    ) -> dict[str, Any]:
        """Append an eval record and re-evaluate the promotion gate.

        Returns a small report dict:
          { "passed_total": int, "promoted": bool, "quarantined": bool }

        A eval with ``passed=False`` triggers automatic quarantine
        (the skill can be inspected but won't be auto-invoked).
        """
        layout = self.layout_root.find(name)
        if layout is None:
            return {"error": "not_found"}
        m = layout.read_manifest()
        if m is None:
            return {"error": "no_manifest"}
        m.eval_records.append(record)
        # Persist append-only.
        layout.write_manifest(m)
        layout.append_eval_record(record.to_dict())
        promoted = m.is_promoted()
        report = {
            "passed_total": m.success_count(),
            "promoted": promoted,
            "quarantined": False,
        }
        if not record.passed:
            self.quarantine(name, f"eval_failure: {record.note or record.invocation_id}")
            report["quarantined"] = True
        elif promoted and not self.is_enabled(name):
            # Auto-enable on promotion.  Caller can disable again.
            self.enable(name)
        return report

    # ── community browsing (read-only) ──────────────────────────

    def community_browse(self) -> list[SkillLayout]:
        """List community skills without enabling them."""
        return self.layout_root.list(scope="community")


__all__ = [
    "RegistryState",
    "SkillRegistryV2",
]