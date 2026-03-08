import unittest

from app.core.botsignal import BotSignal
from app.core.models import IncomingRequest, ReplyTarget, SignalPayload
from app.core.orchestrator import MessageOrchestrator


class TestMessageOrchestratorGitTool(unittest.IsolatedAsyncioTestCase):
    async def test_git_message_returns_git_report_on_telegram(self) -> None:
        captured: list[SignalPayload] = []
        botsignal = BotSignal()

        async def sender(_target: ReplyTarget, payload: SignalPayload) -> None:
            captured.append(payload)

        botsignal.register_sender("telegram", sender)
        orchestrator = MessageOrchestrator(botsignal)
        request = IncomingRequest(
            platform="telegram",
            user_id="u123",
            text="git show status and history",
            reply_target=ReplyTarget(platform="telegram", chat_id="42"),
        )
        await orchestrator.handle(request)

        self.assertEqual(len(captured), 1)
        payload = captured[0]
        self.assertIsNone(payload.file_path)
        text = payload.text or ""
        self.assertIn("[source:prompt]", text)
        self.assertIn("[tool:git_ops action:branch status:ok]", text)
        self.assertIn("[tool:git_ops action:status status:ok]", text)
        self.assertIn("[tool:git_ops action:log status:ok]", text)
        self.assertIn("[tool:git_ops action:last_commit status:ok]", text)
        self.assertIn("Git tool operation complete.", text)
        self.assertIn("recent_commits:", text)
        self.assertIn("status:", text)

    async def test_git_message_returns_git_report_on_discord(self) -> None:
        captured: list[SignalPayload] = []
        botsignal = BotSignal()

        async def sender(_target: ReplyTarget, payload: SignalPayload) -> None:
            captured.append(payload)

        botsignal.register_sender("discord", sender)
        orchestrator = MessageOrchestrator(botsignal)
        request = IncomingRequest(
            platform="discord",
            user_id="u999",
            text="/git report",
            reply_target=ReplyTarget(platform="discord", chat_id="10"),
        )
        await orchestrator.handle(request)

        self.assertEqual(len(captured), 1)
        text = captured[0].text or ""
        self.assertIn("[source:command]", text)
        self.assertIn("Git tool operation complete.", text)
        self.assertIn("branch:", text)
        self.assertIn("recent_commits:", text)

    async def test_file_message_runs_filetool_suite_and_sends_file(self) -> None:
        captured: list[SignalPayload] = []
        botsignal = BotSignal()

        async def sender(_target: ReplyTarget, payload: SignalPayload) -> None:
            captured.append(payload)

        botsignal.register_sender("telegram", sender)
        orchestrator = MessageOrchestrator(botsignal)
        request = IncomingRequest(
            platform="telegram",
            user_id="u_file",
            text="file test all functionality",
            reply_target=ReplyTarget(platform="telegram", chat_id="77"),
        )
        await orchestrator.handle(request)

        self.assertEqual(len(captured), 1)
        payload = captured[0]
        self.assertTrue(payload.file_path)
        text = payload.text or ""
        self.assertIn("[source:prompt]", text)
        self.assertIn("[tool:file_operations action:write status:ok]", text)
        self.assertIn("[tool:file_operations action:append status:ok]", text)
        self.assertIn("[tool:file_operations action:read status:ok]", text)
        self.assertIn("[tool:file_operations action:info status:ok]", text)
        self.assertIn("File tool operation complete.", text)

    async def test_non_tool_message_uses_minichat_only(self) -> None:
        captured: list[SignalPayload] = []
        botsignal = BotSignal()

        async def sender(_target: ReplyTarget, payload: SignalPayload) -> None:
            captured.append(payload)

        botsignal.register_sender("discord", sender)
        orchestrator = MessageOrchestrator(botsignal)
        request = IncomingRequest(
            platform="discord",
            user_id="u_plain",
            text="hello",
            reply_target=ReplyTarget(platform="discord", chat_id="900"),
        )
        await orchestrator.handle(request)

        self.assertEqual(len(captured), 1)
        payload = captured[0]
        self.assertIsNone(payload.file_path)
        self.assertIn("[source:prompt]", payload.text or "")
        self.assertNotIn("[tool:file_operations", payload.text or "")
        self.assertNotIn("[tool:git_operations", payload.text or "")

    async def test_virus_message_uses_virustotal_route(self) -> None:
        captured: list[SignalPayload] = []
        botsignal = BotSignal()

        async def sender(_target: ReplyTarget, payload: SignalPayload) -> None:
            captured.append(payload)

        class StubVT:
            def get_name(self):
                return "virustotal_scanner"

            async def execute(self, **kwargs):
                return {
                    "success": True,
                    "operation": "get_url_report",
                    "stats": {
                        "malicious": 1,
                        "suspicious": 0,
                        "harmless": 40,
                        "undetected": 5,
                    },
                }

        botsignal.register_sender("telegram", sender)
        orchestrator = MessageOrchestrator(botsignal)
        orchestrator._vt_tool = StubVT()
        request = IncomingRequest(
            platform="telegram",
            user_id="u_vt",
            text="virus check https://example.com",
            reply_target=ReplyTarget(platform="telegram", chat_id="88"),
        )
        await orchestrator.handle(request)

        self.assertEqual(len(captured), 1)
        payload = captured[0]
        text = payload.text or ""
        self.assertIn("[tool:virustotal_scanner action:auto_lookup status:ok]", text)
        self.assertIn("VirusTotal lookup complete.", text)
        self.assertIn("malicious=1", text)

    async def test_web_search_route(self) -> None:
        captured: list[SignalPayload] = []
        botsignal = BotSignal()

        async def sender(_target: ReplyTarget, payload: SignalPayload) -> None:
            captured.append(payload)

        class StubWebSearch:
            async def execute(self, **kwargs):
                return {
                    "llmContent": "Top result summary",
                    "returnDisplay": {
                        "sources": [
                            {
                                "index": 1,
                                "title": "Example",
                                "uri": "https://example.com",
                            }
                        ]
                    },
                }

        botsignal.register_sender("telegram", sender)
        orchestrator = MessageOrchestrator(botsignal)
        orchestrator._web_search_tool = StubWebSearch()
        request = IncomingRequest(
            platform="telegram",
            user_id="u_ws",
            text="web search latest python news",
            reply_target=ReplyTarget(platform="telegram", chat_id="101"),
        )
        await orchestrator.handle(request)

        self.assertEqual(len(captured), 1)
        text = captured[0].text or ""
        self.assertIn("[tool:web_search action:query status:ok]", text)
        self.assertIn("Web search complete.", text)
        self.assertIn("Top result summary", text)

    async def test_web_fetch_route(self) -> None:
        captured: list[SignalPayload] = []
        botsignal = BotSignal()

        async def sender(_target: ReplyTarget, payload: SignalPayload) -> None:
            captured.append(payload)

        class StubWebFetch:
            async def execute(self, **kwargs):
                return {"success": True, "output": "Fetched content summary"}

        botsignal.register_sender("discord", sender)
        orchestrator = MessageOrchestrator(botsignal)
        orchestrator._web_fetch_tool = StubWebFetch()
        request = IncomingRequest(
            platform="discord",
            user_id="u_wf",
            text="/webfetch https://example.com",
            reply_target=ReplyTarget(platform="discord", chat_id="202"),
        )
        await orchestrator.handle(request)

        self.assertEqual(len(captured), 1)
        text = captured[0].text or ""
        self.assertIn("[tool:web_fetch action:fetch status:ok]", text)
        self.assertIn("Web fetch complete.", text)
        self.assertIn("Fetched content summary", text)

    async def test_xai_image_route(self) -> None:
        captured: list[SignalPayload] = []
        botsignal = BotSignal()

        async def sender(_target: ReplyTarget, payload: SignalPayload) -> None:
            captured.append(payload)

        class StubXAIImage:
            async def execute(self, **kwargs):
                return {
                    "success": True,
                    "model": "grok-2-vision-latest",
                    "image_url": kwargs.get("image_url"),
                    "output": "This looks like a test image.",
                }

        botsignal.register_sender("telegram", sender)
        orchestrator = MessageOrchestrator(botsignal)
        orchestrator._xai_image_tool = StubXAIImage()
        request = IncomingRequest(
            platform="telegram",
            user_id="u_img",
            text="image understand https://example.com/a.png",
            reply_target=ReplyTarget(platform="telegram", chat_id="505"),
        )
        await orchestrator.handle(request)

        self.assertEqual(len(captured), 1)
        text = captured[0].text or ""
        self.assertIn("[tool:xai_image_understand action:analyze status:ok]", text)
        self.assertIn("Image understanding complete.", text)
        self.assertIn("https://example.com/a.png", text)

    async def test_unhandled_prompt_routes_to_killo_provider(self) -> None:
        captured: list[SignalPayload] = []
        botsignal = BotSignal()

        async def sender(_target: ReplyTarget, payload: SignalPayload) -> None:
            captured.append(payload)

        class StubKillo:
            async def chat_completion_resilient(self, **kwargs):
                return {
                    "success": True,
                    "content": "Killo reply content",
                    "model_used": "minimax/minimax-m2.5:free",
                }

        botsignal.register_sender("telegram", sender)
        orchestrator = MessageOrchestrator(botsignal)
        orchestrator._killo_provider = StubKillo()
        request = IncomingRequest(
            platform="telegram",
            user_id="u_killo",
            text="explain quantum physics deeply",  # triggers minichat escalate=True
            reply_target=ReplyTarget(platform="telegram", chat_id="303"),
        )
        await orchestrator.handle(request)

        self.assertEqual(len(captured), 1)
        text = captured[0].text or ""
        self.assertIn("Killo reply content", text)
        self.assertIn(
            "[tool:killo_provider action:chat_completion_resilient status:ok]", text
        )

    async def test_unhandled_prompt_killo_failure_falls_back_to_minichat(self) -> None:
        captured: list[SignalPayload] = []
        botsignal = BotSignal()

        async def sender(_target: ReplyTarget, payload: SignalPayload) -> None:
            captured.append(payload)

        class StubKilloFail:
            async def chat_completion_resilient(self, **kwargs):
                return {"success": False, "error": "network down"}

        botsignal.register_sender("discord", sender)
        orchestrator = MessageOrchestrator(botsignal)
        orchestrator._killo_provider = StubKilloFail()
        request = IncomingRequest(
            platform="discord",
            user_id="u_killo_fail",
            text="some unresolved random prompt",
            reply_target=ReplyTarget(platform="discord", chat_id="404"),
        )
        await orchestrator.handle(request)

        self.assertEqual(len(captured), 1)
        text = captured[0].text or ""
        self.assertIn("SARAS is analyzing your problem", text)
        self.assertIn(
            "[tool:killo_provider action:chat_completion_resilient status:error]",
            text,
        )


if __name__ == "__main__":
    unittest.main()
