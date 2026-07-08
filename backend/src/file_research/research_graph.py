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

RESEARCH_PROMPT="""你是一个情报专家，专门负责检索和分析文档与网络信息。
请通过调用检索工具来收集完整的情报。查完资料后，请在回复中明确说“交给撰稿人”。

【重要指令】:
在调用 search_document_by_vector 或 search_document_by_grep 工具时，如果用户的提问或当前指令中包含代词（如“它”、“这个文件”、“那个报错”），你必须在调用工具前根据对话上下文进行【指代消解】，将代词还原为具体的主题词、文件名或函数名，再填充进工具的 query 参数中。绝不能直接用代词作为检索 query。
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
    return {"messages": [response],
            "report_md": response.content}

def should_continue(state: ResearchState) -> str:
    messages = state["messages"]
    tool_count = sum(1 for m in messages if hasattr(m, 'type') and m.type == 'tool')
    if tool_count >= 20:
        return "writer"

    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"

    # 如果最后一条消息没有触发任何工具调用，且整场会话中从未发生过检索，说明是闲聊，直接体面结束
    if tool_count == 0:
        return END

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
