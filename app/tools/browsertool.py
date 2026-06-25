# app/tools/browsertool.py
"""Full Browser Automation Tool — Playwright-based.

Enables RAVEN to interact with web applications like a real user:
  - Navigate to URLs
  - Click elements by text, selector, or coordinates
  - Fill forms by label or selector  
  - Scroll pages
  - Wait for content to appear
  - Extract text from specific elements
  - Take screenshots
  - Handle multiple tabs
  - Execute JavaScript
  - Manage cookies and storage
  - Download files

Requires: pip install playwright && playwright install chromium
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from typing import Any, Dict

try:
    from playwright.async_api import async_playwright, Page, Browser
    HAS_PLAYWRIGHT = True
except ImportError:
    async_playwright = None
    HAS_PLAYWRIGHT = False

from app.tools.base import BaseTool, ToolCapability, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class BrowserOperationTool(BaseTool):
    """
    Full Playwright browser automation — acts as the user's digital proxy
    for any web interaction: login, form fill, click, scroll, extract, etc.
    """

    group = "automation"

    def __init__(self) -> None:
        self._browser: Any = None
        self._page: Any = None
        self._context: Any = None
        self._pw: Any = None
        self._lock = asyncio.Lock()

    def get_name(self) -> str:
        return "browser_ops"

    def get_description(self) -> str:
        return (
            "Full browser automation via Playwright. Can navigate, click elements, "
            "fill forms, scroll, take screenshots, extract text, run JavaScript, "
            "manage tabs, and interact with any website like a real user."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Browser action to perform.",
                    required=True,
                    enum=[
                        "launch", "navigate", "click", "click_text",
                        "fill", "type_text", "select", "scroll",
                        "screenshot", "extract_text", "extract_element",
                        "wait_for", "run_js", "get_url",
                        "go_back", "go_forward", "reload",
                        "new_tab", "close_tab", "list_tabs",
                        "get_cookies", "set_cookie",
                        "close",
                    ],
                ),
                ToolParameter(
                    name="url", type="string",
                    description="URL to navigate to (for navigate).",
                    required=False,
                ),
                ToolParameter(
                    name="selector", type="string",
                    description="CSS selector or XPath for target element.",
                    required=False,
                ),
                ToolParameter(
                    name="text", type="string",
                    description="Text content: for click_text (text to click), fill/type (text to enter), or run_js (JS code).",
                    required=False,
                ),
                ToolParameter(
                    name="value", type="string",
                    description="Value for select dropdowns or cookie value.",
                    required=False,
                ),
                ToolParameter(
                    name="x", type="integer",
                    description="X coordinate for position-based actions.",
                    required=False,
                ),
                ToolParameter(
                    name="y", type="integer",
                    description="Y coordinate for position-based actions.",
                    required=False,
                ),
                ToolParameter(
                    name="direction", type="string",
                    description="Scroll direction: up, down, left, right.",
                    required=False,
                ),
                ToolParameter(
                    name="amount", type="integer",
                    description="Scroll amount in pixels (default 500).",
                    required=False,
                ),
                ToolParameter(
                    name="timeout_ms", type="integer",
                    description="Timeout in milliseconds (default 15000).",
                    required=False,
                ),
                ToolParameter(
                    name="headless", type="boolean",
                    description="Run browser in headless mode (default true).",
                    required=False,
                ),
            ],
        )

    def get_capabilities(self) -> ToolCapability:
        return ToolCapability(
            required_permissions=["browser:control"],
            risk_level="medium",
            cost_tier="low",
            confirmation_policy="ask",
            readonly=False,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        if not HAS_PLAYWRIGHT:
            return {"success": False, "error": "playwright not installed. Run: pip install playwright && playwright install chromium"}

        op = kwargs.get("operation", "")
        timeout = kwargs.get("timeout_ms", 15000)

        async with self._lock:
            try:
                # ── Launch / Close ─────────────────────────────────────
                if op == "launch":
                    return await self._launch(kwargs.get("headless", True))
                if op == "close":
                    return await self._close()

                # Auto-launch if not running
                if not self._page:
                    await self._launch(kwargs.get("headless", True))

                page = self._page

                # ── Navigation ─────────────────────────────────────────
                if op == "navigate":
                    url = kwargs.get("url", "")
                    if not url:
                        return {"success": False, "error": "URL required"}
                    await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                    return {"success": True, "url": page.url, "title": await page.title()}

                if op == "go_back":
                    await page.go_back(timeout=timeout)
                    return {"success": True, "url": page.url}

                if op == "go_forward":
                    await page.go_forward(timeout=timeout)
                    return {"success": True, "url": page.url}

                if op == "reload":
                    await page.reload(timeout=timeout)
                    return {"success": True, "url": page.url}

                if op == "get_url":
                    return {"success": True, "url": page.url, "title": await page.title()}

                # ── Click ──────────────────────────────────────────────
                if op == "click":
                    selector = kwargs.get("selector")
                    x, y = kwargs.get("x"), kwargs.get("y")
                    if selector:
                        await page.click(selector, timeout=timeout)
                        return {"success": True, "action": "click", "selector": selector}
                    if x is not None and y is not None:
                        await page.mouse.click(int(x), int(y))
                        return {"success": True, "action": "click", "x": x, "y": y}
                    return {"success": False, "error": "Provide selector or x/y coordinates"}

                if op == "click_text":
                    text = kwargs.get("text", "")
                    if not text:
                        return {"success": False, "error": "Text required for click_text"}
                    try:
                        await page.get_by_text(text, exact=False).first.click(timeout=timeout)
                        return {"success": True, "action": "click_text", "text": text}
                    except Exception:
                        pass
                    for strategy in [
                        f"text={text}",
                        f"button:has-text('{text}')",
                        f"a:has-text('{text}')",
                        f"[aria-label='{text}']",
                    ]:
                        try:
                            await page.click(strategy, timeout=5000)
                            return {"success": True, "action": "click_text", "text": text}
                        except Exception:
                            continue
                    return {"success": False, "error": f"Could not find clickable element with text: {text}"}

                # ── Form Interaction ───────────────────────────────────
                if op == "fill":
                    selector = kwargs.get("selector", "")
                    text = kwargs.get("text", "")
                    if not selector:
                        return {"success": False, "error": "Selector required for fill"}
                    await page.fill(selector, text, timeout=timeout)
                    return {"success": True, "action": "fill", "selector": selector}

                if op == "type_text":
                    text = kwargs.get("text", "")
                    selector = kwargs.get("selector")
                    if selector:
                        await page.click(selector, timeout=timeout)
                    await page.keyboard.type(text, delay=50)
                    return {"success": True, "action": "type_text", "chars": len(text)}

                if op == "select":
                    selector = kwargs.get("selector", "")
                    value = kwargs.get("value", "")
                    await page.select_option(selector, value, timeout=timeout)
                    return {"success": True, "action": "select", "selector": selector, "value": value}

                # ── Scroll ─────────────────────────────────────────────
                if op == "scroll":
                    direction = kwargs.get("direction", "down")
                    amount = kwargs.get("amount", 500)
                    dx, dy = 0, 0
                    if direction == "down":
                        dy = amount
                    elif direction == "up":
                        dy = -amount
                    elif direction == "right":
                        dx = amount
                    elif direction == "left":
                        dx = -amount
                    await page.mouse.wheel(dx, dy)
                    return {"success": True, "action": "scroll", "direction": direction, "amount": amount}

                # ── Screenshot ─────────────────────────────────────────
                if op == "screenshot":
                    os.makedirs("workspace", exist_ok=True)
                    path = "workspace/browser_screenshot.png"
                    await page.screenshot(path=path, full_page=False)
                    with open(path, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode()
                    return {"success": True, "path": path, "base64": b64[:200] + "...", "full_base64_available": True}

                # ── Text Extraction ────────────────────────────────────
                if op == "extract_text":
                    selector = kwargs.get("selector")
                    if selector:
                        el = await page.query_selector(selector)
                        if el:
                            text = await el.inner_text()
                        else:
                            return {"success": False, "error": f"Element not found: {selector}"}
                    else:
                        await page.evaluate("""() => {
                            document.querySelectorAll('script, style, nav, footer, iframe, noscript').forEach(e => e.remove());
                        }""")
                        text = await page.evaluate("() => document.body.innerText")
                    text = " ".join(text.split())
                    if len(text) > 15000:
                        text = text[:15000] + "...[TRUNCATED]"
                    return {"success": True, "text": text, "length": len(text)}

                if op == "extract_element":
                    selector = kwargs.get("selector", "")
                    if not selector:
                        return {"success": False, "error": "Selector required"}
                    elements = await page.query_selector_all(selector)
                    results = []
                    for el in elements[:20]:
                        results.append({
                            "text": (await el.inner_text()).strip()[:200],
                            "tag": await el.evaluate("e => e.tagName"),
                            "href": await el.get_attribute("href"),
                        })
                    return {"success": True, "count": len(results), "elements": results}

                # ── Wait ───────────────────────────────────────────────
                if op == "wait_for":
                    selector = kwargs.get("selector")
                    text = kwargs.get("text")
                    if selector:
                        await page.wait_for_selector(selector, timeout=timeout)
                        return {"success": True, "action": "wait_for", "selector": selector}
                    if text:
                        await page.get_by_text(text, exact=False).first.wait_for(timeout=timeout)
                        return {"success": True, "action": "wait_for", "text": text}
                    return {"success": False, "error": "Provide selector or text to wait for"}

                # ── JavaScript ─────────────────────────────────────────
                if op == "run_js":
                    code = kwargs.get("text", "")
                    if not code:
                        return {"success": False, "error": "JS code required in 'text' parameter"}
                    result = await page.evaluate(code)
                    return {"success": True, "result": str(result)[:5000]}

                # ── Tab Management ─────────────────────────────────────
                if op == "new_tab":
                    url = kwargs.get("url", "about:blank")
                    new_page = await self._context.new_page()
                    await new_page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                    self._page = new_page
                    return {"success": True, "url": url, "tabs": len(self._context.pages)}

                if op == "close_tab":
                    pages = self._context.pages
                    if len(pages) > 1:
                        await self._page.close()
                        self._page = self._context.pages[-1]
                        return {"success": True, "tabs": len(self._context.pages)}
                    return {"success": False, "error": "Cannot close last tab"}

                if op == "list_tabs":
                    tabs = []
                    for i, p in enumerate(self._context.pages):
                        tabs.append({"index": i, "url": p.url, "title": await p.title(), "active": p == self._page})
                    return {"success": True, "tabs": tabs}

                # ── Cookies ────────────────────────────────────────────
                if op == "get_cookies":
                    cookies = await self._context.cookies()
                    return {"success": True, "cookies": cookies[:20]}

                if op == "set_cookie":
                    name = kwargs.get("selector", "")
                    value = kwargs.get("value", "")
                    url = kwargs.get("url", page.url)
                    await self._context.add_cookies([{"name": name, "value": value, "url": url}])
                    return {"success": True, "cookie_set": name}

                return {"success": False, "error": f"Unknown operation: {op}"}

            except Exception as e:
                return {"success": False, "error": str(e)[:500]}

    _STORAGE_DIR = "workspace/browser_state"

    async def _launch(self, headless: bool = True) -> Dict[str, Any]:
        if self._browser:
            return {"success": True, "status": "already_running"}
        self._pw = await async_playwright().start()

        # Load persistent storage (cookies, localStorage) if available
        storage_path = os.path.join(self._STORAGE_DIR, "storage_state.json")
        if os.path.exists(storage_path):
            self._context = await self._pw.chromium.launch_persistent_context(
                storage_path.replace("storage_state.json", "user_data"),
                headless=headless,
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
            )
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        else:
            self._browser = await self._pw.chromium.launch(headless=headless)
            self._context = await self._browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
            )
            self._page = await self._context.new_page()
        self._page.set_default_timeout(15000)
        return {"success": True, "status": "launched", "headless": headless, "persistent": os.path.exists(storage_path)}

    async def _close(self) -> Dict[str, Any]:
        # Save session state before closing
        if self._context:
            try:
                os.makedirs(self._STORAGE_DIR, exist_ok=True)
                storage_path = os.path.join(self._STORAGE_DIR, "storage_state.json")
                state = await self._context.storage_state()
                with open(storage_path, "w") as f:
                    json.dump(state, f)
            except Exception:
                pass
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        self._browser = self._page = self._context = self._pw = None
        return {"success": True, "status": "closed"}
