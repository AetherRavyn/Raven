import unittest

from app.provider import (
    AnthropicProviderClient,
    GoogleProviderClient,
    OpenAIProviderClient,
    create_provider,
)
from app.provider.xai import XAIGrpcClient
from app.providers.killo_provider import KilloProviderClient


class TestProviderFactory(unittest.TestCase):
    def test_openai_factory(self):
        p = create_provider("openai", api_key="x")
        self.assertIsInstance(p, OpenAIProviderClient)

    def test_anthropic_factory(self):
        p = create_provider("anthropic", api_key="x")
        self.assertIsInstance(p, AnthropicProviderClient)

    def test_google_factory(self):
        p = create_provider("google", api_key="x")
        self.assertIsInstance(p, GoogleProviderClient)

    def test_killo_factory(self):
        p = create_provider("killo", api_key="x")
        self.assertIsInstance(p, KilloProviderClient)

    def test_xai_factory(self):
        # Inject proto+stub to avoid grpc import requirements in this test.
        class _FakeProto:
            ROLE_USER = 1
            ROLE_ASSISTANT = 2
            ROLE_SYSTEM = 3
            ROLE_TOOL = 5
            ROLE_DEVELOPER = 6
            DETAIL_AUTO = 1

            class Content:
                def __init__(self, text="", image_url=None):
                    self.text = text
                    self.image_url = image_url

            class ImageUrlContent:
                def __init__(self, image_url="", detail=1):
                    self.image_url = image_url
                    self.detail = detail

            class Message:
                def __init__(self, role=0, content=None):
                    self.role = role
                    self.content = content or []

            class GetCompletionsRequest:
                def __init__(self, model="", messages=None):
                    self.model = model
                    self.messages = messages or []

        class _FakeStub:
            pass

        p = create_provider("xai", api_key="x", proto=_FakeProto, stub=_FakeStub())
        self.assertIsInstance(p, XAIGrpcClient)

    def test_invalid_provider(self):
        with self.assertRaises(ValueError):
            create_provider("unknown-provider")


if __name__ == "__main__":
    unittest.main()
