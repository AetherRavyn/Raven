import logging
from typing import Any, Dict

from app.core.botsignal import get_botsignal
from app.core.models import ReplyTarget, SignalPayload
from app.tools.base import BaseTool, ToolParameter, ToolSchema

logger = logging.getLogger(__name__)


class PlatformMessagingTool(BaseTool):
    """
    Allows the agent to act as a Digital Proxy, sending messages
    autonomously to any user on any supported platform (Telegram, Discord).
    """

    def get_name(self) -> str:
        return "send_platform_message"

    def get_description(self) -> str:
        return (
            "Acts as the user's Digital Proxy. Send a message directly to a user "
            "or channel on a specific platform (e.g., 'telegram', 'discord'). "
            "Use this to push asynchronous alerts, send reports to specific chats, "
            "or autonomously reply on the user's behalf."
        )

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="platform",
                    type="string",
                    description="The target platform (e.g., 'telegram', 'discord', 'slack').",
                    required=True,
                    enum=["telegram", "discord", "slack"],
                ),
                ToolParameter(
                    name="chat_id",
                    type="string",
                    description="The target chat ID or user ID on the platform.",
                    required=True,
                ),
                ToolParameter(
                    name="message",
                    type="string",
                    description="The text content of the message to send.",
                    required=True,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        platform = kwargs.get("platform")
        chat_id = kwargs.get("chat_id")
        message = kwargs.get("message")

        if not platform or not chat_id or not message:
            return {
                "success": False,
                "error": "platform, chat_id, and message are required.",
            }

        # Reject obvious placeholder / non-numeric IDs for platforms that need integers
        numeric_platforms = {"discord", "telegram"}
        chat_id_str = str(chat_id).strip()
        if platform.lower() in numeric_platforms and not chat_id_str.isdigit():
            return {
                "success": False,
                "error": (
                    f"chat_id must be a numeric ID for {platform}, "
                    f"got '{chat_id_str}'. Ask the user for the correct ID."
                ),
            }

        botsignal = get_botsignal()
        if not botsignal.has_sender(platform):
            return {
                "success": False,
                "error": f"Platform '{platform}' is not currently registered or online.",
            }

        try:
            target = ReplyTarget(platform=platform, chat_id=str(chat_id))
            payload = SignalPayload(text=message, source_kind="digital_proxy")
            await botsignal.send(target, payload)

            return {
                "success": True,
                "message": f"Successfully pushed message to {platform} chat {chat_id}.",
            }
        except Exception as e:
            logger.error(f"Failed to send platform message: {e}")
            return {"success": False, "error": str(e)}
