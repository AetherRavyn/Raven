from __future__ import annotations

import asyncio
from typing import Any, Dict

try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None

from app.tools.base import BaseTool, ToolParameter, ToolSchema


class BrowserOperationTool(BaseTool):
    """
    Playwright-based headless browser tool. Acts as the user's digital proxy
    to surf the web, scrape JS-rendered pages, and interact with web applications.
    """

    def get_name(self) -> str:
        return "browser_ops"

    def get_description(self) -> str:
        return (
            "Advanced Headless Browser (Playwright). Acts as a digital proxy "
            "to navigate websites, extract rendered text, and read modern JS-heavy applications "
            "that standard HTTP requests cannot reach."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="The browser operation to perform.",
                    required=True,
                    enum=["navigate_and_extract", "take_screenshot"],
                ),
                ToolParameter(
                    name="url",
                    type="string",
                    description="The full URL to navigate to.",
                    required=True,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        if async_playwright is None:
            return {
                "success": False,
                "error": "playwright is not installed. Run: pip install playwright && playwright install",
            }

        operation = kwargs.get("operation")
        url = kwargs.get("url")

        if not url:
            return {"success": False, "error": "URL is required"}

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                    viewport={"width": 1920, "height": 1080},
                )
                page = await context.new_page()

                # Set timeout
                page.set_default_timeout(15000)
                await page.goto(url, wait_until="domcontentloaded")

                if operation == "navigate_and_extract":
                    # Remove unnecessary elements
                    await page.evaluate("""() => {
                        const elements = document.querySelectorAll('script, style, nav, footer, header, iframe, noscript');
                        elements.forEach(el => el.remove());
                    }""")
                    text_content = await page.evaluate("() => document.body.innerText")
                    # Clean up excess whitespace
                    cleaned_text = " ".join(text_content.split())

                    if len(cleaned_text) > 15000:
                        cleaned_text = cleaned_text[:15000] + "...[TRUNCATED]"

                    await browser.close()
                    return {"success": True, "url": url, "content": cleaned_text}

                elif operation == "take_screenshot":
                    # Example capability (would normally save to disk and return path)
                    # For now just return base64 or status
                    screenshot_bytes = await page.screenshot()
                    await browser.close()
                    return {
                        "success": True,
                        "url": url,
                        "status": "Screenshot taken internally (binary omitted for text response)",
                    }

                else:
                    await browser.close()
                    return {"success": False, "error": f"Unknown operation {operation}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
