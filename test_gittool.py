import unittest

from app.tools.gittool import GitOperationTool


class TestGitOperationTool(unittest.IsolatedAsyncioTestCase):
    async def test_all_gittool_operations(self) -> None:
        tool = GitOperationTool(repo_path=".")

        branch = await tool.execute(operation="branch")
        self.assertTrue(branch.get("success"))
        self.assertIn("branch", branch)

        status = await tool.execute(operation="status")
        self.assertTrue(status.get("success"))
        self.assertIn("status", status)

        log = await tool.execute(operation="log", max_count=3)
        self.assertTrue(log.get("success"))
        self.assertIn("commits", log)

        last_commit = await tool.execute(operation="last_commit")
        self.assertTrue(last_commit.get("success"))
        self.assertIn("last_commit", last_commit)

        remotes = await tool.execute(operation="remotes")
        self.assertTrue(remotes.get("success"))
        self.assertIn("remotes", remotes)

        diff_stat = await tool.execute(operation="diff_stat")
        self.assertTrue(diff_stat.get("success"))
        self.assertIn("diff_stat", diff_stat)

    async def test_unknown_operation_returns_error(self) -> None:
        tool = GitOperationTool(repo_path=".")
        result = await tool.execute(operation="not_real")
        self.assertFalse(result.get("success"))
        self.assertIn("Unknown operation", result.get("error", ""))


if __name__ == "__main__":
    unittest.main()
