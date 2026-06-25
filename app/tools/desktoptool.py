# app/tools/desktoptool.py
"""Desktop Application Control Tool.

Enables RAVEN to manage desktop applications and windows like a real user:
  - List open windows and running applications
  - Focus/minimize/maximize/close windows
  - Launch applications by name or command
  - Manage workspaces/virtual desktops
  - Read window titles and properties
  - Resize and move windows
  - Clipboard read/write
  - Lock/unlock screen
  - Control display brightness and volume

Works on Linux (xdotool/wmctrl/xclip), with fallback stubs for other OS.
Requires: sudo apt install xdotool wmctrl xclip xsel
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import subprocess
from typing import Any, Dict, List

from app.tools.base import BaseTool, ToolCapability, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)

IS_LINUX = platform.system() == "Linux"


class DesktopControlTool(BaseTool):
    """Control desktop applications, windows, clipboard, and system UI."""

    group = "automation"

    def get_name(self) -> str:
        return "desktop_control"

    def get_description(self) -> str:
        return (
            "Control desktop apps and windows. List/focus/close/resize windows, "
            "launch apps, read/write clipboard, manage display. "
            "Works like a real user managing their desktop."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation", type="string",
                    description="Desktop action to perform.",
                    required=True,
                    enum=[
                        "list_windows", "focus_window", "close_window",
                        "minimize_window", "maximize_window",
                        "resize_window", "move_window",
                        "launch_app", "list_running",
                        "get_active_window",
                        "clipboard_read", "clipboard_write",
                        "set_volume", "get_volume",
                        "lock_screen", "notification",
                        "search_window",
                    ],
                ),
                ToolParameter(
                    name="window_id", type="string",
                    description="Window ID (from list_windows) for window operations.",
                    required=False,
                ),
                ToolParameter(
                    name="text", type="string",
                    description="App name/command to launch, clipboard text, window search text, or notification message.",
                    required=False,
                ),
                ToolParameter(
                    name="title", type="string",
                    description="Window title to search for (partial match).",
                    required=False,
                ),
                ToolParameter(
                    name="width", type="integer",
                    description="Width for resize (pixels).",
                    required=False,
                ),
                ToolParameter(
                    name="height", type="integer",
                    description="Height for resize (pixels).",
                    required=False,
                ),
                ToolParameter(
                    name="x", type="integer",
                    description="X position for move.",
                    required=False,
                ),
                ToolParameter(
                    name="y", type="integer",
                    description="Y position for move.",
                    required=False,
                ),
                ToolParameter(
                    name="value", type="integer",
                    description="Volume level (0-100) for set_volume.",
                    required=False,
                ),
            ],
        )

    def get_capabilities(self) -> ToolCapability:
        return ToolCapability(
            required_permissions=["desktop:control"],
            risk_level="medium",
            cost_tier="low",
            confirmation_policy="ask",
            readonly=False,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        if not IS_LINUX:
            return {"success": False, "error": f"Desktop control requires Linux. Current OS: {platform.system()}"}

        op = kwargs.get("operation", "")

        try:
            # ── Window Listing ─────────────────────────────────────
            if op == "list_windows":
                return await self._list_windows()

            elif op == "get_active_window":
                return await self._get_active_window()

            elif op == "search_window":
                title = kwargs.get("title") or kwargs.get("text", "")
                return await self._search_window(title)

            # ── Window Control ─────────────────────────────────────
            elif op == "focus_window":
                wid = kwargs.get("window_id") or kwargs.get("text", "")
                if not wid:
                    title = kwargs.get("title", "")
                    if title:
                        result = await self._search_window(title)
                        if result.get("windows"):
                            wid = result["windows"][0]["id"]
                if not wid:
                    return {"success": False, "error": "window_id or title required"}
                await self._run(f"xdotool windowactivate {wid}")
                return {"success": True, "action": "focus", "window_id": wid}

            elif op == "close_window":
                wid = kwargs.get("window_id", "")
                if not wid:
                    return {"success": False, "error": "window_id required"}
                await self._run(f"xdotool windowclose {wid}")
                return {"success": True, "action": "close", "window_id": wid}

            elif op == "minimize_window":
                wid = kwargs.get("window_id", "")
                if not wid:
                    return {"success": False, "error": "window_id required"}
                await self._run(f"xdotool windowminimize {wid}")
                return {"success": True, "action": "minimize", "window_id": wid}

            elif op == "maximize_window":
                wid = kwargs.get("window_id", "")
                if not wid:
                    return {"success": False, "error": "window_id required"}
                if shutil.which("wmctrl"):
                    await self._run(f"wmctrl -ir {wid} -b add,maximized_vert,maximized_horz")
                else:
                    await self._run(f"xdotool windowsize {wid} 100% 100%")
                return {"success": True, "action": "maximize", "window_id": wid}

            elif op == "resize_window":
                wid = kwargs.get("window_id", "")
                w = kwargs.get("width", 800)
                h = kwargs.get("height", 600)
                if not wid:
                    return {"success": False, "error": "window_id required"}
                await self._run(f"xdotool windowsize {wid} {w} {h}")
                return {"success": True, "action": "resize", "window_id": wid, "width": w, "height": h}

            elif op == "move_window":
                wid = kwargs.get("window_id", "")
                x = kwargs.get("x", 0)
                y = kwargs.get("y", 0)
                if not wid:
                    return {"success": False, "error": "window_id required"}
                await self._run(f"xdotool windowmove {wid} {x} {y}")
                return {"success": True, "action": "move", "window_id": wid, "x": x, "y": y}

            # ── App Launcher ───────────────────────────────────────
            elif op == "launch_app":
                app = kwargs.get("text", "")
                if not app:
                    return {"success": False, "error": "App name/command required"}
                # Sanitize to prevent shell injection
                from app.core.command_sanitizer import sanitize_command
                safe_cmd = sanitize_command(f"nohup {app} &>/dev/null &")
                if safe_cmd is None:
                    return {"success": False, "error": "Command blocked by security filter"}
                proc = await asyncio.create_subprocess_shell(
                    safe_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()
                return {"success": True, "action": "launch", "app": app}

            elif op == "list_running":
                out = await self._run("ps aux --sort=-%mem | head -25")
                procs = []
                for line in out.strip().splitlines()[1:]:
                    parts = line.split(None, 10)
                    if len(parts) >= 11:
                        procs.append({
                            "user": parts[0], "pid": parts[1],
                            "cpu": parts[2], "mem": parts[3],
                            "command": parts[10][:80],
                        })
                return {"success": True, "processes": procs, "count": len(procs)}

            # ── Clipboard ──────────────────────────────────────────
            elif op == "clipboard_read":
                if shutil.which("xclip"):
                    out = await self._run("xclip -selection clipboard -o")
                elif shutil.which("xsel"):
                    out = await self._run("xsel --clipboard --output")
                else:
                    return {"success": False, "error": "xclip or xsel required. Run: sudo apt install xclip"}
                return {"success": True, "clipboard": out[:5000]}

            elif op == "clipboard_write":
                text = kwargs.get("text", "")
                if shutil.which("xclip"):
                    proc = await asyncio.create_subprocess_shell(
                        "xclip -selection clipboard",
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                    )
                    await proc.communicate(input=text.encode())
                elif shutil.which("xsel"):
                    proc = await asyncio.create_subprocess_shell(
                        "xsel --clipboard --input",
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                    )
                    await proc.communicate(input=text.encode())
                else:
                    return {"success": False, "error": "xclip or xsel required"}
                return {"success": True, "action": "clipboard_write", "chars": len(text)}

            # ── System Controls ────────────────────────────────────
            elif op == "set_volume":
                val = kwargs.get("value", 50)
                if shutil.which("pactl"):
                    await self._run(f"pactl set-sink-volume @DEFAULT_SINK@ {val}%")
                elif shutil.which("amixer"):
                    await self._run(f"amixer set Master {val}%")
                else:
                    return {"success": False, "error": "pactl or amixer required"}
                return {"success": True, "volume": val}

            elif op == "get_volume":
                if shutil.which("pactl"):
                    out = await self._run("pactl get-sink-volume @DEFAULT_SINK@")
                    return {"success": True, "output": out.strip()[:200]}
                return {"success": False, "error": "pactl required"}

            elif op == "lock_screen":
                for cmd in ["loginctl lock-session", "xdg-screensaver lock", "gnome-screensaver-command -l"]:
                    if shutil.which(cmd.split()[0]):
                        await self._run(cmd)
                        return {"success": True, "action": "lock_screen"}
                return {"success": False, "error": "No screen locker found"}

            elif op == "notification":
                text = kwargs.get("text", "")
                title = kwargs.get("title", "RAVEN")
                if shutil.which("notify-send"):
                    await self._run(f"notify-send '{title}' '{text}'")
                    return {"success": True, "action": "notification", "title": title, "text": text}
                return {"success": False, "error": "notify-send required. Run: sudo apt install libnotify-bin"}

            else:
                return {"success": False, "error": f"Unknown operation: {op}"}

        except Exception as e:
            return {"success": False, "error": str(e)[:500]}

    # ── Helpers ────────────────────────────────────────────────────

    async def _list_windows(self) -> Dict[str, Any]:
        if shutil.which("wmctrl"):
            out = await self._run("wmctrl -l -p")
            windows = []
            for line in out.strip().splitlines():
                parts = line.split(None, 4)
                if len(parts) >= 5:
                    windows.append({"id": parts[0], "desktop": parts[1], "pid": parts[2], "title": parts[4]})
            return {"success": True, "windows": windows, "count": len(windows)}
        elif shutil.which("xdotool"):
            out = await self._run("xdotool search --name ''")
            ids = out.strip().splitlines()[:30]
            windows = []
            for wid in ids:
                try:
                    name = await self._run(f"xdotool getwindowname {wid}")
                    if name.strip():
                        windows.append({"id": wid, "title": name.strip()[:100]})
                except Exception:
                    pass
            return {"success": True, "windows": windows, "count": len(windows)}
        return {"success": False, "error": "wmctrl or xdotool required"}

    async def _get_active_window(self) -> Dict[str, Any]:
        if not shutil.which("xdotool"):
            return {"success": False, "error": "xdotool required"}
        wid = (await self._run("xdotool getactivewindow")).strip()
        name = (await self._run(f"xdotool getwindowname {wid}")).strip()
        return {"success": True, "window_id": wid, "title": name}

    async def _search_window(self, title: str) -> Dict[str, Any]:
        if not title:
            return {"success": False, "error": "Title search text required"}
        if shutil.which("xdotool"):
            out = await self._run(f"xdotool search --name '{title}'")
            ids = out.strip().splitlines()[:10]
            windows = []
            for wid in ids:
                if wid.strip():
                    try:
                        name = (await self._run(f"xdotool getwindowname {wid}")).strip()
                        windows.append({"id": wid, "title": name})
                    except Exception:
                        pass
            return {"success": True, "windows": windows, "count": len(windows)}
        return {"success": False, "error": "xdotool required"}

    async def _run(self, cmd: str) -> str:
        from app.core.command_sanitizer import sanitize_command
        safe_cmd = sanitize_command(cmd, allow_all=True)
        if safe_cmd is None:
            return "Error: Command blocked by security filter"
        proc = await asyncio.create_subprocess_shell(
            safe_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        return stdout.decode("utf-8", errors="replace")
