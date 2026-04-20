import unittest
from unittest.mock import MagicMock, patch

from app.core.model_router import AutoModelRouter, ModelRouter
from app.settings.config import Config


class TestModelRouter(unittest.TestCase):
    def test_model_router_classification(self):
        mock_provider = MagicMock()
        router = ModelRouter(default_provider=mock_provider, default_model="gpt-4o")

        self.assertEqual(router.classify("Hello there"), "local")
        self.assertEqual(router.classify("What is the time?"), "local")
        self.assertEqual(router.classify("system status"), "local")
        self.assertEqual(router.classify("Explain quantum physics"), "cheap")
        self.assertEqual(router.classify("Summarize the document"), "cheap")
        self.assertEqual(router.classify("How do I make a cake?"), "cheap")
        self.assertEqual(
            router.classify("Write a complex python script with 10 classes"), "deep"
        )
        self.assertEqual(
            router.classify("Refactor the entire codebase to use asyncio"), "deep"
        )

    def test_model_router_route_state(self):
        mock_provider = MagicMock()
        router = ModelRouter(default_provider=mock_provider, default_model="gpt-4o")
        router._local_provider = MagicMock()
        router._local_health = True

        self.assertEqual(router.default_model, "gpt-4o")
        self.assertIs(router.default_provider, mock_provider)

    @patch.object(Config, "LLM_PROVIDER", "opencode")
    @patch.object(Config, "LLM_MODEL", "opencode/big-pickle")
    def test_auto_model_router_prefers_configured_provider(self):
        self.assertEqual(
            AutoModelRouter.get_best_model("agent"),
            ("opencode", "opencode/big-pickle"),
        )

    @patch.object(Config, "LLM_PROVIDER", "auto")
    @patch.object(Config, "LLM_MODEL", "")
    @patch.object(Config, "ANTHROPIC_API_KEY", "")
    @patch.object(Config, "OPENAI_API_KEY", "")
    @patch.object(Config, "GOOGLE_API_KEY", "")
    @patch.object(Config, "GEMINI_API_KEY", "")
    @patch.object(Config, "OPENROUTER_API_KEY", "")
    @patch.object(Config, "NVIDIA_NIM_API_KEY", "")
    @patch.object(Config, "HUGGINGFACE_API_KEY", "")
    @patch.object(Config, "BYTEZ_API_KEY", "")
    @patch.object(AutoModelRouter, "_check_local_endpoint", return_value=False)
    @patch("shutil.which", side_effect=lambda cmd: "/bin/opencode" if cmd == "opencode" else None)
    def test_auto_model_router_prefers_opencode_before_killo(
        self, _mock_which, _mock_check
    ):
        self.assertEqual(
            AutoModelRouter.get_best_model("agent"),
            ("opencode", Config.OPENCODE_MODEL),
        )

        available = AutoModelRouter.get_available_models("agent")
        self.assertEqual(available[0], ("opencode", Config.OPENCODE_MODEL))
        self.assertEqual(available[-1], ("killo", "qwen/qwen3-coder:free"))


if __name__ == "__main__":
    unittest.main()
