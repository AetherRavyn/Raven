from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BlueprintTrigger:
    type: str  # "cron" | "interval" | "event"
    expression: str
    description: str


@dataclass(slots=True)
class BlueprintStep:
    id: str
    tool: str
    params: dict[str, Any] | None = None
    output: str = ""
    depends_on: list[str] | None = None
    condition: str | None = None


@dataclass(slots=True)
class BlueprintCondition:
    if_expr: str
    then_action: str
    else_action: str | None = None


@dataclass(slots=True)
class BlueprintRequirement:
    env_vars: list[str]
    tools: list[str]


@dataclass(slots=True)
class Blueprint:
    name: str
    version: str
    description: str
    author: str = "community"
    tags: list[str] = field(default_factory=list)
    triggers: list[BlueprintTrigger] = field(default_factory=list)
    steps: list[BlueprintStep] = field(default_factory=list)
    conditions: list[BlueprintCondition] | None = None
    requirements: BlueprintRequirement | None = None

    @classmethod
    def from_yaml(cls, path: str | Path) -> Blueprint:
        try:
            import yaml
        except ImportError:
            raise ImportError(
                "PyYAML is required for YAML support. Install it with: pip install pyyaml"
            ) from None

        path_obj = Path(path)
        if not path_obj.exists():
            raise FileNotFoundError(f"Blueprint YAML not found: {path_obj}")

        with open(path_obj, "r") as f:
            data: dict[str, Any] = yaml.safe_load(f)

        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> Blueprint:
        triggers = [
            BlueprintTrigger(**t) for t in data.get("triggers", [])
        ]
        steps = []
        for s in data.get("steps", []):
            step_data = dict(s)
            deps = step_data.pop("depends_on", None)
            step_data["depends_on"] = deps or None
            steps.append(BlueprintStep(**step_data))

        conditions_raw = data.get("conditions")
        conditions: list[BlueprintCondition] | None = None
        if conditions_raw is not None:
            conditions = [BlueprintCondition(**c) for c in conditions_raw]

        requirements_raw = data.get("requirements")
        requirements: BlueprintRequirement | None = None
        if requirements_raw is not None:
            requirements = BlueprintRequirement(**requirements_raw)

        return cls(
            name=data["name"],
            version=data["version"],
            description=data["description"],
            author=data.get("author", "community"),
            tags=data.get("tags", []),
            triggers=triggers,
            steps=steps,
            conditions=conditions,
            requirements=requirements,
        )

    def to_yaml(self, path: str | Path) -> None:
        try:
            import yaml
        except ImportError:
            raise ImportError(
                "PyYAML is required for YAML support. Install it with: pip install pyyaml"
            ) from None

        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)

        data = self._to_dict()
        with open(path_obj, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def _to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "tags": self.tags,
            "triggers": [
                {
                    "type": t.type,
                    "expression": t.expression,
                    "description": t.description,
                }
                for t in self.triggers
            ],
            "steps": [
                {
                    "id": s.id,
                    "tool": s.tool,
                    "params": s.params,
                    "output": s.output,
                    "depends_on": s.depends_on or [],
                    "condition": s.condition,
                }
                for s in self.steps
            ],
        }
        if self.conditions is not None:
            data["conditions"] = [
                {
                    "if_expr": c.if_expr,
                    "then_action": c.then_action,
                    "else_action": c.else_action,
                }
                for c in self.conditions
            ]
        if self.requirements is not None:
            data["requirements"] = {
                "env_vars": self.requirements.env_vars,
                "tools": self.requirements.tools,
            }
        return data
