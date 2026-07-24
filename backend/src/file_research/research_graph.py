from typing import Annotated, TypedDict
import operator
import openai
from pydantic import SecretStr
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langchain_core.messages import SystemMessage, AIMessage
import structlog
from src.resilience import safe_ainvoke, LLM_RETRY_POLICY, ainvoke_with_context_recovery

from src.config import settings
from src.file_research.retriever import (
    search_document_by_grep,
    search_document_by_vector,
)
from src.graph import checkpointer
from src.tools import search_web

logger = structlog.get_logger()

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
    degraded: bool
    errors: Annotated[list[dict], operator.add]

llm = ChatOpenAI(
    model="deepseek-v4-pro",
    api_key=SecretStr(settings.DEEPSEEK_API_KEY),
    base_url=settings.DEEPSEEK_BASE_URL,
    streaming=True,
    timeout=settings.LLM_TIMEOUT,
    max_retries=settings.LLM_MAX_ATTEMPTS
)

flash_llm = ChatOpenAI(
        model="deepseek-v4-flash",
        api_key=SecretStr(settings.DEEPSEEK_API_KEY),
        base_url=settings.DEEPSEEK_BASE_URL,
        streaming=True,
        timeout=settings.LLM_TIMEOUT,
        max_retries=settings.LLM_MAX_ATTEMPTS,
)

research_llm = llm.bind_tools(research_tools)
writer_llm = llm.with_fallbacks(
    [flash_llm],
    exceptions_to_handle=(
        openai.RateLimitError,
        openai.InternalServerError,
        openai.APITimeoutError,
        openai.APIConnectionError
    ),
)

async def researcher_node(state: ResearchState) -> dict:
    """ 回复消息，但是不会写文件 """
    try:
        messages = [SystemMessage(content=RESEARCH_PROMPT)] + state["messages"]
        response = await ainvoke_with_context_recovery(research_llm, messages)
        return {"messages": [response]}
    except Exception as e:
        return {"errors": [{"node": "researcher", "error": str(e), "type": type(e).__name__}]}

async def writer_node(state: ResearchState) -> dict:
    """ 用户写文件，但是不会回复用户的消息 """
    messages = [SystemMessage(content=WRITER_PROMPT)] + state["messages"]
    response = await ainvoke_with_context_recovery(writer_llm, messages)
    return {"messages": [response],
            "report_md": response.content,
            "degraded": False}

def _build_degraded_report(state: ResearchState) -> str:
    """ B6 降级: writer 失败时， 把 researcher 的原始情报 (AIMessage 内容) 拼成报告降级 """
    msgs = state.get("messages", [])
    intel = [m.content for m in msgs if isinstance(m, AIMessage) and m.content]
    body = "\n\n---\n\n".join(intel) if intel else "(情报专家未产出可用素材)"
    return (
        "> ⚠️ 本报告为降级输出：撰写模型多次重试失败，"
        "以下为情报专家收集的原始素材，未经排版润色。\n\n" + body
    )

async def writer_error_handler(state: ResearchState) -> dict:
    """ writer 重试耗尽后的兜底: 不调 LLM (它会一起挂), 纯拼接原始情报降级。"""
    logger.warning("writer_degraded", intel_count=sum(1 for m in state.get("messages", []) if isinstance(m, AIMessage)))
    report = _build_degraded_report(state)
    return {
        "report_md": report,
        "degraded": True,
        "messages" : [AIMessage(content=report)], # 镜像 writer_node 的返回形状，保持历史完整
        "errors": [{"node": "writer", "error": "撰写节点失败，已执行原始情报合并降级"}]
    }

def should_continue(state: ResearchState) -> str:
    if state.get("errors"):
        return "writer"
    messages = state["messages"]
    tool_count = sum(1 for m in messages if hasattr(m, 'type') and m.type == 'tool')
    if tool_count >= 20:
        return "writer"

    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"

    return "writer"

workflow = StateGraph(ResearchState)
workflow.add_node("researcher", researcher_node, retry_policy=LLM_RETRY_POLICY)
workflow.add_node("writer", writer_node, retry_policy=LLM_RETRY_POLICY, error_handler=writer_error_handler)
workflow.add_node("tools", tool_node)

workflow.set_entry_point("researcher")

workflow.add_conditional_edges("researcher", should_continue)
workflow.add_edge("tools", "researcher")
workflow.add_edge("writer", END)

research_app = workflow.compile(checkpointer=checkpointer)
