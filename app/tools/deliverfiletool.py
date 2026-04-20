from typing import Any, Dict
from app.core.botsignal import get_botsignal
from app.core.models import SignalPayload
from app.tools.base import BaseTool, ToolCapability, ToolParameter, ToolSchema

class DeliverFileTool(BaseTool):
    """
    Sends a locally generated file or downloaded document directly to the user
    in their current active chat session.
    """

    def get_name(self) -> str:
        return "deliver_file_to_user"

    def get_description(self) -> str:
        return "Sends a file directly to the user in the current chat. Use this when you have successfully created or downloaded a file (like a zip, pdf, image, etc.) and want the user to have it."

    def get_schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.get_name(),
            description=self.get_description(),
            parameters=[
                ToolParameter(
                    name="file_path",
                    type="string",
                    description="Absolute path to the file to send to the user.",
                    required=True,
                ),
                ToolParameter(
                    name="caption",
                    type="string",
                    description="Optional message/caption to accompany the file.",
                    required=False,
                ),
            ],
        )

    def get_capabilities(self) -> ToolCapability:
        return ToolCapability(
            required_permissions=["file.read", "message.send"],
            risk_level="low",
            cost_tier="low",
            confirmation_policy="never",
            readonly=True,
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        file_path = kwargs.get("file_path")
        caption = kwargs.get("caption", "Here is the file you requested.")
        request = kwargs.get("_request")

        if not file_path:
            return {"success": False, "error": "file_path is required."}

        if not request or not request.reply_target:
            return {"success": False, "error": "No active user chat context found."}

        try:
            botsignal = get_botsignal()
            payload = SignalPayload(text=caption, file_path=file_path, source_kind="tool_delivery")
            await botsignal.send(request.reply_target, payload)
            
            return {
                "success": True,
                "message": f"Successfully delivered file {file_path} to the user.",
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to send file: {e}"}
