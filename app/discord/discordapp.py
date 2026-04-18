import logging
import os
import tempfile
from pathlib import Path

import discord
from app.core import (
    BotSignal,
    IncomingRequest,
    MessageOrchestrator,
    ReplyTarget,
    SignalPayload,
)
from app.core.render import to_discord_md

logger = logging.getLogger(__name__)
DISCORD_CONTENT_LIMIT = 1990  # Discord hard limit is 2000; leave headroom
DISCORD_FILE_CAPTION_LIMIT = 1000


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
        await channel.send(to_discord_md(text))

    async def send_to_target(self, target: ReplyTarget, payload: SignalPayload) -> None:
        raw_id = target.chat_id
        # Validate chat_id is numeric; fall back to the bot's default channel
        if raw_id and raw_id.isdigit():
            channel_id = int(raw_id)
        else:
            logger.warning(
                "Discord send_to_target: invalid chat_id %r, falling back to default channel %s",
                raw_id,
                self.channel_ID,
            )
            channel_id = self.channel_ID
        channel = self.get_channel(channel_id)
        if channel is None:
            channel = await self.fetch_channel(channel_id)

        temp_file_path: str | None = None
        content_text = payload.text or payload.caption or ""

        # If there is an explicit file or the text exceeds the limit, send as
        # a file attachment so nothing is lost.
        if len(content_text) > DISCORD_CONTENT_LIMIT and not payload.file_path:
            fd, temp_file_path = tempfile.mkstemp(
                prefix="saras_output_", suffix=".txt", text=True
            )
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(content_text)
            content_text = "Output exceeded message limit. Sent as file attachment."

        file_path = payload.file_path or temp_file_path
        if file_path:
            try:
                file = discord.File(file_path)
                await channel.send(
                    content=content_text[:DISCORD_CONTENT_LIMIT],
                    file=file,
                )
            finally:
                if temp_file_path and os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
            return

        text = payload.text or payload.caption or ""
        if payload.animation_url:
            text = f"{text}\n{payload.animation_url}".strip()
        rendered = to_discord_md(text)

        # Chunk into <=DISCORD_CONTENT_LIMIT segments so we never exceed 2000
        for chunk in self._chunk_text(rendered, DISCORD_CONTENT_LIMIT):
            await channel.send(chunk)

    @staticmethod
    def _chunk_text(text: str, limit: int) -> list[str]:
        """Split *text* into chunks of at most *limit* characters.

        Tries to break on newlines first, then on spaces, and only hard-cuts
        as a last resort.
        """
        if len(text) <= limit:
            return [text]

        chunks: list[str] = []
        while text:
            if len(text) <= limit:
                chunks.append(text)
                break
            # Try to break at a newline within the limit window
            cut = text.rfind("\n", 0, limit)
            if cut <= 0:
                # Fall back to space
                cut = text.rfind(" ", 0, limit)
            if cut <= 0:
                # Hard cut
                cut = limit
            chunks.append(text[:cut])
            text = text[cut:].lstrip("\n")
        return chunks

    def register_output_sender(self, botsignal: BotSignal) -> None:
        botsignal.register_sender("discord", self.send_to_target)

    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user or message.author.bot:
            return

        # If message has audio attachments, transcribe them
        if message.attachments:
            for attachment in message.attachments:
                if attachment.content_type and attachment.content_type.startswith(
                    "audio"
                ):
                    await self._handle_discord_audio(message, attachment)
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
            conversation_id=f"{message.channel.id}:{message.id}",
        )
        logger.info(
            "Discord incoming  user=%s  channel=%s  text=%r",
            message.author.id,
            message.channel.id,
            text[:120],
        )
        await self._orchestrator.handle(request)

    async def _handle_discord_audio(
        self, message: discord.Message, attachment: discord.Attachment
    ) -> None:
        """Download a Discord audio attachment, transcribe it, and handle as text."""
        from app.voice.transcribe import transcribe_audio

        suffix = Path(attachment.filename).suffix or ".ogg"
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        try:
            await attachment.save(Path(tmp_path))
            text = await transcribe_audio(tmp_path)
        finally:
            os.unlink(tmp_path)

        if not text:
            await message.channel.send("Sorry, I couldn't transcribe that audio.")
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
            conversation_id=f"{message.channel.id}:{message.id}",
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
