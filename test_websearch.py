import unittest

from app.tools.websearch import WebSearchTool


class _Part:
    def __init__(self, text: str):
        self.text = text


class _Content:
    def __init__(self, parts):
        self.parts = parts


class _Candidate:
    def __init__(self, content, grounding_metadata=None):
        self.content = content
        self.grounding_metadata = grounding_metadata


class _Response:
    def __init__(self, candidates):
        self.candidates = candidates


class _ModelStub:
    def __init__(self, response):
        self._response = response

    def generate_content(self, contents=None, tools=None):
        return self._response


class TestWebSearchTool(unittest.IsolatedAsyncioTestCase):
    async def test_missing_query(self):
        tool = WebSearchTool(model=_ModelStub(None))
        result = await tool.execute()
        self.assertIn("Error:", result.get("llmContent", ""))
        self.assertIn("query", result.get("returnDisplay", {}).get("error", ""))

    async def test_execute_without_grounding_metadata(self):
        response = _Response(
            candidates=[_Candidate(_Content([_Part("simple answer")]), None)]
        )
        tool = WebSearchTool(model=_ModelStub(response))
        result = await tool.execute(query="latest update")
        self.assertEqual(result.get("llmContent"), "simple answer")
        self.assertIn("results", result.get("returnDisplay", {}))

    async def test_execute_no_parts(self):
        response = _Response(candidates=[_Candidate(_Content([]), None)])
        tool = WebSearchTool(model=_ModelStub(response))
        result = await tool.execute(query="nothing")
        self.assertIn("No search results", result.get("llmContent", ""))


if __name__ == "__main__":
    unittest.main()
