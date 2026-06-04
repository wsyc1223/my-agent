from src.config import settings
from langchain_openai import ChatOpenAI
from langchain_core.runnables import RunnableLambda
from typing import Annotated, TypedDict
from langgraph.prebuilt import ToolNode
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from src.tools import tools
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

DATABASE_URL_PSYCOPG = settings.DATABASE_URL_PSYCOPG
pool = AsyncConnectionPool(
    conninfo=DATABASE_URL_PSYCOPG,
    max_size=20,
    open=False,
    kwargs={
        "autocommit": True,
        "row_factory": dict_row,
    }
)

llm = ChatOpenAI(
    model = "deepseek-chat",
    api_key = settings.DEEPSEEK_API_KEY,
    base_url = settings.DEEPSEEK_BASE_URL,
    streaming=True,
)

llm_with_tools = llm.bind_tools(tools)

tool_node = ToolNode(tools)

class State(TypedDict):
    messages: Annotated[list, add_messages]

def should_continue(state: State):
    """判断是否需要继续调用模型，主要根据当前消息列表中是否包含工具调用的结果来决定。"""
    messages = state["messages"]
    tool_count = sum(1 for m in messages if hasattr(m, 'type') and m.type == 'tool')
    if tool_count >= 100:
        return END

    last_message = messages[-1]
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        return "tools"
    return END

workflow = StateGraph(State)
agent_node = RunnableLambda(lambda state: state["messages"]) | llm_with_tools | RunnableLambda(lambda msg: {"messages": [msg]})
workflow.add_node("agent", agent_node)
workflow.add_node("tools", tool_node)
workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", should_continue)
workflow.add_edge("tools", "agent")

checkpointer = AsyncPostgresSaver(pool)
app = workflow.compile(checkpointer=checkpointer, interrupt_before=["tools"])


