import unittest

from app.providers.killo_provider import KilloProviderClient


class _MockKilloProvider(KilloProviderClient):
    async def _request(self, method, path, payload=None):
        if method == "GET" and path == "/models":
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "data": [
                        {
                            "id": "qwen/qwen3-coder:free",
                            "pricing": {"prompt": "0", "completion": "0"},
                        },
                        {
                            "id": "giga-potato",
                            "pricing": {"prompt": "0", "completion": "0"},
                        },
                        {
                            "id": "paid/model",
                            "pricing": {"prompt": "0.0001", "completion": "0.0002"},
                        },
                    ]
                },
            }
        if method == "POST" and path == "/chat/completions":
            if (payload or {}).get("model") == "qwen/qwen3-coder:free":
                return {
                    "success": False,
                    "status_code": 429,
                    "error": {
                        "message": "Provider returned error",
                        "code": 429,
                        "metadata": {
                            "raw": "qwen/qwen3-coder:free is temporarily rate-limited upstream."
                        },
                    },
                }
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "choices": [{"message": {"content": "OK"}}],
                    "model": "qwen/qwen3-coder:free",
                },
            }
        return {"success": False, "status_code": 404, "error": {"message": "not found"}}


class TestKilloProvider(unittest.IsolatedAsyncioTestCase):
    async def test_list_free_models(self):
        client = _MockKilloProvider(api_key="test")
        res = await client.list_free_models()
        self.assertTrue(res.get("success"))
        ids = res.get("free_model_ids", [])
        self.assertIn("qwen/qwen3-coder:free", ids)
        self.assertIn("giga-potato", ids)
        self.assertNotIn("paid/model", ids)

    async def test_chat_completion_with_free_guard(self):
        client = _MockKilloProvider(api_key="test")
        res = await client.chat_completion(
            model="giga-potato",
            messages=[{"role": "user", "content": "Reply with OK"}],
            free_only_guard=True,
        )
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("content"), "OK")

    async def test_free_guard_rejects_paid_model(self):
        client = _MockKilloProvider(api_key="test")
        res = await client.chat_completion(
            model="paid/model",
            messages=[{"role": "user", "content": "hi"}],
            free_only_guard=True,
        )
        self.assertFalse(res.get("success"))
        self.assertIn("not free", res.get("error", ""))

    async def test_resilient_completion_fallbacks_after_429(self):
        client = _MockKilloProvider(api_key="test")
        res = await client.chat_completion_resilient(
            messages=[{"role": "user", "content": "hello"}],
            preferred_models=["qwen/qwen3-coder:free", "giga-potato"],
            free_only_guard=True,
            max_retries_per_model=1,
            initial_backoff_seconds=0.01,
        )
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("model_used"), "giga-potato")
        self.assertEqual(res.get("content"), "OK")


if __name__ == "__main__":
    unittest.main()
