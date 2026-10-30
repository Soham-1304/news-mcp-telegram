import os
import sqlite3
import logging
from datetime import datetime
from typing import Annotated, Sequence, TypedDict, Dict, Any, List

from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.sqlite import SqliteSaver

from agent.config import (
    GROQ_API_KEY,
    DEFAULT_MODEL,
    MEMORY_DB_PATH
)
from agent.prompts import NEWSLETTER_PROMPT, CHAT_SYSTEM_PROMPT
from agent.tools import (
    AGENT_TOOLS,
    get_fresh_articles_for_digest,
    record_delivered_articles
)

logger = logging.getLogger("news_agent.workflow")

# -----------------------------------------------------------------------------
# 1. State Definition
# -----------------------------------------------------------------------------
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]


# -----------------------------------------------------------------------------
# 2. LLM Setup with Priority: 20b -> 27b -> 120b (Ultra-resilient)
# -----------------------------------------------------------------------------
def get_resilient_llm(max_tokens: int = 1024):
    primary_20b = ChatGroq(
        api_key=GROQ_API_KEY,
        model="openai/gpt-oss-20b",
        temperature=0.3,
        max_tokens=max_tokens,
        max_retries=0
    )
    fallback_qwen = ChatGroq(
        api_key=GROQ_API_KEY,
        model="qwen/qwen3.8-27b",
        temperature=0.3,
        max_tokens=max_tokens,
        max_retries=0
    )
    fallback_120b = ChatGroq(
        api_key=GROQ_API_KEY,
        model="openai/gpt-oss-120b",
        temperature=0.3,
        max_tokens=max_tokens,
        max_retries=0
    )

    return primary_20b.with_fallbacks([fallback_qwen, fallback_120b])


llm = get_resilient_llm(max_tokens=1024)
llm_with_tools = llm.bind_tools(AGENT_TOOLS)


# -----------------------------------------------------------------------------
# 3. Graph Nodes
# -----------------------------------------------------------------------------
def clean_messages_for_llm(messages: Sequence[BaseMessage]) -> List[BaseMessage]:
    """
    Safely sanitizes conversational history for Groq/OpenAI tool calling:
    1. Anchors to the last user HumanMessage.
    2. Keeps previous turn's text exchange (if present) for conversational continuity.
    3. Keeps tool calls paired with their matching ToolMessages.
    4. Truncates tool content to 1,200 chars to prevent 413 Payload Too Large / 429 TPM limits.
    5. Guarantees ToolMessage always has valid name attribute to prevent 'Tools should have a name' error.
    """
    if not messages:
        return []

    # Find the last HumanMessage
    last_human_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], HumanMessage):
            last_human_idx = i
            break

    if last_human_idx == -1:
        last_human_idx = 0

    # Collect previous turn's pure text messages (no tool dumps) for context
    context_msgs: List[BaseMessage] = []
    if last_human_idx > 0:
        prev_slice = messages[max(0, last_human_idx - 3):last_human_idx]
        for m in prev_slice:
            if isinstance(m, HumanMessage):
                context_msgs.append(m)
            elif isinstance(m, AIMessage) and m.content and not getattr(m, "tool_calls", None):
                context_msgs.append(m)

    # Active turn from last HumanMessage onwards
    active_slice = list(messages[last_human_idx:])
    human_msg = active_slice[0]
    cleaned = context_msgs + [human_msg]

    # Process tool exchanges in the active turn
    pending_tool_call_ids = set()
    for msg in active_slice[1:]:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            cleaned.append(msg)
            pending_tool_call_ids = {tc["id"] for tc in msg.tool_calls}
        elif isinstance(msg, ToolMessage):
            if getattr(msg, "tool_call_id", None) in pending_tool_call_ids:
                cleaned.append(ToolMessage(
                    content=str(msg.content)[:1200],
                    tool_call_id=msg.tool_call_id,
                    name=getattr(msg, "name", None) or "search_news_tool"
                ))
                pending_tool_call_ids.discard(msg.tool_call_id)
        elif isinstance(msg, AIMessage) and msg.content:
            cleaned.append(msg)
            pending_tool_call_ids = set()

    return cleaned


def call_model(state: AgentState) -> Dict[str, Any]:
    raw_messages = list(state["messages"])
    cleaned_history = clean_messages_for_llm(raw_messages)
    
    # Always prepend SystemMessage
    messages = [SystemMessage(content=CHAT_SYSTEM_PROMPT)] + [
        m for m in cleaned_history if not isinstance(m, SystemMessage)
    ]
    
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


# -----------------------------------------------------------------------------
# 4. Compile StateGraph with SQLite Memory Checkpointer
# -----------------------------------------------------------------------------
def build_agent_graph():
    os.makedirs(os.path.dirname(MEMORY_DB_PATH), exist_ok=True)
    db_conn = sqlite3.connect(MEMORY_DB_PATH, check_same_thread=False)
    checkpointer = SqliteSaver(db_conn)
    checkpointer.setup()

    builder = StateGraph(AgentState)
    builder.add_node("agent", call_model)
    builder.add_node("tools", ToolNode(AGENT_TOOLS))

    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")

    return builder.compile(checkpointer=checkpointer), checkpointer


agent_graph, memory_checkpointer = build_agent_graph()


# -----------------------------------------------------------------------------
# 5. High-Level Agent API (Token-Optimized to prevent 429 Rate Limits)
# -----------------------------------------------------------------------------
def generate_newsletter(chat_id: int = None, limit_per_source: int = 4, **kwargs) -> str:
    """
    Executes daily news briefing:
    1. Runs progressive crawl loop with SQLite deduplication.
    2. Selects top 5-6 fresh, unread articles with condensed snippets (<1000 tokens).
    3. Synthesizes a structured morning newsletter without exhausting TPM limits.
    4. Commits delivered articles to SQLite.
    """
    logger.info(f"Generating newsletter for chat_id={chat_id}")
    
    fresh_articles, rejected = get_fresh_articles_for_digest(chat_id=chat_id, limit_per_source=limit_per_source)
    
    if not fresh_articles:
        return (
            "✨ <b>All Caught Up!</b>\n\n"
            "You have already received the latest news from In The World of AI, DeepLearning.AI, The Guardian, "
            "MIT Technology Review, and TechCrunch AI.\n\n"
            "Our deduplication filter prevented repeating any previously delivered stories.\n"
            "Feel free to ask me questions about today's earlier news or use <code>/reset_history</code> to test from scratch!"
        )

    # Ensure we have at least 5 distinct articles to populate all newsletter sections cleanly
    selected_articles = list(fresh_articles[:6])
    if len(selected_articles) < 5:
        seen_urls = {a["url"] for a in selected_articles}
        for r in rejected:
            if r.get("url") and r["url"] not in seen_urls:
                selected_articles.append(r)
                seen_urls.add(r["url"])
                if len(selected_articles) >= 5:
                    break

    articles_text = []
    for i, a in enumerate(selected_articles, 1):
        clean_summary = (a.get("summary") or "").strip()[:240]
        articles_text.append(
            f"[{i}] Title: {a['title']}\n"
            f"    Source: {a['source']} | Author: {a.get('writer', 'Staff')}\n"
            f"    URL: {a['url']}\n"
            f"    Summary: {clean_summary}...\n"
        )
    
    current_date = datetime.now().strftime("%B %d, %Y")
    formatted_prompt = NEWSLETTER_PROMPT.format(
        current_date=current_date,
        articles_text="\n".join(articles_text)
    )

    compiler_llm = get_resilient_llm(max_tokens=3500)
    response = compiler_llm.invoke([
        SystemMessage(content="You are a professional AI news editor. Output clean, high-signal Telegram newsletter text."),
        HumanMessage(content=formatted_prompt)
    ])
    newsletter_text = response.content

    record_delivered_articles(selected_articles, chat_id=chat_id)

    if chat_id:
        config = {"configurable": {"thread_id": str(chat_id)}}
        # Efficiently save delivery memory directly into checkpointer without triggering an extra LLM call
        delivered_titles = ", ".join([f"'{a['title']}'" for a in selected_articles[:4]])
        agent_graph.update_state(
            config,
            {
                "messages": [
                    AIMessage(content=f"Delivered morning digest on {current_date} covering: {delivered_titles}.")
                ]
            },
            as_node="agent"
        )

    return newsletter_text


def chat_with_agent(chat_id: int, user_message: str) -> str:
    """
    Handles user chat, topic queries, and follow-ups with full conversational memory.
    Resets thread state automatically if invalid/corrupt state is detected.
    """
    config = {"configurable": {"thread_id": str(chat_id)}}
    inputs = {"messages": [HumanMessage(content=user_message)]}
    
    try:
        result = agent_graph.invoke(inputs, config=config)
        messages = result.get("messages", [])
        
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                return msg.content
                
        return "I searched today's news feeds, but found no matching reports. What specific topic would you like to explore?"
    except Exception as e:
        logger.error(f"Error in chat_with_agent for {chat_id}: {e}", exc_info=True)
        # Auto-recover by clearing corrupted checkpointer state
        try:
            conn = sqlite3.connect(MEMORY_DB_PATH)
            with conn:
                conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (str(chat_id),))
                conn.execute("DELETE FROM writes WHERE thread_id = ?", (str(chat_id),))
            conn.close()
        except Exception:
            pass
        raise e
