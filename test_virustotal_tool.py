import unittest

from app.tools.virustool import VirusTotalTool


class MockVirusTotalTool(VirusTotalTool):
    async def _request(self, method, path, **kwargs):
        if method == "GET" and path.startswith("/urls/"):
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "data": {
                        "attributes": {
                            "last_analysis_stats": {
                                "malicious": 1,
                                "suspicious": 0,
                                "harmless": 70,
                                "undetected": 5,
                            }
                        }
                    }
                },
            }
        if method == "GET" and path.startswith("/files/"):
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "data": {
                        "attributes": {
                            "last_analysis_stats": {
                                "malicious": 0,
                                "suspicious": 0,
                                "harmless": 75,
                                "undetected": 2,
                            }
                        }
                    }
                },
            }
        if method == "GET" and path.startswith("/domains/"):
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "data": {"attributes": {"last_analysis_stats": {"harmless": 33}}}
                },
            }
        if method == "GET" and path.startswith("/ip_addresses/"):
            return {
                "success": True,
                "status_code": 200,
                "data": {
                    "data": {"attributes": {"last_analysis_stats": {"harmless": 20}}}
                },
            }
        if method == "POST" and path == "/urls":
            return {
                "success": True,
                "status_code": 200,
                "data": {"data": {"id": "analysis-123", "type": "analysis"}},
            }
        if method == "GET" and path == "/analyses/analysis-123":
            return {
                "success": True,
                "status_code": 200,
                "data": {"data": {"attributes": {"status": "completed"}}},
            }
        return {"success": False, "error": f"Unhandled request: {method} {path}"}


class TestVirusTotalTool(unittest.IsolatedAsyncioTestCase):
    async def test_auto_lookup_url(self):
        tool = MockVirusTotalTool(api_key="x")
        result = await tool.execute(
            operation="auto_lookup", indicator="https://example.com/test"
        )
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("operation"), "get_url_report")
        self.assertEqual(result.get("stats", {}).get("malicious"), 1)

    async def test_auto_lookup_hash(self):
        tool = MockVirusTotalTool(api_key="x")
        result = await tool.execute(
            operation="auto_lookup",
            indicator="a" * 64,
        )
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("operation"), "get_file_report")

    async def test_scan_and_wait_url(self):
        tool = MockVirusTotalTool(api_key="x")
        result = await tool.execute(
            operation="scan_and_wait_url",
            url="https://example.com",
            max_polls=2,
            poll_interval_seconds=1,
        )
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("status"), "completed")

    async def test_missing_indicator_error(self):
        tool = MockVirusTotalTool(api_key="x")
        result = await tool.execute(operation="auto_lookup")
        self.assertFalse(result.get("success"))
        self.assertIn("indicator", result.get("error", ""))


if __name__ == "__main__":
    unittest.main()
