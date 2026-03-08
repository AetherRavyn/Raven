import unittest

from app.provider.anthropic import AnthropicProviderClient
from app.provider.google import GoogleProviderClient
from app.provider.openai import OpenAIProviderClient


class TestOpenAIProvider(unittest.IsolatedAsyncioTestCase):
    async def test_chat_completion_success(self):
        def _request_fn(_method, _url, _headers, payload, _timeout):
            self.assertEqual(payload["model"], "gpt-4o-mini")
            self.assertEqual(payload["messages"][0]["content"], "hello")
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "model": "gpt-4o-mini",
                    "choices": [{"message": {"content": "Hi from OpenAI"}}],
                },
            }

        client = OpenAIProviderClient(api_key="x", request_fn=_request_fn)
        result = await client.chat_completion(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "hello"}],
        )
        self.assertTrue(result.get("success"))
        self.assertIn("OpenAI", result.get("content", ""))


class TestAnthropicProvider(unittest.IsolatedAsyncioTestCase):
    async def test_chat_completion_success(self):
        def _request_fn(_method, _url, _headers, payload, _timeout):
            self.assertEqual(payload["model"], "claude-3-5-sonnet-latest")
            self.assertEqual(payload["system"], "system rules")
            self.assertEqual(payload["messages"][0]["role"], "user")
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "model": "claude-3-5-sonnet-latest",
                    "content": [{"type": "text", "text": "Hi from Anthropic"}],
                },
            }

        client = AnthropicProviderClient(api_key="x", request_fn=_request_fn)
        result = await client.chat_completion(
            model="claude-3-5-sonnet-latest",
            messages=[
                {"role": "system", "content": "system rules"},
                {"role": "user", "content": "hello"},
            ],
            max_tokens=256,
        )
        self.assertTrue(result.get("success"))
        self.assertIn("Anthropic", result.get("content", ""))


class TestGoogleProvider(unittest.IsolatedAsyncioTestCase):
    async def test_chat_completion_success(self):
        def _request_fn(_method, _url, _headers, payload, _timeout):
            self.assertEqual(payload["contents"][0]["role"], "user")
            self.assertIn("hello", payload["contents"][0]["parts"][0]["text"])
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "candidates": [
                        {"content": {"parts": [{"text": "Hi from Gemini/Google"}]}}
                    ]
                },
            }

        client = GoogleProviderClient(api_key="x", request_fn=_request_fn)
        result = await client.chat_completion(
            model="gemini-2.5-flash",
            messages=[{"role": "user", "content": "hello"}],
        )
        self.assertTrue(result.get("success"))
        self.assertIn("Gemini", result.get("content", ""))


if __name__ == "__main__":
    unittest.main()
