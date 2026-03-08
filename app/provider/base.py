from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class BaseLLMProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def chat_completion(
        self,
        *,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        raise NotImplementedError
