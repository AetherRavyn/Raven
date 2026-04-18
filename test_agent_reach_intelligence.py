import unittest

from agent_reach.core import AgentReach


class TestAgentReachIntelligence(unittest.TestCase):
    def test_status_is_structured(self):
        reach = AgentReach()
        reach._intel._free_sources = lambda: {"web": "DuckDuckGo HTML + Jina Reader"}
        reach._intel.coverage_report = lambda *_args, **_kwargs: "coverage ok"
        status = reach.status()
        self.assertTrue(status["success"])
        self.assertIn("channels", status)
        self.assertIn("report", status)

    def test_search_rejects_empty_query(self):
        reach = AgentReach()
        result = reach.search("")
        self.assertFalse(result["success"])
        self.assertIn("query", result["error"])

    def test_search_supports_source_selection(self):
        reach = AgentReach()

        def _stub_search(query, limit=8, sources=None):
            return {
                "success": True,
                "sources_used": ["web"],
                "results": [],
                "summary": f"stub {query}",
            }

        reach._intel.search = _stub_search
        result = reach.search("open source ai agents", limit=2, sources="web")
        self.assertTrue(result["success"])
        self.assertIn("sources_used", result)

    def test_read_rejects_empty_url(self):
        reach = AgentReach()
        result = reach.read("")
        self.assertFalse(result["success"])
        self.assertIn("url", result["error"])


if __name__ == "__main__":
    unittest.main()
