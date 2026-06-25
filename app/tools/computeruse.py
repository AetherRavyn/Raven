from typing import Any, Dict
import os
import time
import base64
from io import BytesIO

from app.tools.base import BaseTool, ToolSchema, ToolParameter, ToolCapability

# NOTE: To use this tool, you need to install pyautogui and pillow.
# pip install pyautogui pillow

try:
    import pyautogui
    from PIL import Image

    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False


class ComputerUseTool(BaseTool):
    group = "system"

    def __init__(self) -> None:
        self._lock = None

    def get_name(self) -> str:
        return "computeruse"

    def get_description(self) -> str:
        return "Controls the computer using pyautogui. Supports screenshot, click, type, key, and mouse_move."

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="The action to perform: screenshot, click, type, key, mouse_move",
                    required=True,
                    enum=["screenshot", "click", "type", "key", "mouse_move"],
                ),
                ToolParameter(
                    name="x",
                    type="integer",
                    description="X coordinate for click or mouse_move",
                    required=False,
                ),
                ToolParameter(
                    name="y",
                    type="integer",
                    description="Y coordinate for click or mouse_move",
                    required=False,
                ),
                ToolParameter(
                    name="text",
                    type="string",
                    description="Text to type",
                    required=False,
                ),
                ToolParameter(
                    name="key_name",
                    type="string",
                    description="Key to press (e.g., enter, tab, ctrl+c)",
                    required=False,
                ),
            ],
        )

    def get_capabilities(self) -> ToolCapability:
        return ToolCapability(
            required_permissions=["system:control"],
            risk_level="high",
            cost_tier="low",
            confirmation_policy="ask",
            readonly=False,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        if not HAS_PYAUTOGUI:
            return {
                "success": False,
                "error": "pyautogui or pillow not installed. Run: pip install pyautogui pillow"
            }

        action = kwargs.get("action")
        if self._lock is None:
            import asyncio

            self._lock = asyncio.Lock()

        async with self._lock:
            try:
                if action == "screenshot":
                    return await self._screenshot()

                if action == "click":
                    x = kwargs.get("x")
                    y = kwargs.get("y")
                    if x is None or y is None:
                        return {"success": False, "error": "Missing x or y for click"}
                    await self._run_blocking(pyautogui.click, int(x), int(y))
                    return {"success": True, "action": "click", "x": x, "y": y}

                if action == "type":
                    text = kwargs.get("text")
                    if text is None:
                        return {"success": False, "error": "Missing text for type"}
                    await self._run_blocking(pyautogui.write, text, interval=0.05)
                    return {"success": True, "action": "type", "chars": len(text)}

                if action == "key":
                    key_name = kwargs.get("key_name")
                    if key_name is None:
                        return {"success": False, "error": "Missing key_name for key"}
                    if "+" in key_name:
                        keys = key_name.split("+")
                        await self._run_blocking(pyautogui.hotkey, *keys)
                    else:
                        await self._run_blocking(pyautogui.press, key_name)
                    return {"success": True, "action": "key", "key": key_name}

                if action == "mouse_move":
                    x = kwargs.get("x")
                    y = kwargs.get("y")
                    if x is None or y is None:
                        return {
                            "success": False,
                            "error": "Missing x or y for mouse_move",
                        }
                    await self._run_blocking(pyautogui.moveTo, int(x), int(y))
                    return {"success": True, "action": "mouse_move", "x": x, "y": y}

                return {"success": False, "error": f"Unknown action: {action}"}

            except Exception as e:
                return {"success": False, "error": str(e)}

    async def _run_blocking(self, func, *args: Any, **kwargs: Any) -> Any:
        import asyncio

        return await asyncio.to_thread(func, *args, **kwargs)

    async def _screenshot(self) -> Dict[str, Any]:
        import time

        os.makedirs("workspace", exist_ok=True)
        path = os.path.join("workspace", f"screenshot_{int(time.time() * 1000)}.png")
        screenshot = await self._run_blocking(pyautogui.screenshot)
        await self._run_blocking(screenshot.save, path)

        buffered = BytesIO()
        screenshot.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")

        return {"success": True, "path": path, "base64": img_str}
