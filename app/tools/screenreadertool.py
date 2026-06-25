# app/tools/screenreadertool.py
"""Screen Reader / OCR Tool — read and understand screen content.

Enables RAVEN to "see" what's on any screen (desktop, mobile, browser):
  - Take a screenshot and extract all text via OCR
  - Find specific text or UI elements on screen
  - Read the focused window content
  - Get element positions for targeted clicking
  - Understand screen layout and structure

Uses Tesseract OCR for text extraction.
Requires: sudo apt install tesseract-ocr
Optional: pip install pytesseract pillow
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

from app.tools.base import BaseTool, ToolCapability, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import pytesseract
    HAS_TESSERACT = True
except ImportError:
    HAS_TESSERACT = False


class ScreenReaderTool(BaseTool):
    """Read and understand screen content via OCR — see what's on any screen."""

    group = "automation"

    def get_name(self) -> str:
        return "screen_reader"

    def get_description(self) -> str:
        return (
            "Read and understand screen content. Take screenshots and extract text via OCR, "
            "find specific elements on screen with their positions, read window content, "
            "and understand screen layout. Works with desktop, browser, and mobile screenshots."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation", type="string",
                    description="Screen reading action.",
                    required=True,
                    enum=[
                        "read_screen", "read_window", "read_region",
                        "find_text", "find_element",
                        "read_image", "describe_layout",
                        "ocr_mobile",
                    ],
                ),
                ToolParameter(
                    name="image_path", type="string",
                    description="Path to image to read (for read_image). If omitted, takes a fresh screenshot.",
                    required=False,
                ),
                ToolParameter(
                    name="text", type="string",
                    description="Text to find on screen (for find_text).",
                    required=False,
                ),
                ToolParameter(
                    name="x", type="integer",
                    description="Left X for region capture.",
                    required=False,
                ),
                ToolParameter(
                    name="y", type="integer",
                    description="Top Y for region capture.",
                    required=False,
                ),
                ToolParameter(
                    name="width", type="integer",
                    description="Width for region capture.",
                    required=False,
                ),
                ToolParameter(
                    name="height", type="integer",
                    description="Height for region capture.",
                    required=False,
                ),
                ToolParameter(
                    name="language", type="string",
                    description="OCR language (default 'eng'). Use 'ben' for Bengali, 'hin' for Hindi, etc.",
                    required=False,
                ),
            ],
        )

    def get_capabilities(self) -> ToolCapability:
        return ToolCapability(
            required_permissions=["screen:read"],
            risk_level="low",
            cost_tier="low",
            confirmation_policy="auto",
            readonly=True,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        op = kwargs.get("operation", "")
        lang = kwargs.get("language", "eng")

        try:
            if op == "read_screen":
                return await self._read_screen(lang)

            elif op == "read_window":
                return await self._read_active_window(lang)

            elif op == "read_region":
                x = kwargs.get("x", 0)
                y = kwargs.get("y", 0)
                w = kwargs.get("width", 500)
                h = kwargs.get("height", 500)
                return await self._read_region(x, y, w, h, lang)

            elif op == "find_text":
                text = kwargs.get("text", "")
                if not text:
                    return {"success": False, "error": "Text to find is required"}
                return await self._find_text_on_screen(text, lang)

            elif op == "find_element":
                text = kwargs.get("text", "")
                return await self._find_element(text, lang)

            elif op == "read_image":
                path = kwargs.get("image_path", "")
                if not path or not os.path.exists(path):
                    return {"success": False, "error": f"Image not found: {path}"}
                return await self._ocr_image(path, lang)

            elif op == "describe_layout":
                return await self._describe_layout(lang)

            elif op == "ocr_mobile":
                path = kwargs.get("image_path", "workspace/mobile_screenshot.png")
                if not os.path.exists(path):
                    return {"success": False, "error": f"Mobile screenshot not found: {path}. Take a screenshot first."}
                return await self._ocr_image(path, lang)

            else:
                return {"success": False, "error": f"Unknown operation: {op}"}

        except Exception as e:
            return {"success": False, "error": str(e)[:500]}

    # ── Core OCR ───────────────────────────────────────────────────

    async def _ocr_image(self, path: str, lang: str = "eng") -> Dict[str, Any]:
        """Run OCR on an image file."""
        # Strategy 1: pytesseract (Python library)
        if HAS_TESSERACT and HAS_PIL:
            try:
                img = Image.open(path)
                text = pytesseract.image_to_string(img, lang=lang)
                # Also get bounding box data
                data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
                elements = []
                for i in range(len(data["text"])):
                    word = data["text"][i].strip()
                    if word and int(data["conf"][i]) > 30:
                        elements.append({
                            "text": word,
                            "x": data["left"][i],
                            "y": data["top"][i],
                            "width": data["width"][i],
                            "height": data["height"][i],
                            "confidence": int(data["conf"][i]),
                        })
                return {
                    "success": True,
                    "text": text.strip()[:8000],
                    "elements": elements[:100],
                    "word_count": len(elements),
                    "method": "pytesseract",
                }
            except Exception as e:
                logger.debug("pytesseract failed: %s", e)

        # Strategy 2: CLI tesseract
        if shutil.which("tesseract"):
            out_base = "workspace/ocr_output"
            await self._run_cmd(f"tesseract {path} {out_base} -l {lang}")
            text_path = f"{out_base}.txt"
            if os.path.exists(text_path):
                with open(text_path) as f:
                    text = f.read()
                return {
                    "success": True,
                    "text": text.strip()[:8000],
                    "elements": [],
                    "method": "tesseract-cli",
                }

        return {"success": False, "error": "Tesseract not available. Run: sudo apt install tesseract-ocr && pip install pytesseract pillow"}

    # ── Screen Capture + OCR ───────────────────────────────────────

    async def _take_screenshot(self, path: str = "workspace/screen_reader.png") -> Optional[str]:
        """Take a screenshot of the entire screen."""
        os.makedirs("workspace", exist_ok=True)

        # Try multiple screenshot methods
        for cmd in [
            f"scrot {path}",
            f"gnome-screenshot -f {path}",
            f"import -window root {path}",
            f"xfce4-screenshooter -f -s {path}",
        ]:
            tool = cmd.split()[0]
            if shutil.which(tool):
                await self._run_cmd(cmd)
                if os.path.exists(path):
                    return path

        # Fallback: PyAutoGUI
        try:
            import pyautogui
            screenshot = pyautogui.screenshot()
            screenshot.save(path)
            if os.path.exists(path):
                return path
        except Exception:
            pass

        return None

    async def _read_screen(self, lang: str) -> Dict[str, Any]:
        """Take screenshot and OCR the entire screen."""
        path = await self._take_screenshot()
        if not path:
            return {"success": False, "error": "Could not take screenshot. Install scrot: sudo apt install scrot"}
        result = await self._ocr_image(path, lang)
        result["screenshot_path"] = path
        return result

    async def _read_active_window(self, lang: str) -> Dict[str, Any]:
        """Screenshot and OCR only the active window."""
        path = "workspace/active_window.png"
        os.makedirs("workspace", exist_ok=True)

        if shutil.which("xdotool") and shutil.which("import"):
            wid = (await self._run_cmd("xdotool getactivewindow")).strip()
            await self._run_cmd(f"import -window {wid} {path}")
        elif shutil.which("scrot"):
            await self._run_cmd(f"scrot -u {path}")
        else:
            return {"success": False, "error": "xdotool+import or scrot required"}

        if os.path.exists(path):
            result = await self._ocr_image(path, lang)
            result["screenshot_path"] = path
            return result
        return {"success": False, "error": "Failed to capture active window"}

    async def _read_region(self, x: int, y: int, w: int, h: int, lang: str) -> Dict[str, Any]:
        """OCR a specific region of the screen."""
        full_path = await self._take_screenshot()
        if not full_path:
            return {"success": False, "error": "Screenshot failed"}

        region_path = "workspace/screen_region.png"
        if HAS_PIL:
            img = Image.open(full_path)
            cropped = img.crop((x, y, x + w, y + h))
            cropped.save(region_path)
        else:
            await self._run_cmd(f"convert {full_path} -crop {w}x{h}+{x}+{y} {region_path}")

        if os.path.exists(region_path):
            result = await self._ocr_image(region_path, lang)
            result["region"] = {"x": x, "y": y, "width": w, "height": h}
            return result
        return {"success": False, "error": "Region crop failed"}

    async def _find_text_on_screen(self, search: str, lang: str) -> Dict[str, Any]:
        """Find specific text on screen and return its position."""
        result = await self._read_screen(lang)
        if not result.get("success"):
            return result

        search_lower = search.lower()
        found = []
        for el in result.get("elements", []):
            if search_lower in el["text"].lower():
                found.append({
                    "text": el["text"],
                    "x": el["x"], "y": el["y"],
                    "center_x": el["x"] + el["width"] // 2,
                    "center_y": el["y"] + el["height"] // 2,
                    "confidence": el.get("confidence", 0),
                })

        # Also check if the full text appears in the OCR output
        full_text = result.get("text", "")
        text_found = search_lower in full_text.lower()

        return {
            "success": True,
            "search": search,
            "found": text_found,
            "matches": found,
            "match_count": len(found),
            "suggestion": f"Use computeruse click at ({found[0]['center_x']}, {found[0]['center_y']})" if found else "Text not found on screen",
        }

    async def _find_element(self, text: str, lang: str) -> Dict[str, Any]:
        """Find a UI element by text and return click coordinates."""
        result = await self._find_text_on_screen(text, lang)
        if result.get("matches"):
            best = result["matches"][0]
            return {
                "success": True,
                "element": best,
                "click_x": best["center_x"],
                "click_y": best["center_y"],
                "action_hint": f"Call computeruse with action=click, x={best['center_x']}, y={best['center_y']}",
            }
        return {"success": False, "error": f"Element '{text}' not found on screen"}

    async def _describe_layout(self, lang: str) -> Dict[str, Any]:
        """Describe the overall screen layout."""
        result = await self._read_screen(lang)
        if not result.get("success"):
            return result

        words = result.get("elements", [])
        if not words:
            return {"success": True, "layout": "Screen appears empty or content is non-textual"}

        # Analyze regions
        if HAS_PIL:
            path = result.get("screenshot_path", "")
            if path and os.path.exists(path):
                img = Image.open(path)
                sw, sh = img.size
            else:
                sw, sh = 1920, 1080
        else:
            sw, sh = 1920, 1080

        top = [w for w in words if w["y"] < sh * 0.15]
        middle = [w for w in words if sh * 0.15 <= w["y"] <= sh * 0.85]
        bottom = [w for w in words if w["y"] > sh * 0.85]

        summary = {
            "screen_size": f"{sw}x{sh}",
            "total_elements": len(words),
            "top_region": " ".join(w["text"] for w in top[:15]),
            "main_content_preview": " ".join(w["text"] for w in middle[:30]),
            "bottom_region": " ".join(w["text"] for w in bottom[:10]),
        }

        return {"success": True, "layout": summary}

    # ── Helper ─────────────────────────────────────────────────────

    async def _run_cmd(self, cmd: str) -> str:
        from app.core.command_sanitizer import sanitize_command
        safe_cmd = sanitize_command(cmd, allow_all=True)
        if safe_cmd is None:
            return "Error: Command blocked by security filter"
        proc = await asyncio.create_subprocess_shell(
            safe_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        return stdout.decode("utf-8", errors="replace")
