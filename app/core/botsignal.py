from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.core.audit import AuditEvent, get_action_logger
from app.core.models import ReplyTarget, SignalPayload, ToolTrace
from app.core.policy import get_policy_engine

Sender = Callable[[ReplyTarget, SignalPayload], Awaitable[None]]


class BotSignal:
    """Unified output API used by all platform connectors."""

    def __init__(self) -> None:
        self._senders: dict[str, Sender] = {}

    def register_sender(self, platform: str, sender: Sender) -> None:
        self._senders[platform.lower()] = sender

    def has_sender(self, platform: str) -> bool:
        return platform.lower() in self._senders

    def _annotation_lines(self, payload: SignalPayload) -> list[str]:
        lines: list[str] = []
        if payload.source_kind:
            lines.append(f"[source:{payload.source_kind}]")
        for evidence in payload.evidence or []:
            lines.append(f"[evidence] {evidence}")
        for trace in payload.tool_traces or []:
            status = "ok" if trace.success else "error"
            base = f"[tool:{trace.tool_name} action:{trace.action} status:{status}]"
            lines.append(f"{base} {trace.detail}" if trace.detail else base)
        return lines

    def _payload_with_annotations(self, payload: SignalPayload) -> SignalPayload:
        # In earlier versions, this appended debug annotations to every message.
        # This was polluting user chats, so we now just return the clean payload.
        # Tool traces and evidence are still available on the payload object for
        # dashboards or custom loggers to use without forcing them into the message text.
        return payload

    async def send(self, target: ReplyTarget, payload: SignalPayload) -> None:
        sender = self._senders.get(target.platform.lower())
        if not sender:
            raise ValueError(f"No sender registered for platform '{target.platform}'")
        get_action_logger().record(
            AuditEvent(
                kind="message",
                action="send",
                success=True,
                metadata={
                    "platform": target.platform,
                    "chat_id": target.chat_id,
                    "source_kind": payload.source_kind,
                },
            )
        )
        await sender(target, self._payload_with_annotations(payload))

    async def send_confirmation_request(
        self,
        target: ReplyTarget,
        title: str,
        detail: str,
        source_kind: str | None = None,
    ) -> None:
        await self.send_text(
            target,
            f"{title}\n{detail}\nReply with YES to continue.",
            source_kind=source_kind,
        )

    async def send_text(
        self,
        target: ReplyTarget,
        text: str,
        source_kind: str | None = None,
        tool_traces: list[ToolTrace] | None = None,
        evidence: list[str] | None = None,
    ) -> None:
        await self.send(
            target,
            SignalPayload(
                text=text,
                source_kind=source_kind,
                tool_traces=tool_traces,
                evidence=evidence,
            ),
        )

    async def send_tool_text(
        self,
        target: ReplyTarget,
        text: str,
        tool_name: str,
        action: str,
        success: bool,
        detail: str | None = None,
        source_kind: str | None = None,
    ) -> None:
        await self.send_text(
            target,
            text,
            source_kind=source_kind,
            tool_traces=[
                ToolTrace(
                    tool_name=tool_name,
                    action=action,
                    success=success,
                    detail=detail,
                )
            ],
        )

    async def send_to_platform(
        self,
        platform: str,
        chat_id: str,
        payload: SignalPayload,
        reply_to_id: str | None = None,
    ) -> None:
        await self.send(
            ReplyTarget(platform=platform, chat_id=chat_id, reply_to_id=reply_to_id),
            payload,
        )


_GLOBAL_BOTSIGNAL = BotSignal()


def get_botsignal() -> BotSignal:
    return _GLOBAL_BOTSIGNAL
