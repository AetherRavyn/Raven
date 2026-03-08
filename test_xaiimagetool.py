import unittest

from app.tools.xaiimagetool import XAIImageUnderstandTool


class _StubXAIClient:
    def __init__(self):
        self.calls = []

    def chat_completion_with_image(self, **kwargs):
        self.calls.append(kwargs)
        return {"success": True, "content": "Detected: a cat on a sofa.", "raw": {}}


class TestXAIImageUnderstandTool(unittest.IsolatedAsyncioTestCase):
    async def test_execute_success(self):
        stub = _StubXAIClient()
        tool = XAIImageUnderstandTool(client=stub, default_model="grok-2-vision-latest")
        result = await tool.execute(
            image_url="https://example.com/cat.jpg",
            prompt="Describe this image",
            image_detail="high",
        )
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("model"), "grok-2-vision-latest")
        self.assertIn("cat", result.get("output", ""))
        self.assertEqual(len(stub.calls), 1)
        self.assertEqual(stub.calls[0]["image_detail"], "high")

    async def test_execute_rejects_bad_url(self):
        tool = XAIImageUnderstandTool(client=_StubXAIClient())
        result = await tool.execute(image_url="file:///etc/passwd", prompt="analyze")
        self.assertFalse(result.get("success"))
        self.assertIn("HTTP/HTTPS", result.get("error", ""))


if __name__ == "__main__":
    unittest.main()
