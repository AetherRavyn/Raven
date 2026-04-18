from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ToolParameter:
    name: str
    type: str
    description: str
    required: bool = False
    enum: List[str] = field(default_factory=list)


@dataclass
class ToolSchema:
    name: str
    description: str
    parameters: List[ToolParameter] = field(default_factory=list)


@dataclass
class ToolCapability:
    required_permissions: List[str] = field(default_factory=list)
    risk_level: str = "low"
    cost_tier: str = "low"
    confirmation_policy: str = "none"
    readonly: bool = True


class BaseTool(ABC):
    @abstractmethod
    def get_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_description(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_schema(self) -> ToolSchema:
        raise NotImplementedError

    def get_capabilities(self) -> ToolCapability:
        return ToolCapability()

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        raise NotImplementedError
