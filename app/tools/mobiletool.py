# app/tools/mobiletool.py
"""Mobile Device Automation Tool — ADB (Android Debug Bridge).

Enables SARAS to control Android phones/tablets like a real user:
  - Tap, swipe, long press on screen
  - Type text into focused fields
  - Press hardware buttons (home, back, volume, power)
  - Take screenshots and read screen content
  - Install/uninstall/launch apps
  - List running apps and processes
  - Send SMS, make calls
  - Manage files (push/pull)
  - Get device info and battery status

Requires: adb installed and device connected (USB or wireless)
  Ubuntu: sudo apt install adb
  Enable USB debugging on device
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import shutil
from typing import Any, Dict

from app.tools.base import BaseTool, ToolCapability, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


def _has_adb() -> bool:
    return shutil.which("adb") is not None


class MobileDeviceTool(BaseTool):
    """Control Android devices via ADB — tap, swipe, type, screenshot, manage apps."""

    group = "automation"

    def get_name(self) -> str:
        return "mobile_device"

    def get_description(self) -> str:
        return (
            "Control Android phones/tablets via ADB. Tap, swipe, type text, press buttons, "
            "take screenshots, launch/install apps, read screen content, manage files, "
            "and interact with any mobile app like a real user."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation", type="string",
                    description="Mobile device action to perform.",
                    required=True,
                    enum=[
                        "list_devices", "device_info", "battery",
                        "screenshot", "screen_xml",
                        "tap", "swipe", "long_press", "pinch",
                        "type_text", "press_key", "press_back", "press_home",
                        "open_app", "close_app", "list_apps", "install_app", "uninstall_app",
                        "list_running", "shell",
                        "push_file", "pull_file",
                        "input_keyevent",
                    ],
                ),
                ToolParameter(
                    name="x", type="integer",
                    description="X coordinate for tap/swipe/long_press.",
                    required=False,
                ),
                ToolParameter(
                    name="y", type="integer",
                    description="Y coordinate for tap/swipe/long_press.",
                    required=False,
                ),
                ToolParameter(
                    name="x2", type="integer",
                    description="End X coordinate for swipe.",
                    required=False,
                ),
                ToolParameter(
                    name="y2", type="integer",
                    description="End Y coordinate for swipe.",
                    required=False,
                ),
                ToolParameter(
                    name="text", type="string",
                    description="Text to type, app package name, key name, shell command, or file path.",
                    required=False,
                ),
                ToolParameter(
                    name="duration", type="integer",
                    description="Duration in ms for swipe/long_press (default 300).",
                    required=False,
                ),
                ToolParameter(
                    name="device_id", type="string",
                    description="Specific device serial (if multiple connected).",
                    required=False,
                ),
                ToolParameter(
                    name="local_path", type="string",
                    description="Local file path for push/pull operations.",
                    required=False,
                ),
                ToolParameter(
                    name="remote_path", type="string",
                    description="Device file path for push/pull operations.",
                    required=False,
                ),
            ],
        )

    def get_capabilities(self) -> ToolCapability:
        return ToolCapability(
            required_permissions=["device:control"],
            risk_level="high",
            cost_tier="low",
            confirmation_policy="ask",
            readonly=False,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        if not _has_adb():
            return {"success": False, "error": "adb not installed. Run: sudo apt install adb"}

        op = kwargs.get("operation", "")
        device_id = kwargs.get("device_id")
        adb = f"adb -s {device_id}" if device_id else "adb"

        try:
            # ── Device Discovery ───────────────────────────────────
            if op == "list_devices":
                out = await self._run(f"{adb} devices -l")
                devices = []
                for line in out.strip().splitlines()[1:]:
                    if line.strip() and "device" in line:
                        parts = line.split()
                        devices.append({
                            "serial": parts[0],
                            "status": parts[1] if len(parts) > 1 else "unknown",
                            "info": " ".join(parts[2:]) if len(parts) > 2 else "",
                        })
                return {"success": True, "devices": devices, "count": len(devices)}

            elif op == "device_info":
                model = await self._run(f"{adb} shell getprop ro.product.model")
                brand = await self._run(f"{adb} shell getprop ro.product.brand")
                android = await self._run(f"{adb} shell getprop ro.build.version.release")
                sdk = await self._run(f"{adb} shell getprop ro.build.version.sdk")
                res = await self._run(f"{adb} shell wm size")
                return {"success": True, "model": model.strip(), "brand": brand.strip(),
                        "android_version": android.strip(), "sdk": sdk.strip(),
                        "resolution": res.strip()}

            elif op == "battery":
                out = await self._run(f"{adb} shell dumpsys battery")
                info = {}
                for line in out.splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        info[k.strip().lower().replace(" ", "_")] = v.strip()
                return {"success": True, "battery": info}

            # ── Screen Capture ─────────────────────────────────────
            elif op == "screenshot":
                os.makedirs("workspace", exist_ok=True)
                path = "workspace/mobile_screenshot.png"
                await self._run(f"{adb} shell screencap -p /sdcard/screen.png")
                await self._run(f"{adb} pull /sdcard/screen.png {path}")
                await self._run(f"{adb} shell rm /sdcard/screen.png")
                if os.path.exists(path):
                    with open(path, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode()
                    return {"success": True, "path": path, "base64_preview": b64[:200] + "..."}
                return {"success": False, "error": "Screenshot failed"}

            elif op == "screen_xml":
                await self._run(f"{adb} shell uiautomator dump /sdcard/ui.xml")
                out = await self._run(f"{adb} shell cat /sdcard/ui.xml")
                await self._run(f"{adb} shell rm /sdcard/ui.xml")
                # Parse key elements
                import re
                elements = []
                for match in re.finditer(r'text="([^"]*)".*?bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', out):
                    text, x1, y1, x2, y2 = match.groups()
                    if text.strip():
                        cx, cy = (int(x1)+int(x2))//2, (int(y1)+int(y2))//2
                        elements.append({"text": text, "center_x": cx, "center_y": cy,
                                        "bounds": f"[{x1},{y1}][{x2},{y2}]"})
                return {"success": True, "elements": elements[:30], "raw_length": len(out)}

            # ── Touch Input ────────────────────────────────────────
            elif op == "tap":
                x, y = kwargs.get("x"), kwargs.get("y")
                if x is None or y is None:
                    return {"success": False, "error": "x and y required for tap"}
                await self._run(f"{adb} shell input tap {x} {y}")
                return {"success": True, "action": "tap", "x": x, "y": y}

            elif op == "swipe":
                x1, y1 = kwargs.get("x", 500), kwargs.get("y", 1500)
                x2, y2 = kwargs.get("x2", 500), kwargs.get("y2", 500)
                dur = kwargs.get("duration", 300)
                await self._run(f"{adb} shell input swipe {x1} {y1} {x2} {y2} {dur}")
                return {"success": True, "action": "swipe", "from": f"{x1},{y1}", "to": f"{x2},{y2}"}

            elif op == "long_press":
                x, y = kwargs.get("x"), kwargs.get("y")
                dur = kwargs.get("duration", 1000)
                if x is None or y is None:
                    return {"success": False, "error": "x and y required"}
                await self._run(f"{adb} shell input swipe {x} {y} {x} {y} {dur}")
                return {"success": True, "action": "long_press", "x": x, "y": y, "duration": dur}

            # ── Text Input ─────────────────────────────────────────
            elif op == "type_text":
                text = kwargs.get("text", "")
                if not text:
                    return {"success": False, "error": "Text required"}
                escaped = text.replace(" ", "%s").replace("'", "\\'")
                await self._run(f"{adb} shell input text '{escaped}'")
                return {"success": True, "action": "type_text", "chars": len(text)}

            elif op == "press_key" or op == "input_keyevent":
                key = kwargs.get("text", "")
                key_map = {
                    "enter": "66", "tab": "61", "delete": "67", "backspace": "67",
                    "space": "62", "escape": "111", "menu": "82",
                    "volume_up": "24", "volume_down": "25",
                    "power": "26", "camera": "27",
                }
                keycode = key_map.get(key.lower(), key)
                await self._run(f"{adb} shell input keyevent {keycode}")
                return {"success": True, "action": "keyevent", "key": keycode}

            elif op == "press_back":
                await self._run(f"{adb} shell input keyevent 4")
                return {"success": True, "action": "press_back"}

            elif op == "press_home":
                await self._run(f"{adb} shell input keyevent 3")
                return {"success": True, "action": "press_home"}

            # ── App Management ─────────────────────────────────────
            elif op == "open_app":
                pkg = kwargs.get("text", "")
                if not pkg:
                    return {"success": False, "error": "Package name required (e.g., com.whatsapp)"}
                await self._run(f"{adb} shell monkey -p {pkg} -c android.intent.category.LAUNCHER 1")
                return {"success": True, "action": "open_app", "package": pkg}

            elif op == "close_app":
                pkg = kwargs.get("text", "")
                if not pkg:
                    return {"success": False, "error": "Package name required"}
                await self._run(f"{adb} shell am force-stop {pkg}")
                return {"success": True, "action": "close_app", "package": pkg}

            elif op == "list_apps":
                out = await self._run(f"{adb} shell pm list packages -3")
                apps = [line.replace("package:", "").strip() for line in out.splitlines() if line.strip()]
                return {"success": True, "apps": sorted(apps), "count": len(apps)}

            elif op == "install_app":
                path = kwargs.get("text", "")
                if not path or not path.endswith(".apk"):
                    return {"success": False, "error": "APK path required"}
                out = await self._run(f"{adb} install {path}")
                return {"success": True, "output": out.strip()}

            elif op == "uninstall_app":
                pkg = kwargs.get("text", "")
                out = await self._run(f"{adb} uninstall {pkg}")
                return {"success": True, "output": out.strip()}

            elif op == "list_running":
                out = await self._run(f"{adb} shell dumpsys activity recents | head -30")
                return {"success": True, "output": out.strip()[:3000]}

            # ── Shell ──────────────────────────────────────────────
            elif op == "shell":
                cmd = kwargs.get("text", "")
                if not cmd:
                    return {"success": False, "error": "Shell command required"}
                out = await self._run(f"{adb} shell {cmd}")
                return {"success": True, "output": out.strip()[:5000]}

            # ── File Transfer ──────────────────────────────────────
            elif op == "push_file":
                local = kwargs.get("local_path", "")
                remote = kwargs.get("remote_path", "/sdcard/")
                out = await self._run(f"{adb} push {local} {remote}")
                return {"success": True, "output": out.strip()}

            elif op == "pull_file":
                remote = kwargs.get("remote_path", "")
                local = kwargs.get("local_path", "workspace/")
                out = await self._run(f"{adb} pull {remote} {local}")
                return {"success": True, "output": out.strip()}

            else:
                return {"success": False, "error": f"Unknown operation: {op}"}

        except Exception as e:
            return {"success": False, "error": str(e)[:500]}

    async def _run(self, cmd: str) -> str:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        out = stdout.decode("utf-8", errors="replace")
        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="replace")
            if err.strip():
                out += "\n[STDERR] " + err
        return out
