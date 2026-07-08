from __future__ import annotations

from typing import Any

from app.core.hooks import EventHookManager


class HookEmitter:
    """Mixin for core modules to emit hook events.

    Usage::

        class MyModule(HookEmitter):
            async def do_thing(self) -> None:
                await self.emit_hook("task_completed", {"task_id": "123"})

    Call ``HookEmitter.set_hook_manager(manager)`` once at startup
    to wire up the shared ``EventHookManager`` instance.
    """

    _manager: EventHookManager | None = None

    @classmethod
    def set_hook_manager(cls, manager: EventHookManager) -> None:
        cls._manager = manager

    async def emit_hook(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._manager is not None:
            self._manager.trigger(event_type, payload)
