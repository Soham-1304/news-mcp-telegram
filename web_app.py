import os
import sys
import re
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Header, HTTPException, Response, BackgroundTasks
from fastapi.responses import JSONResponse
from telegram import Update, Bot
from telegram.constants import ParseMode

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from storage.database import initialize_db, get_subscribers, add_subscriber
from agent.config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    GROQ_API_KEY,
    DEFAULT_MODEL
)
from agent.workflow import generate_newsletter
from bot.telegram_bot import create_bot_application
from bot.formatter import clean_and_format_for_telegram, chunk_message, html_to_plain_text_with_links

logger = logging.getLogger("news_agent.web")
logging.basicConfig(level=logging.INFO)

telegram_app = None
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
CRON_SECRET = os.getenv("CRON_SECRET", "techno-news-secret-cron-key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_app
    initialize_db()
    telegram_app = create_bot_application()
    
    await telegram_app.initialize()
    await telegram_app.start()
    
    if WEBHOOK_URL:
        webhook_endpoint = f"{WEBHOOK_URL.rstrip('/')}/webhook"
        logger.info(f"Setting Telegram webhook to: {webhook_endpoint}")
        await telegram_app.bot.set_webhook(url=webhook_endpoint)
    else:
        logger.info("Webhook active for manual/external configuration.")
        
    yield
    
    if telegram_app:
        if WEBHOOK_URL:
            await telegram_app.bot.delete_webhook()
        await telegram_app.stop()
        await telegram_app.shutdown()


app = FastAPI(
    title="Techno News Agent Web Service",
    description="FastAPI Web Service hosting Telegram Webhook, Web Cron, and MCP Client",
    lifespan=lifespan
)


@app.get("/")
async def health_check():
    return {
        "status": "online",
        "bot": "Techno (@techn0o_bot)",
        "model": DEFAULT_MODEL,
        "mcp_server": "active",
        "webhook_url": WEBHOOK_URL or "configured via Telegram API"
    }


@app.post("/webhook")
async def telegram_webhook(request: Request):
    if not telegram_app:
        raise HTTPException(status_code=503, detail="Telegram bot not ready")
        
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return Response(status_code=200)


_cron_digest_lock = asyncio.Lock()


async def deliver_cron_digest_task():
    """Background task to generate and deliver newsletter without blocking the HTTP response."""
    if _cron_digest_lock.locked():
        logger.info("Cron digest already executing, skipping duplicate execution.")
        return

    async with _cron_digest_lock:
        subscribers = set(get_subscribers())
        if TELEGRAM_CHAT_ID:
            try:
                subscribers.add(int(TELEGRAM_CHAT_ID))
            except ValueError:
                pass

        bot = telegram_app.bot if (telegram_app and telegram_app.bot) else Bot(token=TELEGRAM_BOT_TOKEN)

        logger.info(f"Cron Digest Task running for subscribers: {subscribers}")
        for chat_id in subscribers:
            try:
                logger.info(f"Web Cron: Generating briefing for chat {chat_id}")
                newsletter = generate_newsletter(chat_id=chat_id)
                clean_html = clean_and_format_for_telegram(newsletter)
                chunks = chunk_message(clean_html, max_chars=3900)

                for chunk in chunks:
                    try:
                        await bot.send_message(
                            chat_id=chat_id,
                            text=chunk,
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True
                        )
                    except Exception as e:
                        logger.warning(f"Telegram HTML send failed ({e}), using plaintext with preserved links")
                        plain = html_to_plain_text_with_links(chunk)
                        await bot.send_message(chat_id=chat_id, text=plain)

                logger.info(f"Successfully delivered morning briefing to {chat_id}")
            except Exception as e:
                logger.error(f"Cron delivery failed for {chat_id}: {e}", exc_info=True)


@app.api_route("/cron/daily-digest", methods=["GET", "POST"])
async def trigger_daily_digest(
    background_tasks: BackgroundTasks,
    x_cron_secret: str = Header(default="", alias="X-Cron-Secret")
):
    if CRON_SECRET and x_cron_secret and x_cron_secret != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized cron trigger")

    # Queue execution immediately in background so cron-job.org gets an ultra-lightweight response
    background_tasks.add_task(deliver_cron_digest_task)
    return Response(content="OK", media_type="text/plain", status_code=200)
