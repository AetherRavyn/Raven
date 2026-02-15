import logging
import os

from dotenv import load_dotenv

from app.core import BotSignal, MessageOrchestrator, ReplyTarget, SignalPayload
from app.telegram.command import (
    about,
    error_handler,
    handle_callback,
    handle_message,
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


def create_bot() -> Application:
    """Create and configure the Telegram bot application."""
    load_dotenv()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
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

    async def _send_telegram(target: ReplyTarget, payload: SignalPayload) -> None:
        chat_id: str | int
        chat_id = (
            int(target.chat_id)
            if target.chat_id.lstrip("-").isdigit()
            else target.chat_id
        )
        kwargs = {}
        if target.reply_to_id and target.reply_to_id.isdigit():
            kwargs["reply_to_message_id"] = int(target.reply_to_id)
        if payload.animation_url:
            await app.bot.send_animation(
                chat_id=chat_id,
                animation=payload.animation_url,
                caption=payload.caption or payload.text,
                **kwargs,
            )
            return
        if payload.video_path:
            with open(payload.video_path, "rb") as fh:
                await app.bot.send_video(
                    chat_id=chat_id,
                    video=fh,
                    caption=payload.caption or payload.text,
                    **kwargs,
                )
            return
        if payload.audio_path:
            with open(payload.audio_path, "rb") as fh:
                await app.bot.send_audio(
                    chat_id=chat_id,
                    audio=fh,
                    caption=payload.caption or payload.text,
                    **kwargs,
                )
            return
        if payload.file_path:
            with open(payload.file_path, "rb") as fh:
                await app.bot.send_document(
                    chat_id=chat_id,
                    document=fh,
                    caption=payload.caption or payload.text,
                    **kwargs,
                )
            return
        await app.bot.send_message(
            chat_id=chat_id,
            text=payload.text or payload.caption or "",
            **kwargs,
        )

    botsignal.register_sender("telegram", _send_telegram)


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
