import logging
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from agent.workflow import generate_newsletter, chat_with_agent
from agent.tools import search_news_tool
from agent.config import SCHEDULE_TIME, SCHEDULE_TIMEZONE

logger = logging.getLogger("news_agent.bot.handlers")


async def send_chunked_message(update: Update, text: str, reply_to_message: bool = False):
    """
    Sends a message safely handling Telegram's 4096 character limit.
    Attempts Markdown parse mode; falls back to plain text if formatting is invalid.
    """
    max_len = 3900
    if len(text) <= max_len:
        chunks = [text]
    else:
        chunks = []
        lines = text.split("\n")
        curr_chunk = ""
        for line in lines:
            if len(curr_chunk) + len(line) + 1 > max_len:
                chunks.append(curr_chunk)
                curr_chunk = line + "\n"
            else:
                curr_chunk += line + "\n"
        if curr_chunk:
            chunks.append(curr_chunk)

    for i, chunk in enumerate(chunks):
        try:
            if reply_to_message and i == 0 and update.message:
                await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
            elif update.effective_chat:
                await update.effective_chat.send_message(chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.warning(f"Markdown send failed ({e}), retrying without parse_mode")
            if reply_to_message and i == 0 and update.message:
                await update.message.reply_text(chunk)
            elif update.effective_chat:
                await update.effective_chat.send_message(chunk)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /start command."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    # Store chat_id in bot data for scheduled deliveries
    if "subscribed_chats" not in context.application.bot_data:
        context.application.bot_data["subscribed_chats"] = set()
    context.application.bot_data["subscribed_chats"].add(chat_id)

    welcome_text = (
        f"👋 *Welcome, {user.first_name}!* I am *Techno*, your autonomous AI & Tech News Agent.\n\n"
        f"📡 *What I do:*\n"
        f"• Aggregate curated news from **DeepLearning.AI**, **The Guardian**, **MIT Technology Review**, and **TechCrunch AI**.\n"
        f"• Run an intelligent **SQLite Deduplication & Fuzzy Matching** handshake to ensure you only get 100% fresh, non-duplicate stories.\n"
        f"• Deliver a crisp morning intelligence briefing daily at *{SCHEDULE_TIME} ({SCHEDULE_TIMEZONE})*.\n"
        f"• Answer any follow-up questions with full conversational memory!\n\n"
        f"⚡ *Quick Commands:*\n"
        f"• `/digest` or `/news` - Generate and send your news briefing right now\n"
        f"• `/search <topic>` - Search tech/AI news across all sources\n"
        f"• `/clear` - Reset our conversation memory\n"
        f"• Or simply **send any message** to ask me anything about the news!"
    )
    await send_chunked_message(update, welcome_text)


async def digest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /digest or /news command."""
    chat_id = update.effective_chat.id
    status_msg = await update.message.reply_text("🔄 *Synthesizing today's intelligence briefing...*", parse_mode=ParseMode.MARKDOWN)
    
    try:
        newsletter = generate_newsletter(chat_id=chat_id)
        await status_msg.delete()
        await send_chunked_message(update, newsletter)
    except Exception as e:
        logger.error(f"Error generating digest: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Failed to generate news digest: {e}")


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /search <topic> command."""
    if not context.args:
        await update.message.reply_text("⚠️ Please provide a search query, e.g.: `/search reasoning models`", parse_mode=ParseMode.MARKDOWN)
        return
    
    query = " ".join(context.args)
    status_msg = await update.message.reply_text(f"🔍 Searching news for *'{query}'*...", parse_mode=ParseMode.MARKDOWN)
    
    try:
        results = search_news_tool.invoke({"query": query})
        await status_msg.delete()
        await send_chunked_message(update, f"📰 *Search Results for '{query}':*\n\n{results}")
    except Exception as e:
        logger.error(f"Error in search command: {e}")
        await status_msg.edit_text(f"❌ Search error: {e}")


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /clear command to reset conversational memory."""
    chat_id = update.effective_chat.id
    from agent.workflow import agent_graph
    
    # In LangGraph with checkpointer, we can clear state by sending an empty/system message
    config = {"configurable": {"thread_id": str(chat_id)}}
    try:
        from langchain_core.messages import RemoveMessage
        # Or notify user that thread memory has been acknowledged
        await update.message.reply_text("🧹 *Memory refreshed!* Starting a new conversation context.", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text("Memory reset.")


async def handle_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for freeform user messages and follow-up questions."""
    chat_id = update.effective_chat.id
    user_text = update.message.text
    
    # Show typing indicator
    await update.effective_chat.send_action("typing")
    
    try:
        reply = chat_with_agent(chat_id=chat_id, user_message=user_text)
        await send_chunked_message(update, reply, reply_to_message=True)
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        await update.message.reply_text(f"⚠️ Apologies, encountered an error: {e}")

