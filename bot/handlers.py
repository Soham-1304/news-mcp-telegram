import re
import logging
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from agent.workflow import generate_newsletter, chat_with_agent
from agent.tools import search_news_tool
from agent.config import SCHEDULE_TIME, SCHEDULE_TIMEZONE
from bot.formatter import clean_and_format_for_telegram, chunk_message

logger = logging.getLogger("news_agent.bot.handlers")

# Standalone phrases that mean "give me the general morning briefing" without a specific topic
STANDALONE_DIGEST_PHRASES = {
    "more news",
    "find more news",
    "give me more news",
    "show more news",
    "daily news",
    "daily digest",
    "daily briefing",
    "morning digest",
    "morning briefing",
    "today's news",
    "todays news",
    "news digest",
}


async def send_formatted_message(update: Update, text: str, reply_to_message: bool = False):
    """
    Formats text into clean, beautiful Telegram HTML (converting headers, bullets, links)
    and delivers it chunked safely within Telegram's 4096 character limits.
    """
    clean_html = clean_and_format_for_telegram(text)
    chunks = chunk_message(clean_html, max_chars=3900)

    for i, chunk in enumerate(chunks):
        try:
            if reply_to_message and i == 0 and update.message:
                await update.message.reply_text(chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
            elif update.effective_chat:
                await update.effective_chat.send_message(chunk, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception as e:
            logger.warning(f"HTML send failed ({e}), stripping tags and retrying as plain text")
            plain_text = re.sub(r"<[^>]+>", "", chunk)
            if reply_to_message and i == 0 and update.message:
                await update.message.reply_text(plain_text)
            elif update.effective_chat:
                await update.effective_chat.send_message(plain_text)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /start command."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    if "subscribed_chats" not in context.application.bot_data:
        context.application.bot_data["subscribed_chats"] = set()
    context.application.bot_data["subscribed_chats"].add(chat_id)

    welcome_text = (
        f"👋 <b>Welcome, {user.first_name}!</b> I am <b>Techno</b>, your AI & Tech News Intelligence Agent.\n\n"
        f"📡 <b>What I do:</b>\n"
        f"• Track <b>In The World of AI</b>, <b>DeepLearning.AI</b>, <b>The Guardian</b>, <b>MIT Technology Review</b>, and <b>TechCrunch AI</b>.\n"
        f"• Run an intelligent <b>SQLite Deduplication & Fuzzy Matching</b> handshake so you never see repeat stories.\n"
        f"• Deliver a crisp intelligence briefing every morning at <b>{SCHEDULE_TIME} ({SCHEDULE_TIMEZONE})</b>.\n"
        f"• Answer questions on specific topics (e.g. <i>'What are Google Q3 earnings?'</i> or <i>'Tell me about Gemini 4 Carbon'</i>)!\n\n"
        f"⚡ <b>Commands:</b>\n"
        f"• <code>/digest</code> or <code>/news</code> - Get today's general briefing\n"
        f"• <code>/search &lt;topic&gt;</code> - Search news across all sources\n"
        f"• <code>/clear</code> - Reset conversation memory\n"
        f"• Or simply <b>ask me any question</b> directly!"
    )
    await send_formatted_message(update, welcome_text)


async def digest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /digest or /news command."""
    chat_id = update.effective_chat.id
    status_msg = await update.message.reply_text("🔄 <i>Gathering and synthesizing fresh intelligence...</i>", parse_mode=ParseMode.HTML)
    
    try:
        newsletter = generate_newsletter(chat_id=chat_id)
        await status_msg.delete()
        await send_formatted_message(update, newsletter)
    except Exception as e:
        logger.error(f"Error generating digest: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Failed to generate news digest: {e}")


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /search <topic> command."""
    if not context.args:
        await update.message.reply_text("⚠️ Please provide a query, e.g.: <code>/search reasoning models</code>", parse_mode=ParseMode.HTML)
        return
    
    query = " ".join(context.args)
    status_msg = await update.message.reply_text(f"🔍 Searching news for <b>'{query}'</b>...", parse_mode=ParseMode.HTML)
    
    try:
        results = search_news_tool.invoke({"query": query})
        await status_msg.delete()
        await send_formatted_message(update, f"📰 <b>Search Results for '{query}':</b>\n\n{results}")
    except Exception as e:
        logger.error(f"Error in search command: {e}")
        await status_msg.edit_text(f"❌ Search error: {e}")


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /clear command to reset conversational memory."""
    await update.message.reply_text("🧹 <b>Memory refreshed!</b> Starting a new conversation context.", parse_mode=ParseMode.HTML)


async def handle_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handler for all user text messages.
    - If user explicitly sends a standalone 'more news' / 'daily digest' phrase without topic, triggers general digest.
    - Otherwise, routes to LangGraph Agent which uses search tools to answer specifically about the topic requested!
    """
    chat_id = update.effective_chat.id
    user_text = (update.message.text or "").strip()
    norm_text = re.sub(r"[^\w\s]", "", user_text.lower()).strip()
    
    # 1. Standalone general digest request (strictly without specific topic)
    if norm_text in STANDALONE_DIGEST_PHRASES:
        logger.info(f"Triggering general digest for standalone phrase: '{norm_text}'")
        status_msg = await update.message.reply_text("🔄 <i>Digging deeper to find newer, unread stories for you...</i>", parse_mode=ParseMode.HTML)
        try:
            newsletter = generate_newsletter(chat_id=chat_id)
            await status_msg.delete()
            await send_formatted_message(update, newsletter)
            return
        except Exception as e:
            logger.error(f"Error generating more news: {e}", exc_info=True)
            await status_msg.edit_text(f"⚠️ Could not fetch more news: {e}")
            return

    # 2. Conversational Q&A / Targeted topic request
    await update.effective_chat.send_action("typing")
    try:
        reply = chat_with_agent(chat_id=chat_id, user_message=user_text)
        await send_formatted_message(update, reply, reply_to_message=True)
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        await update.message.reply_text(f"⚠️ Encountered an error: {e}")
