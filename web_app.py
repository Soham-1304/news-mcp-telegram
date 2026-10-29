import os
import sys
import re
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from telegram import Update
from telegram.constants import ParseMode

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from storage.database import initialize_db
from agent.config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    GROQ_API_KEY,
    DEFAULT_MODEL
)
from agent.workflow import generate_newsletter
from bot.telegram_bot import create_bot_application
from bot.formatter import clean_and_format_for_telegram, chunk_message

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


@app.api_route("/cron/daily-digest", methods=["GET", "POST"])
async def trigger_daily_digest(
    x_cron_secret: str = Header(default="", alias="X-Cron-Secret")
):
    if CRON_SECRET and x_cron_secret and x_cron_secret != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized cron trigger")

    target_chat_id = None
    if TELEGRAM_CHAT_ID:
        try:
            target_chat_id = int(TELEGRAM_CHAT_ID)
        except ValueError:
            pass
            
    subscribed = set()
    if telegram_app and "subscribed_chats" in telegram_app.bot_data:
        subscribed.update(telegram_app.bot_data["subscribed_chats"])
    if target_chat_id:
        subscribed.add(target_chat_id)

    if not subscribed:
        return JSONResponse(
            status_code=400,
            content={"message": "No subscribed chat_id found. Message /start to the bot on Telegram first."}
        )

    results = []
    for chat_id in subscribed:
        try:
            logger.info(f"Web Cron: Generating briefing for chat {chat_id}")
            newsletter = generate_newsletter(chat_id=chat_id)
            clean_html = clean_and_format_for_telegram(newsletter)
            chunks = chunk_message(clean_html, max_chars=3900)

            for chunk in chunks:
                try:
                    await telegram_app.bot.send_message(
                        chat_id=chat_id,
                        text=chunk,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True
                    )
                except Exception:
                    plain = re.sub(r"<[^>]+>", "", chunk)
                    await telegram_app.bot.send_message(chat_id=chat_id, text=plain)
            
            results.append({"chat_id": chat_id, "status": "delivered"})
        except Exception as e:
            logger.error(f"Cron delivery failed for {chat_id}: {e}", exc_info=True)
            results.append({"chat_id": chat_id, "status": "failed", "error": str(e)})

    return {"message": "Cron digest executed", "deliveries": results}
