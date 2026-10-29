import logging
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters
)

from agent.config import TELEGRAM_BOT_TOKEN
from bot.handlers import (
    start_command,
    digest_command,
    search_command,
    clear_command,
    handle_chat_message
)
from bot.scheduler import setup_scheduler

logger = logging.getLogger("news_agent.bot")


def create_bot_application():
    """Builds and configures the Telegram Bot Application."""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN is missing. Please set it in .env")

    # Initialize Application with JobQueue enabled
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Command Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler(["digest", "news"], digest_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("clear", clear_command))

    # Freeform message & conversation handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_chat_message))

    # Setup daily cron trigger
    setup_scheduler(app)

    return app

