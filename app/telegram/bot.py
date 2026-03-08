import logging
import os
import tempfile

from app.core import BotSignal, MessageOrchestrator, ReplyTarget, SignalPayload
from app.core.render import to_telegram_html
from app.settings.config import Config
from app.telegram.command import (
    about,
    error_handler,
    handle_callback,
    handle_message,
    handle_voice_message,
    help_command,
    start,
    status,
)
from app.telegram.constants import ORCHESTRATOR_KEY
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

logger = logging.getLogger(__name__)
TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_CAPTION_LIMIT = 1024


def create_bot() -> Application:
    """Create and configure the Telegram bot application."""
    token = Config.TELEGRAM_BOT_TOKEN
    if not token or token == "your_telegram_bot_token_here":
        raise ValueError(
            "TELEGRAM_BOT_TOKEN is not set. "
            "Get a token from @BotFather on Telegram and add it to your .env file."
        )

    app = Application.builder().token(token).build()

    # Register command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("about", about))

    # Register message handler for non-command text messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Register voice/audio handler
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice_message))

    # Register callback query handler for inline keyboard buttons
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Register error handler
    app.add_error_handler(error_handler)

    logger.info("Telegram bot configured successfully.")
    return app


def bind_runtime(
    app: Application, orchestrator: MessageOrchestrator, botsignal: BotSignal
) -> None:
    """Bind runtime objects and register Telegram sender on BotSignal."""
    app.bot_data[ORCHESTRATOR_KEY] = orchestrator
    app.bot_data["botsignal"] = botsignal

    async def _send_telegram(target: ReplyTarget, payload: SignalPayload) -> None:
        chat_id: str | int
        chat_id = (
            int(target.chat_id)
            if target.chat_id.lstrip("-").isdigit()
            else target.chat_id
        )
        kwargs = {}
        temp_file_path: str | None = None
        if target.reply_to_id and target.reply_to_id.isdigit():
            kwargs["reply_to_message_id"] = int(target.reply_to_id)

        message_text = payload.text or payload.caption or ""
        if len(message_text) > TELEGRAM_TEXT_LIMIT and not payload.file_path:
            fd, temp_file_path = tempfile.mkstemp(
                prefix="saras_output_", suffix=".txt", text=True
            )
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(message_text)
            message_text = "Output exceeded message limit. Sent as file attachment."

        file_path = payload.file_path or temp_file_path
        caption_text = (payload.caption or message_text or "")[:TELEGRAM_CAPTION_LIMIT]

        if payload.animation_url:
            try:
                await app.bot.send_animation(
                    chat_id=chat_id,
                    animation=payload.animation_url,
                    caption=caption_text,
                    **kwargs,
                )
            finally:
                if temp_file_path and os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
            return
        if payload.video_path:
            try:
                with open(payload.video_path, "rb") as fh:
                    await app.bot.send_video(
                        chat_id=chat_id,
                        video=fh,
                        caption=caption_text,
                        **kwargs,
                    )
            finally:
                if temp_file_path and os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
            return
        if payload.audio_path:
            try:
                with open(payload.audio_path, "rb") as fh:
                    await app.bot.send_audio(
                        chat_id=chat_id,
                        audio=fh,
                        caption=caption_text,
                        **kwargs,
                    )
            finally:
                if temp_file_path and os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
            return
        if file_path:
            try:
                with open(file_path, "rb") as fh:
                    await app.bot.send_document(
                        chat_id=chat_id,
                        document=fh,
                        caption=caption_text,
                        **kwargs,
                    )
            finally:
                if temp_file_path and os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
            return
        try:
            rendered_text, parse_mode = to_telegram_html(message_text)
            send_kwargs = {**kwargs}
            if parse_mode:
                send_kwargs["parse_mode"] = parse_mode
            await app.bot.send_message(
                chat_id=chat_id,
                text=rendered_text,
                **send_kwargs,
            )
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    botsignal.register_sender("telegram", _send_telegram)

    async def _send_telegram_voice(target: ReplyTarget, payload: SignalPayload) -> None:
        """Telegram sender that replies with a voice note for final responses.

        Status / tool-progress messages (source_kind == "status") are forwarded
        as plain text to avoid unnecessary TTS overhead.
        """
        # Status messages → plain text via the existing sender
        if payload.source_kind == "status":
            plain_target = ReplyTarget(
                platform="telegram",
                chat_id=target.chat_id,
                reply_to_id=target.reply_to_id,
            )
            await _send_telegram(plain_target, payload)
            return

        # Final response with text → generate TTS voice note
        if payload.text:
            from app.voice.tts import synthesize  # noqa: PLC0415

            audio_path = await synthesize(payload.text)
            if audio_path:
                chat_id: str | int = (
                    int(target.chat_id)
                    if target.chat_id.lstrip("-").isdigit()
                    else target.chat_id
                )
                kwargs: dict = {}
                if target.reply_to_id and target.reply_to_id.isdigit():
                    kwargs["reply_to_message_id"] = int(target.reply_to_id)
                try:
                    with open(audio_path, "rb") as fh:
                        await app.bot.send_voice(chat_id=chat_id, voice=fh, **kwargs)
                finally:
                    try:
                        os.unlink(audio_path)
                    except OSError:
                        pass
                return

        # Fallback: no audio generated or no text → regular text message
        await _send_telegram(target, payload)

    botsignal.register_sender("telegram_voice", _send_telegram_voice)


def run_bot() -> None:
    """Create and run the Telegram bot (blocking, uses long-polling)."""
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    # Reduce noise from httpx
    logging.getLogger("httpx").setLevel(logging.WARNING)

    logger.info("Starting SARAS Telegram bot...")
    app = create_bot()
    app.run_polling(drop_pending_updates=True)
