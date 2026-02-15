import logging

import discord
from app.core import (
    BotSignal,
    IncomingRequest,
    MessageOrchestrator,
    ReplyTarget,
    SignalPayload,
)

logger = logging.getLogger(__name__)


class DiscordBot(discord.Client):
    def __init__(
        self,
        token: str | None,
        channel_ID: int,
        orchestrator: MessageOrchestrator,
        *,
        enable_message_content: bool = False,
    ):
        self._token = token
        self.channel_ID = channel_ID
        self._orchestrator = orchestrator

        intents = discord.Intents.default()
        # message_content is privileged; keep it opt-in to avoid portal errors.
        intents.message_content = enable_message_content
        super().__init__(intents=intents)

    async def on_ready(self):
        print(f"Logged in as {self.user}")
        if not self.intents.message_content:
            logger.warning(
                "Discord message_content intent is disabled. "
                "Text messages will not be processed reliably."
            )

    async def send_text(self, text: str):
        channel = self.get_channel(self.channel_ID)
        if not channel:
            return
        await channel.send(text)

    async def send_to_target(self, target: ReplyTarget, payload: SignalPayload) -> None:
        channel_id = int(target.chat_id)
        channel = self.get_channel(channel_id)
        if channel is None:
            channel = await self.fetch_channel(channel_id)
        if payload.file_path:
            file = discord.File(payload.file_path)
            await channel.send(content=payload.text or payload.caption, file=file)
            return
        text = payload.text or payload.caption or ""
        if payload.animation_url:
            text = f"{text}\n{payload.animation_url}".strip()
        await channel.send(text)

    def register_output_sender(self, botsignal: BotSignal) -> None:
        botsignal.register_sender("discord", self.send_to_target)

    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user or message.author.bot:
            return
        text = (message.content or "").strip()
        if not text:
            # Keep behavior explicit; without message content intent this is common.
            logger.info(
                "Skipping Discord message without text content (channel=%s, message_id=%s)",
                message.channel.id,
                message.id,
            )
            return

        request = IncomingRequest(
            platform="discord",
            user_id=str(message.author.id),
            text=text,
            reply_target=ReplyTarget(
                platform="discord",
                chat_id=str(message.channel.id),
                reply_to_id=str(message.id),
            ),
        )
        await self._orchestrator.handle(request)

    async def start_bot(self):
        if not self._token:
            raise ValueError("DISCORD_BOT_TOKEN is not set")
        await self.start(self._token)

    def run_bot(self):
        if not self._token:
            raise ValueError("DISCORD_BOT_TOKEN is not set")
        self.run(self._token)
