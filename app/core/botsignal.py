from __future__ import annotations

import hashlib
import itertools
import json
import threading
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from app.core.audit import AuditEvent, get_action_logger
from app.core.models import ReplyTarget, SignalPayload, ToolTrace
from app.core.policy import get_policy_engine

if TYPE_CHECKING:
    from app.runtime.outbox import OutboxEntry, Sender as OutboxSender

Sender = Callable[[ReplyTarget, SignalPayload], Awaitable[None]]

# A monotonic nonce source for idempotency keys.  We use a process-wide
# counter combined with a high-resolution timestamp so every call to
# :meth:`BotSignal.send` has a unique nonce.  This means two separate
# ``send`` calls to the same chat with identical text do NOT collapse
# to a single outbox entry — they are distinct user intents.  Retries
# within a single send path go through :meth:`Outbox.drain_once`, which
# does not call back into ``send`` and therefore does not generate a
# new nonce.
_send_nonce = itertools.count()
_nonce_lock = threading.Lock()


def _new_nonce() -> int:
    with _nonce_lock:
        return next(_send_nonce) | (int(time.time_ns()) << 16)


def _payload_to_dict(payload: SignalPayload) -> dict[str, Any]:
    """Serialise the intent-bearing parts of a SignalPayload.

    We don't serialise the full dataclass — just the fields that
    should be hashed for the idempotency key.  Anything not in this
    dict (e.g. ``reply_to_id``) is preserved by the live sender
    and is not part of the dedup signature.
    """
    return {
        "text": payload.text,
        "source_kind": payload.source_kind,
        "evidence": list(payload.evidence or []),
        "tool_traces": [
            {
                "tool_name": t.tool_name,
                "action": t.action,
                "success": t.success,
            }
            for t in (payload.tool_traces or [])
        ],
    }


def _payload_hash(d: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(d, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _make_outbox_sender(bs_sender: Sender) -> OutboxSender:
    """Adapt BotSignal's ``(ReplyTarget, SignalPayload) -> None``
    sender into the Outbox's ``(OutboxEntry) -> None`` sender.

    The outbox owns delivery state; this adapter rehydrates the
    payload from the entry's JSON-safe dict and forwards the call.
    """

    async def _adapter(entry: OutboxEntry) -> None:
        target = ReplyTarget(
            platform=entry.channel,
            chat_id=entry.target,
        )
        payload = SignalPayload(
            text=entry.payload.get("text", ""),
            source_kind=entry.payload.get("source_kind"),
            evidence=list(entry.payload.get("evidence") or []),
            tool_traces=[
                ToolTrace(
                    tool_name=t["tool_name"],
                    action=t["action"],
                    success=bool(t["success"]),
                )
                for t in entry.payload.get("tool_traces", [])
            ],
        )
        await bs_sender(target, payload)

    return _adapter


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
        # Lazy-import to avoid a circular dependency: outbox.py
        # must not import anything from app.core (and therefore
        # from app.core.botsignal).
        from app.runtime.outbox import get_outbox, make_idempotency_key

        payload_dict = _payload_to_dict(payload)
        channel = target.platform.lower()
        # The nonce makes every call to ``send`` unique.  The hash
        # of the payload is preserved so a *retry* (e.g. after a
        # process restart) of a known-intent message dedupes; but
        # two distinct user messages with identical text and the
        # same target remain separate entries.
        key = make_idempotency_key(
            "botsignal",
            channel,
            target.chat_id,
            _payload_hash(payload_dict),
            _new_nonce(),
        )
        outbox = get_outbox()
        # Register the platform sender on the outbox the first time
        # we see this channel.  ``register_sender`` is a plain dict
        # assignment so this is idempotent and cheap.
        outbox.register_sender(channel, _make_outbox_sender(sender))
        entry = await outbox.enqueue(
            idempotency_key=key,
            channel=channel,
            target=target.chat_id,
            action="send",
            payload=payload_dict,
        )
        get_action_logger().record(
            AuditEvent(
                kind="message",
                action="send",
                actor="botsignal",
                success=True,
                metadata={
                    "platform": target.platform,
                    "chat_id": target.chat_id,
                    "source_kind": payload.source_kind,
                    "outbox_id": entry.id,
                    "outbox_key": entry.idempotency_key,
                    "via": "outbox",
                },
            )
        )
        # Lazy drain: try to deliver right now.  If the sender
        # fails the entry stays in the outbox and will be retried
        # on the next drain (per-send, on mode-change, or via
        # explicit ``get_outbox().drain_until_drained()``).  We
        # only raise when our specific entry is the one that
        # failed; other entries' failures (e.g. stale entries from
        # earlier in the process) are silently retried.
        await outbox.drain_once()
        if entry.state != "sent":
            raise RuntimeError(
                f"outbox drain failed for key={entry.idempotency_key}: "
                f"{entry.last_error}"
            )

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
        # FRIDAY: Adapt response for platform before sending
        try:
            from app.core.platform_adapter import adapt_response
            text = adapt_response(text, target.platform)
        except Exception:
            pass  # Platform adaptation is best-effort

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
