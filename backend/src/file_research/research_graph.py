from typing import Annotated, TypedDict
import operator
from pydantic import SecretStr
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.messages import SystemMessage

from src.config import settings
from src.file_research.retriever import (
    search_document_by_grep,
    search_document_by_vector,
)
from src.graph import checkpointer
from src.tools import search_web

# 工具集
research_tools = [
    search_document_by_grep,
    search_document_by_vector,
    search_web
]
tool_node = ToolNode(research_tools)

RESEARCH_PROMPT="""
    你是一个情报专家，只需要查找资料，不需要写长篇报告，查完就说'交给撰稿人'。
"""
WRITER_PROMPT="""
    你是一个排版专家，不用查资料，直接看前面的聊天记录，写出一篇精美的 Markdown 报告正文。
"""

# 如果是追加文件，就把新旧文件合并，set 去重
def merge_files(left: list[str] | None, right: list[str] | None) -> list[str]:
    if not left: left = []
    if not right: right = []
    return list(set(left + right))

# 全局状态
class ResearchState(TypedDict):
    messages: Annotated[list, add_messages]
    report_md: str
    file_ids: Annotated[list[str], merge_files]

llm = ChatOpenAI(
    model="deepseek-v4-pro",
    api_key=SecretStr(settings.DEEPSEEK_API_KEY),
    base_url=settings.DEEPSEEK_BASE_URL,
    streaming=True
)
research_llm = llm.bind_tools(research_tools)
writer_llm = llm

async def researcher_node(state: ResearchState) -> dict:
    """ 用户回复用户的消息，但是不会写文件 """
    messages = [SystemMessage(content=RESEARCH_PROMPT)] + state["messages"]
    response = await research_llm.ainvoke(messages)
    return {"messages": [response]}

async def writer_node(state: ResearchState) -> dict:
    """ 用户写文件，但是不会回复用户的消息 """
    messages = [SystemMessage(content=WRITER_PROMPT)] + state["messages"]
    response = await writer_llm.ainvoke(messages)
    return {"messages": [response]}

def should_continue(state: ResearchState) -> str:
    messages = state["messages"]
    tool_count = sum(1 for m in messages if hasattr(m, 'type') and m.type == 'tool')
    if tool_count >= 20:
        return "writer"

    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"

    return "writer"

workflow = StateGraph(ResearchState)
workflow.add_node("researcher", researcher_node)
workflow.add_node("writer", writer_node)
workflow.add_node("tools", tool_node)

workflow.set_entry_point("researcher")

workflow.add_conditional_edges("researcher", should_continue)
workflow.add_edge("tools", "researcher")
workflow.add_edge("writer", END)

research_app = workflow.compile(checkpointer=checkpointer)
