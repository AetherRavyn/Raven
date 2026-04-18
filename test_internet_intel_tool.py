import unittest

from app.tools.internetinteltool import InternetIntelTool


class TestInternetIntelTool(unittest.IsolatedAsyncioTestCase):
    async def test_status_operation(self):
        tool = InternetIntelTool()
        tool._reach.status = lambda: {"success": True, "channels": {}, "report": "ok"}
        result = await tool.execute(operation="status")
        self.assertTrue(result["success"])
        self.assertIn("channels", result)

    async def test_report_operation(self):
        tool = InternetIntelTool()
        tool._reach.coverage_report = lambda: "ok"
        result = await tool.execute(operation="report")
        self.assertTrue(result["success"])
        self.assertIn("report", result)

    async def test_read_requires_url(self):
        tool = InternetIntelTool()
        result = await tool.execute(operation="read")
        self.assertFalse(result["success"])
        self.assertIn("url", result["error"])

    async def test_search_requires_query(self):
        tool = InternetIntelTool()
        result = await tool.execute(operation="search")
        self.assertFalse(result["success"])
        self.assertIn("query", result["error"])


if __name__ == "__main__":
    unittest.main()
