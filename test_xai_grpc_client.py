import unittest

from app.provider.xai.clinet import XAIGrpcClient


class _FakeContent:
    def __init__(self, text="", image_url=None):
        self.text = text
        self.image_url = image_url


class _FakeImageUrlContent:
    def __init__(self, image_url="", detail=1):
        self.image_url = image_url
        self.detail = detail


class _FakeMessage:
    def __init__(self, role=0, content=None):
        self.role = role
        self.content = content or []


class _FakeRequest:
    def __init__(self, model="", messages=None):
        self.model = model
        self.messages = messages or []
        self.max_tokens = None
        self.temperature = None
        self.top_p = None
        self.user = ""


class _FakeCompletionMessage:
    def __init__(self, content=""):
        self.content = content


class _FakeCompletionOutput:
    def __init__(self, text=""):
        self.message = _FakeCompletionMessage(text)


class _FakeResponse:
    def __init__(self, text):
        self.outputs = [_FakeCompletionOutput(text)]


class _FakeDelta:
    def __init__(self, content):
        self.content = content


class _FakeChunkOut:
    def __init__(self, content):
        self.delta = _FakeDelta(content)


class _FakeChunk:
    def __init__(self, content):
        self.outputs = [_FakeChunkOut(content)]


class _FakeProto:
    ROLE_USER = 1
    ROLE_ASSISTANT = 2
    ROLE_SYSTEM = 3
    ROLE_TOOL = 5
    ROLE_DEVELOPER = 6
    DETAIL_AUTO = 1
    DETAIL_LOW = 2
    DETAIL_HIGH = 3

    Content = _FakeContent
    ImageUrlContent = _FakeImageUrlContent
    Message = _FakeMessage
    GetCompletionsRequest = _FakeRequest


class _FakeStub:
    def __init__(self):
        self.last_call = None

    def GetCompletion(self, request, metadata=None, timeout=None):
        self.last_call = ("GetCompletion", request, metadata, timeout)
        return _FakeResponse("hello from xai")

    def GetCompletionChunk(self, request, metadata=None, timeout=None):
        self.last_call = ("GetCompletionChunk", request, metadata, timeout)
        return [_FakeChunk("he"), _FakeChunk("llo")]


class TestXAIGrpcClient(unittest.TestCase):
    def test_chat_completion(self):
        stub = _FakeStub()
        client = XAIGrpcClient(
            api_key="xai-key",
            host="api.x.ai:443",
            proto=_FakeProto,
            stub=stub,
        )
        res = client.chat_completion(
            model="grok-4-fast-reasoning",
            messages=[{"role": "user", "content": "Say hello"}],
            max_tokens=16,
        )
        self.assertTrue(res.get("success"))
        self.assertIn("hello from xai", res.get("content", ""))
        self.assertEqual(stub.last_call[0], "GetCompletion")
        self.assertIn(("authorization", "Bearer xai-key"), stub.last_call[2])

    def test_chat_completion_stream(self):
        stub = _FakeStub()
        client = XAIGrpcClient(
            api_key="xai-key",
            host="api.x.ai:443",
            proto=_FakeProto,
            stub=stub,
        )
        chunks = list(
            client.chat_completion_stream(
                model="grok-4-fast-reasoning",
                messages=[{"role": "user", "content": "stream"}],
            )
        )
        self.assertEqual(stub.last_call[0], "GetCompletionChunk")
        self.assertEqual("".join(c["delta"] for c in chunks), "hello")

    def test_chat_completion_with_image(self):
        stub = _FakeStub()
        client = XAIGrpcClient(
            api_key="xai-key",
            host="api.x.ai:443",
            proto=_FakeProto,
            stub=stub,
        )
        res = client.chat_completion_with_image(
            model="grok-2-vision-latest",
            prompt="What is in this image?",
            image_url="https://example.com/cat.jpg",
            image_detail="high",
        )
        self.assertTrue(res.get("success"))
        self.assertEqual(stub.last_call[0], "GetCompletion")
        request = stub.last_call[1]
        first_message = request.messages[0]
        self.assertEqual(len(first_message.content), 2)
        self.assertEqual(first_message.content[0].text, "What is in this image?")
        self.assertEqual(
            first_message.content[1].image_url.image_url, "https://example.com/cat.jpg"
        )
        self.assertEqual(
            first_message.content[1].image_url.detail, _FakeProto.DETAIL_HIGH
        )


if __name__ == "__main__":
    unittest.main()
