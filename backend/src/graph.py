from src.config import settings
from pydantic import SecretStr
from langchain_openai import ChatOpenAI
from langchain_core.runnables import RunnableLambda
from typing import Annotated, TypedDict
from langgraph.prebuilt import ToolNode
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from src.tools import tools
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from src.resilience import safe_ainvoke, LLM_RETRY_POLICY, ainvoke_with_context_recovery
from psycopg.rows import dict_row
import operator

# 数据库连接池
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
    model = "deepseek-v4-flash",
    api_key = SecretStr(settings.DEEPSEEK_API_KEY),
    base_url = settings.DEEPSEEK_BASE_URL,
    streaming=True,
    timeout=settings.LLM_TIMEOUT,
    max_retries=settings.LLM_MAX_ATTEMPTS,
)

llm_with_tools = llm.bind_tools(tools)

tool_node = ToolNode(tools)

class State(TypedDict):
    messages: Annotated[list, add_messages]
    errors: Annotated[list[dict], operator.add]

def should_continue(state: State):
    """判断是否需要继续调用模型，主要根据当前消息列表中是否包含工具调用的结果来决定。"""
    if state.get("errors"):
        return END

    messages = state["messages"]
    tool_count = sum(1 for m in messages if hasattr(m, 'type') and m.type == 'tool')
    if tool_count >= 100:
        return END

    last_message = messages[-1]
    if hasattr(last_message, 'tool_calls') and last_message.tool_calls:
        return "tools"
    return END

async def agent_node(state: State) -> State:
    """
    Agent 决策节点: 调用 LLM 生成下一步动作(或工具调用),
    捕获重试耗尽后非正常退出
    """
    try:
        response = await ainvoke_with_context_recovery(llm_with_tools, state["messages"])
        return {"messages": [response]}
    except Exception as e:
        return {"errors": [{"node": "agent", "error": str(e), "type": type(e).__name__}]}

workflow = StateGraph(State)
workflow.add_node("agent", agent_node, retry_policy=LLM_RETRY_POLICY)
workflow.add_node("tools", tool_node)
workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", should_continue)
workflow.add_edge("tools", "agent")

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.postgres.base import BasePostgresSaver

class LazyAsyncPostgresSaver(AsyncPostgresSaver):
    def __init__(self, conn, pipe=None, serde=None):
        # 初始化基类的序列化器，防止导入阶段或早期配置访问报错
        BasePostgresSaver.__init__(self, serde=serde)
        self.conn_lazy = conn
        self.pipe_lazy = pipe
        self.serde_lazy = serde
        self._initialized = False

    def _ensure_initialized(self):
        if not self._initialized:
            # 只有在真正需要执行数据库交互时（此时必然在运行中的事件循环中），才安全地调用父类初始化
            super().__init__(self.conn_lazy, pipe=self.pipe_lazy, serde=self.serde_lazy)
            self._initialized = True

    async def get_tuple(self, config):
        self._ensure_initialized()
        return await super().get_tuple(config)

    async def list(self, config, *, filter=None, before=None, limit=None):
        self._ensure_initialized()
        return await super().list(config, filter=filter, before=before, limit=limit)

    async def put(self, config, checkpoint, metadata, new_versions):
        self._ensure_initialized()
        return await super().put(config, checkpoint, metadata, new_versions)

    async def put_writes(self, config, writes, task_id):
        self._ensure_initialized()
        return await super().put_writes(config, writes, task_id)

    async def setup(self):
        self._ensure_initialized()
        return await super().setup()

checkpointer = LazyAsyncPostgresSaver(pool)
app = workflow.compile(checkpointer=checkpointer, interrupt_before=["tools"])
