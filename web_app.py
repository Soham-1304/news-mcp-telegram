import os
import sys
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from telegram import Update

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

logger = logging.getLogger("news_agent.web")
logging.basicConfig(level=logging.INFO)

# Global Telegram Application instance
telegram_app = None
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")  # e.g. https://your-service.onrender.com
CRON_SECRET = os.getenv("CRON_SECRET", "techno-news-secret-cron-key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI Lifespan: Start and stop the Telegram bot application."""
    global telegram_app
    initialize_db()
    telegram_app = create_bot_application()
    
    # Initialize the telegram bot
    await telegram_app.initialize()
    await telegram_app.start()
    
    if WEBHOOK_URL:
        webhook_endpoint = f"{WEBHOOK_URL.rstrip('/')}/webhook"
        logger.info(f"Setting Telegram webhook to: {webhook_endpoint}")
        await telegram_app.bot.set_webhook(url=webhook_endpoint)
    else:
        logger.info("No WEBHOOK_URL set. Webhook endpoint /webhook is active for manual configuration.")
        
    yield
    
    # Teardown
    if telegram_app:
        if WEBHOOK_URL:
            await telegram_app.bot.delete_webhook()
        await telegram_app.stop()
        await telegram_app.shutdown()


app = FastAPI(
    title="Techno News Agent Web Service",
    description="FastAPI Web Service hosting the Telegram Webhook, Cron Trigger endpoint, and MCP server",
    lifespan=lifespan
)


@app.get("/")
async def health_check():
    """Health check endpoint for Render / Railway / Uptime monitoring."""
    return {
        "status": "online",
        "bot": "Techno (@techn0o_bot)",
        "model": DEFAULT_MODEL,
        "mcp_server": "active",
        "webhook_url": WEBHOOK_URL or "not configured (long-polling or direct POST)"
    }


@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Telegram Webhook Endpoint: receives updates directly from Telegram servers."""
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
    """
    Web Cron Endpoint:
    Can be called by external cron services (cron-job.org, Render Cron, GitHub Actions)
    at 07:00 AM every morning.
    """
    if CRON_SECRET and x_cron_secret and x_cron_secret != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized cron trigger")

    target_chat_id = None
    if TELEGRAM_CHAT_ID:
        try:
            target_chat_id = int(TELEGRAM_CHAT_ID)
        except ValueError:
            pass
            
    # Also check subscribed chats from bot_data if available
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
            
            # Send message safely with length check
            max_len = 3900
            if len(newsletter) <= max_len:
                await telegram_app.bot.send_message(chat_id=chat_id, text=newsletter, parse_mode="Markdown")
            else:
                chunks = [newsletter[i:i + max_len] for i in range(0, len(newsletter), max_len)]
                for chunk in chunks:
                    await telegram_app.bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")
            
            results.append({"chat_id": chat_id, "status": "delivered"})
        except Exception as e:
            logger.error(f"Cron delivery failed for {chat_id}: {e}", exc_info=True)
            results.append({"chat_id": chat_id, "status": "failed", "error": str(e)})

    return {"message": "Cron digest executed", "deliveries": results}

