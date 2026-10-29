import datetime
import logging
from zoneinfo import ZoneInfo
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from agent.config import SCHEDULE_TIME, SCHEDULE_TIMEZONE, TELEGRAM_CHAT_ID
from agent.workflow import generate_newsletter

logger = logging.getLogger("news_agent.bot.scheduler")


async def scheduled_newsletter_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Cron job triggered automatically every morning.
    Generates fresh newsletter and broadcasts to subscribed users.
    """
    logger.info("Executing scheduled morning newsletter job...")
    
    # Collect target chat IDs
    subscribed = set(context.application.bot_data.get("subscribed_chats", set()))
    if TELEGRAM_CHAT_ID:
        try:
            subscribed.add(int(TELEGRAM_CHAT_ID))
        except ValueError:
            pass

    if not subscribed:
        logger.warning("No subscribed chats found for scheduled newsletter.")
        return

    for chat_id in subscribed:
        try:
            logger.info(f"Delivering morning briefing to chat_id: {chat_id}")
            newsletter = generate_newsletter(chat_id=chat_id)
            
            # Send message safely with length check
            max_len = 3900
            if len(newsletter) <= max_len:
                await context.bot.send_message(chat_id=chat_id, text=newsletter, parse_mode=ParseMode.MARKDOWN)
            else:
                chunks = [newsletter[i:i + max_len] for i in range(0, len(newsletter), max_len)]
                for chunk in chunks:
                    await context.bot.send_message(chat_id=chat_id, text=chunk, parse_mode=ParseMode.MARKDOWN)
                    
            logger.info(f"Successfully sent scheduled newsletter to {chat_id}")
        except Exception as e:
            logger.error(f"Failed to send scheduled newsletter to {chat_id}: {e}", exc_info=True)


def setup_scheduler(application):
    """Configures the daily morning cron trigger on the Telegram JobQueue."""
    try:
        parts = SCHEDULE_TIME.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        tz = ZoneInfo(SCHEDULE_TIMEZONE)
        target_time = datetime.time(hour=hour, minute=minute, tzinfo=tz)

        job_queue = application.job_queue
        if job_queue is None:
            logger.warning("JobQueue is not initialized. Ensure python-telegram-bot[job-queue] is installed.")
            return

        job_queue.run_daily(
            scheduled_newsletter_job,
            time=target_time,
            name="daily_morning_newsletter"
        )
        logger.info(f"Scheduled morning newsletter configured for {target_time.strftime('%H:%M')} {SCHEDULE_TIMEZONE}")
    except Exception as e:
        logger.error(f"Error configuring daily scheduler: {e}", exc_info=True)

