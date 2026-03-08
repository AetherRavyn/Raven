import unittest

from app.tools.webfetch import WebFetchTool


class _ModelStub:
    def generate_content(self, prompt):
        class _R:
            text = "mocked model answer"

        return _R()


class TestWebFetchTool(unittest.IsolatedAsyncioTestCase):
    async def test_missing_prompt(self):
        tool = WebFetchTool(model=_ModelStub())
        result = await tool.execute()
        self.assertFalse(result.get("success"))
        self.assertIn("prompt", result.get("output", ""))

    async def test_no_valid_url(self):
        tool = WebFetchTool(model=_ModelStub())
        result = await tool.execute(prompt="check this text without links")
        self.assertFalse(result.get("success"))
        self.assertIn("No valid HTTP/HTTPS URLs", result.get("output", ""))

    async def test_private_ip_block(self):
        tool = WebFetchTool(model=_ModelStub())
        tool._is_private_ip = lambda _url: True
        result = await tool.execute(prompt="scan https://example.com/admin")
        self.assertFalse(result.get("success"))
        self.assertIn("Security Error", result.get("output", ""))

    async def test_success_with_mocked_fetch(self):
        tool = WebFetchTool(model=_ModelStub())
        tool._is_private_ip = lambda _url: False
        tool._fetch_fallback = lambda _url, _prompt: "fetched summary"
        result = await tool.execute(prompt="read https://example.com now")
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("output"), "fetched summary")


if __name__ == "__main__":
    unittest.main()
