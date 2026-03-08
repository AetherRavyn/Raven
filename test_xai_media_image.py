import unittest

from app.media.image.xai import understand_image


class _StubXAIClient:
    def __init__(self):
        self.calls = []

    def chat_completion_with_image(self, **kwargs):
        self.calls.append(kwargs)
        return {"success": True, "content": "image analysis ok", "raw": {}}


class TestXaiMediaImage(unittest.TestCase):
    def test_understand_image_success(self):
        stub = _StubXAIClient()
        res = understand_image(
            image_url="https://example.com/image.jpg",
            prompt="what is this?",
            model="grok-2-vision-latest",
            image_detail="low",
            client=stub,
        )
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("output"), "image analysis ok")
        self.assertEqual(len(stub.calls), 1)
        self.assertEqual(stub.calls[0]["image_detail"], "low")

    def test_understand_image_invalid_url(self):
        res = understand_image(image_url="ftp://example.com/a.jpg")
        self.assertFalse(res.get("success"))
        self.assertIn("HTTP/HTTPS", res.get("error", ""))


if __name__ == "__main__":
    unittest.main()
