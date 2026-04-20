import unittest

from app.provider.cli_proxy import CLIProxyProvider, _extract_json_response


class TestCLIProxyProvider(unittest.TestCase):
    def test_cli_proxy_builds_opencode_run_command(self):
        provider = CLIProxyProvider(tool_name="opencode", timeout=45)
        cmd, uses_stdin = provider._build_command(
            "opencode", "hello", "opencode/minimax-m2.5-free"
        )

        self.assertFalse(uses_stdin)
        self.assertEqual(
            cmd,
            [
                "opencode",
                "run",
                "hello",
                "--format",
                "json",
                "--model",
                "opencode/minimax-m2.5-free",
            ],
        )

    def test_cli_proxy_builds_kilocode_auto_json_command(self):
        provider = CLIProxyProvider(tool_name="kilocode", timeout=33)
        cmd, uses_stdin = provider._build_command(
            "kilocode", "fix the bug", "qwen/qwen3-coder:free"
        )

        self.assertFalse(uses_stdin)
        self.assertEqual(
            cmd,
            [
                "kilocode",
                "--auto",
                "--json",
                "--mode",
                "ask",
                "--timeout",
                "33",
                "--model",
                "qwen/qwen3-coder:free",
                "fix the bug",
            ],
        )

    def test_extract_json_response_handles_line_delimited_events(self):
        raw = '\n'.join(
            [
                '{"type":"status","text":"thinking"}',
                '{"type":"assistant","text":"OpenCode answer"}',
            ]
        )

        self.assertEqual(_extract_json_response(raw), "OpenCode answer")

    def test_extract_json_response_handles_opencode_event_stream(self):
        raw = '\n'.join(
            [
                '{"type":"step_start","sessionID":"s1","part":{"type":"step-start"}}',
                '{"type":"tool_use","sessionID":"s1","part":{"type":"tool","tool":"websearch"}}',
                '{"type":"text","sessionID":"s1","part":{"type":"text","text":"Formatted answer"}}',
                '{"type":"step_finish","sessionID":"s1","part":{"type":"step-finish"}}',
            ]
        )

        self.assertEqual(_extract_json_response(raw), "Formatted answer")
if __name__ == "__main__":
    unittest.main()
