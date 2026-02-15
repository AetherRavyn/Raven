import logging
from datetime import datetime

from app.core import IncomingRequest, ReplyTarget
from app.telegram.constants import ORCHESTRATOR_KEY
from telegram import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command - greet user and show options."""
    user = update.effective_user
    keyboard = [
        [KeyboardButton("/help"), KeyboardButton("/status")],
        [KeyboardButton("/about")],
    ]
    reply_markup = ReplyKeyboardMarkup(
        keyboard=keyboard, resize_keyboard=True, one_time_keyboard=False
    )
    await update.message.reply_text(
        f"Hi {user.first_name}! I'm SARAS, your personal AI assistant.\n\n"
        "I'm here to help you with anything you need. "
        "You can send me text messages and I'll respond.\n\n"
        "Use /help to see what I can do.",
        reply_markup=reply_markup,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /help command - show available commands."""
    help_text = (
        "*Available Commands:*\n\n"
        "/start - Start the bot and show the main menu\n"
        "/help - Show this help message\n"
        "/status - Check bot status\n"
        "/about - Learn about SARAS\n\n"
        "*Just send me a message and I'll respond!*"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /status command - show bot status."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status_text = f"*SARAS Status*\n\nStatus: Online\nPlatform: Telegram\nTime: {now}\n"
    await update.message.reply_text(status_text, parse_mode="Markdown")


async def about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /about command - show info about SARAS."""
    about_text = (
        "*About SARAS*\n\n"
        "SARAS is an intelligent personal AI companion - "
        "a bot that acts as your friend, assistant, and brainstorming partner.\n\n"
        "SARAS can be reached from multiple platforms:\n"
        "- Telegram (you're here!)\n"
        "- Discord\n"
        "- WhatsApp\n"
        "- Web Dashboard\n\n"
        "Built with Python and python-telegram-bot."
    )
    await update.message.reply_text(about_text, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text and dispatch to shared orchestrator."""
    if not update.message or not update.effective_user or not update.effective_chat:
        return

    user_id = str(update.effective_user.id)
    user = update.effective_user
    text = update.message.text or ""
    logger.info(f"Message from {user.first_name} ({user.id}): {text}")

    orchestrator = context.application.bot_data.get(ORCHESTRATOR_KEY)
    if orchestrator is None:
        await update.message.reply_text("Runtime is not ready yet. Please try again.")
        return

    request = IncomingRequest(
        platform="telegram",
        user_id=user_id,
        text=text,
        reply_target=ReplyTarget(
            platform="telegram",
            chat_id=str(update.effective_chat.id),
            reply_to_id=str(update.message.message_id),
        ),
    )
    await orchestrator.handle(request)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard button callbacks."""
    query = update.callback_query
    await query.answer()

    data = query.data
    logger.info(f"Callback received: {data}")

    if data == "status":
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await query.edit_message_text(f"SARAS is online. Time: {now}")
    elif data == "help":
        await query.edit_message_text("Send /help to see available commands.")
    else:
        await query.edit_message_text(f"You selected: {data}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors in the bot."""
    logger.error(f"Exception while handling an update: {context.error}")
