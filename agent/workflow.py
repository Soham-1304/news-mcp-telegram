import os
import sqlite3
import logging
from datetime import datetime
from typing import Annotated, Sequence, TypedDict, Dict, Any, List

from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage, AIMessage
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
# 2. LLM & Tools Setup
# -----------------------------------------------------------------------------
def get_llm():
    return ChatGroq(
        api_key=GROQ_API_KEY,
        model=DEFAULT_MODEL,
        temperature=0.3
    )

llm = get_llm()
llm_with_tools = llm.bind_tools(AGENT_TOOLS)


# -----------------------------------------------------------------------------
# 3. Graph Nodes
# -----------------------------------------------------------------------------
def call_model(state: AgentState) -> Dict[str, Any]:
    messages = state["messages"]
    # If first message is not a system message, prepend CHAT_SYSTEM_PROMPT
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=CHAT_SYSTEM_PROMPT)] + list(messages)
    
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


# Global compiled graph
agent_graph, memory_checkpointer = build_agent_graph()


# -----------------------------------------------------------------------------
# 5. High-Level Agent API
# -----------------------------------------------------------------------------
def generate_newsletter(chat_id: int = None, force_refresh: bool = False) -> str:
    """
    Executes the daily news briefing handshake:
    1. Fetches raw news from DeepLearning.AI, The Guardian, MIT, TechCrunch.
    2. Runs Deduplication & Freshness filtering against SQLite (exact + metadata + fuzzy).
    3. Synthesizes a structured morning newsletter with LLM.
    4. Commits delivered articles to SQLite to prevent future duplication.
    5. Injects the newsletter into the user's LangGraph conversation memory for seamless follow-up questions.
    """
    logger.info(f"Generating newsletter for chat_id={chat_id} (force_refresh={force_refresh})")
    
    fresh_articles, rejected = get_fresh_articles_for_digest(chat_id=chat_id, limit_per_source=4)
    
    if not fresh_articles:
        return (
            "✨ *All Caught Up!*\n\n"
            "You have already received the latest news from DeepLearning.AI, The Guardian, "
            "MIT Technology Review, and TechCrunch AI within the last 48 hours.\n\n"
            "Our deduplication filter prevented repeating any previously delivered stories.\n"
            "Feel free to ask me questions about today's earlier news or use `/news <topic>` to explore specific topics!"
        )

    # Format articles for prompt
    articles_text = []
    for i, a in enumerate(fresh_articles, 1):
        articles_text.append(
            f"[{i}] Title: {a['title']}\n"
            f"    Source: {a['source']} | Author: {a.get('writer', 'Staff')}\n"
            f"    Published: {a.get('published_at', 'Recent')} | Category: {a.get('topic', 'AI')}\n"
            f"    URL: {a['url']}\n"
            f"    Summary: {a.get('summary', '')}\n"
        )
    
    current_date = datetime.now().strftime("%B %d, %Y")
    formatted_prompt = NEWSLETTER_PROMPT.format(
        current_date=current_date,
        articles_text="\n".join(articles_text)
    )

    # Invoke LLM for synthesis
    compiler_llm = get_llm()
    response = compiler_llm.invoke([
        SystemMessage(content="You are a professional AI news editor. Output crisp, high-signal Telegram newsletter text."),
        HumanMessage(content=formatted_prompt)
    ])
    newsletter_text = response.content

    # Commit sent articles to SQLite database
    record_delivered_articles(fresh_articles, chat_id=chat_id)

    # Inject into LangGraph memory state so user can ask follow-up questions
    if chat_id:
        config = {"configurable": {"thread_id": str(chat_id)}}
        agent_graph.invoke(
            {
                "messages": [
                    HumanMessage(content="Here is today's morning newsletter digest that was sent to the user."),
                    AIMessage(content=newsletter_text)
                ]
            },
            config=config
        )

    return newsletter_text


def chat_with_agent(chat_id: int, user_message: str) -> str:
    """
    Handles user chat and follow-up questions with full conversational memory.
    """
    config = {"configurable": {"thread_id": str(chat_id)}}
    inputs = {"messages": [HumanMessage(content=user_message)]}
    
    result = agent_graph.invoke(inputs, config=config)
    messages = result.get("messages", [])
    
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            return msg.content
            
    return "I processed your request, but have no additional output. How else can I assist you with the news?"

