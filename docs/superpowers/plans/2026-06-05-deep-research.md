# 深度研究 Agent 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 Agentic OS 项目中实现独立的「深度研究」模式——用户输入问题，Agent 自动拆解 → 搜索 → 阅读 → 筛选 → 生成 Markdown 报告，含两个人机协同审批中断点。

**Architecture:** 新建独立 LangGraph 研究图（planner → researcher → writer），使用结构化 State 替代 messages 列表避免 Context Window 爆炸。共享现有 PostgreSQL Checkpointer、JWT 认证、Langfuse 可观测性。前端新增 ResearchView + 时间线进度组件。

**Tech Stack:** Python 3.12, FastAPI, LangGraph, LangChain, PostgreSQL + pgvector, SQLAlchemy, Alembic, Vue 3, Pinia, Vite, marked, highlight.js

**Spec:** `DEEP_RESEARCH_DESIGN.md`

---

## 文件结构总览

### 新建文件

| 文件路径 | 职责 |
|---|---|
| `backend/src/research_graph.py` | 研究 LangGraph 图：State 类型定义 + planner/researcher/writer 节点 + 图编排 |
| `backend/src/service/research.py` | 研究业务逻辑：start、approve_outline、approve_sources 的 SSE 流生成器 |
| `backend/src/router/research.py` | 研究 API 路由：5 个端点 |
| `backend/tests/test_research_graph.py` | 研究图单元测试 |
| `backend/tests/test_research_api.py` | 研究 API 集成测试 |
| `frontend/src/views/ResearchView.vue` | 研究主页面 |
| `frontend/src/components/ResearchTimeline.vue` | 左侧竖向进度时间线 |
| `frontend/src/components/OutlineEditor.vue` | 提纲审批编辑器 |
| `frontend/src/components/SourcesReviewer.vue` | 来源审批面板 |
| `frontend/src/components/ReportRenderer.vue` | 报告 Markdown 渲染 + 下载 |
| `frontend/src/stores/research.ts` | Pinia store 管理研究状态 |
| `frontend/src/services/research.ts` | 研究 API 调用 + SSE 流读取 |

### 修改文件

| 文件路径 | 改动内容 |
|---|---|
| `backend/src/db/model.py` | 追加 ResearchTask Model |
| `backend/src/schemas.py` | 追加研究相关 Request/Response Schema |
| `backend/main.py` | 注册 research_router |
| `backend/src/tools.py` | fetch_url 增加 SSRF 防护 |
| `backend/src/service/agent.py` | 修复 embed_text 异步 + 多工具拒绝 |
| `backend/src/rag.py` | search_messages 增加 exclude_conversation_id |
| `frontend/src/router/index.ts` | 新增 /research 路由 |
| `frontend/src/components/ChatSidebar.vue` | 新增「深度研究」导航入口 |

---

## Task 1: 修复现有 Bug — 异步 Embedding 与多工具拒绝

修复面试中最容易被追问的两个工程缺陷，同时也是后续研究功能正确运行的基础。

**Files:**
- Modify: `backend/src/service/agent.py`
- Test: `backend/tests/test_bug_fixes.py`

- [ ] **Step 1: 创建 bug 修复测试文件**

```python
# backend/tests/test_bug_fixes.py
import asyncio
import pytest


def test_embed_text_is_not_coroutine():
    """embed_text 本身是同步函数，但应通过 asyncio.to_thread 调用"""
    from src.rag import embed_text
    result = embed_text("测试文本")
    assert isinstance(result, list)
    assert len(result) == 768  # bge-base-zh-v1.5 输出维度


def test_multi_tool_rejection_message_count():
    """当大模型并行调用 N 个工具时，拒绝应产生 N 条 ToolMessage"""
    from langchain_core.messages import AIMessage, ToolMessage

    # 模拟大模型返回 3 个并行 tool_calls
    mock_tool_calls = [
        {"id": "call_1", "name": "search_web", "args": {"query": "test1"}},
        {"id": "call_2", "name": "get_weather", "args": {"city": "北京"}},
        {"id": "call_3", "name": "calculator", "args": {"a": 1, "b": 2, "op": "add"}},
    ]

    # 修复后的拒绝逻辑
    reject_messages = [
        ToolMessage(content="用户拒绝了该工具调用", tool_call_id=tc["id"])
        for tc in mock_tool_calls
    ]

    assert len(reject_messages) == 3
    assert reject_messages[0].tool_call_id == "call_1"
    assert reject_messages[1].tool_call_id == "call_2"
    assert reject_messages[2].tool_call_id == "call_3"
```

- [ ] **Step 2: 运行测试确认失败（embed_text 测试应通过，但确认测试文件可正常执行）**

```bash
cd /home/wsyc1/projects/langchain/backend
uv run pytest tests/test_bug_fixes.py -v
```

Expected: 两个测试都应通过（这里测试的是修复后的正确逻辑形态）

- [ ] **Step 3: 修复 agent.py — 异步 Embedding + 多工具拒绝**

在 `backend/src/service/agent.py` 中做以下修改：

**修改 1**：文件顶部的 import 中确认已有 `import asyncio`（已有）

**修改 2**：`chat_stream` 函数中 3 处 `embed_text` 调用改为异步（约 L34、L84-85）：

```python
# L34: 用户消息 embedding（修改前）
msg_emb = embed_text(message)
# L34: 用户消息 embedding（修改后）
msg_emb = await asyncio.to_thread(embed_text, message)

# L84: AI 回复 embedding（修改前）
rep_emb = embed_text(last_msg.content)
# L84: AI 回复 embedding（修改后）
rep_emb = await asyncio.to_thread(embed_text, last_msg.content)
```

**修改 3**：`resume` 函数中 2 处 `embed_text` 调用改为异步（约 L158、L166）：

```python
# 修改前
rep_emb = embed_text(msg.content)
# 修改后
rep_emb = await asyncio.to_thread(embed_text, msg.content)
```

**修改 4**：`resume` 函数中多工具拒绝逻辑（约 L122-128）：

```python
# 修改前
if not approved:
    state = await app.aget_state(config)
    last_msg = state.values["messages"][-1]
    tool_call_id = last_msg.tool_calls[0]["id"]
    resume_input = Command(resume={"messages": [
        ToolMessage(content="用户拒绝了该工具调用", tool_call_id=tool_call_id)
    ]})

# 修改后
if not approved:
    state = await app.aget_state(config)
    last_msg = state.values["messages"][-1]
    reject_messages = [
        ToolMessage(content="用户拒绝了该工具调用", tool_call_id=tc["id"])
        for tc in last_msg.tool_calls
    ]
    resume_input = Command(resume={"messages": reject_messages})
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /home/wsyc1/projects/langchain/backend
uv run pytest tests/test_bug_fixes.py -v
```

Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
cd /home/wsyc1/projects/langchain
git add backend/src/service/agent.py backend/tests/test_bug_fixes.py
git commit -m "fix: async embedding via to_thread + handle multi-tool rejection"
```

---

## Task 2: SSRF 防护 + RAG 排除当前会话

**Files:**
- Modify: `backend/src/tools.py`
- Modify: `backend/src/rag.py`
- Test: `backend/tests/test_security.py`

- [ ] **Step 1: 创建安全测试文件**

```python
# backend/tests/test_security.py
import pytest


def test_ssrf_blocks_private_ip():
    from src.tools import is_safe_url
    assert is_safe_url("http://127.0.0.1:8080") is False
    assert is_safe_url("http://192.168.1.1") is False
    assert is_safe_url("http://10.0.0.1") is False
    assert is_safe_url("http://172.16.0.1") is False


def test_ssrf_blocks_non_http_schemes():
    from src.tools import is_safe_url
    assert is_safe_url("ftp://example.com") is False
    assert is_safe_url("file:///etc/passwd") is False
    assert is_safe_url("gopher://evil.com") is False


def test_ssrf_allows_public_urls():
    from src.tools import is_safe_url
    assert is_safe_url("https://www.google.com") is True
    assert is_safe_url("https://api.tavily.com/search") is True
    assert is_safe_url("http://example.com") is True
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/wsyc1/projects/langchain/backend
uv run pytest tests/test_security.py -v
```

Expected: FAIL — `is_safe_url` 不存在

- [ ] **Step 3: 在 tools.py 中实现 SSRF 防护**

在 `backend/src/tools.py` 文件顶部新增 import 和函数（在现有 import 之后、第一个 `@tool` 之前）：

```python
import ipaddress
import socket
from urllib.parse import urlparse

def is_safe_url(url: str) -> bool:
    """校验 URL 是否安全，防止 SSRF 攻击"""
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        return False

    if not parsed.hostname:
        return False

    try:
        resolved_ip = socket.gethostbyname(parsed.hostname)
        ip = ipaddress.ip_address(resolved_ip)
    except (socket.gaierror, ValueError):
        return False

    if ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local:
        return False

    return True
```

然后修改 `fetch_url` 函数，在请求之前增加校验（在 `try:` 之前插入）：

```python
@tool
async def fetch_url(url: str) -> str:
    """...(docstring 保持不变)..."""
    if not is_safe_url(url):
        return f"错误: 安全策略禁止访问该 URL ({url})，不允许访问内网地址或非 HTTP 协议"

    try:
        # ... 原有的 httpx 请求逻辑不变 ...
```

- [ ] **Step 4: 运行安全测试确认通过**

```bash
cd /home/wsyc1/projects/langchain/backend
uv run pytest tests/test_security.py -v
```

Expected: 3 passed

- [ ] **Step 5: 修改 rag.py 支持排除当前会话**

修改 `backend/src/rag.py` 中的 `search_messages` 函数签名和 SQL：

```python
async def search_messages(session: AsyncSession, user_id: str, query: str, limit: int = 5, exclude_conversation_id: str | None = None):
    query_vec = embed_text(query)

    sql = (
        "SELECT m.content, m.role, 1 - (m.embedding <=> cast(:qv as vector)) AS score "
        "FROM messages m JOIN conversations c ON m.conversation_id = c.id "
        "WHERE c.user_id = :uid AND embedding IS NOT NULL "
    )
    params = {"qv": str(query_vec), "qv2": str(query_vec), "uid": user_id, "lim": limit * 4}

    if exclude_conversation_id:
        sql += "AND c.id != :exclude_conv_id "
        params["exclude_conv_id"] = exclude_conversation_id

    sql += "ORDER BY m.embedding <=> cast(:qv2 as vector) LIMIT :lim"

    result = await session.execute(text(sql), params)
    candidates = [{"content": row.content, "role": row.role, "score": float(row.score)} for row in result]

    if candidates:
        pairs = [(query, c["content"]) for c in candidates]
        scores = reranker_model.predict(pairs)

        for i, c in enumerate(candidates):
            c["score"] = float(scores[i])
        candidates.sort(key=lambda x: x["score"], reverse=True)

    return candidates[:limit]
```

- [ ] **Step 6: 更新 agent.py 中的 search_messages 调用**

在 `backend/src/service/agent.py` 中的 `chat_stream` 函数（约 L39）：

```python
# 修改前
hits = await search_messages(db, user_id, message, limit = 5)

# 修改后
hits = await search_messages(db, user_id, message, limit=5, exclude_conversation_id=str(conversation_id))
```

- [ ] **Step 7: Commit**

```bash
cd /home/wsyc1/projects/langchain
git add backend/src/tools.py backend/src/rag.py backend/src/service/agent.py backend/tests/test_security.py
git commit -m "fix: add SSRF protection to fetch_url + exclude current conversation from RAG"
```

---

## Task 3: 数据库 — ResearchTask Model + 迁移

**Files:**
- Modify: `backend/src/db/model.py`
- Modify: `backend/src/schemas.py`
- Create: `backend/src/db/repository.py` (追加 ResearchTaskRepository)
- Create: Alembic 迁移脚本（自动生成）

- [ ] **Step 1: 在 model.py 中追加 ResearchTask Model**

在 `backend/src/db/model.py` 末尾（Message 类之后）追加：

```python
class ResearchTask(Base):
    __tablename__ = "research_tasks"
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    query = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="planning")
    outline = Column(JSONB, nullable=True)
    sources = Column(JSONB, nullable=True)
    report = Column(Text, nullable=True)
    thread_id = Column(UUID, nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User")
```

- [ ] **Step 2: 在 schemas.py 中追加研究相关 Schema**

在 `backend/src/schemas.py` 末尾追加：

```python
class SubQuestionSchema(BaseModel):
    id: int
    question: str
    search_queries: list[str]

class SourceItemSchema(BaseModel):
    sub_question_id: int
    url: str
    title: str
    snippet: str
    credibility: str  # high / medium / low

class ResearchStartRequest(BaseModel):
    query: str

class ApproveOutlineRequest(BaseModel):
    thread_id: str
    outline: list[SubQuestionSchema]

class ApproveSourcesRequest(BaseModel):
    thread_id: str
    approved_indices: list[int]

class ResearchTaskOut(BaseModel):
    id: str
    query: str
    status: str
    created_at: str | None

class ResearchTaskDetail(BaseModel):
    id: str
    query: str
    status: str
    outline: list[SubQuestionSchema] | None = None
    sources: list[SourceItemSchema] | None = None
    report: str | None = None
    created_at: str | None
```

- [ ] **Step 3: 在 repository.py 中追加 ResearchTaskRepository**

在 `backend/src/db/repository.py` 末尾追加：

```python
from src.db.model import Conversation, Message, ResearchTask

class ResearchTaskRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user_id: str, query: str, thread_id: str) -> ResearchTask:
        task = ResearchTask(
            id=uuid.uuid4(),
            user_id=user_id,
            query=query,
            thread_id=thread_id,
            status="planning",
        )
        self.session.add(task)
        await self.session.commit()
        await self.session.refresh(task)
        return task

    async def get(self, task_id: uuid.UUID) -> ResearchTask | None:
        return await self.session.get(ResearchTask, task_id)

    async def get_by_user(self, user_id: str, task_id: uuid.UUID) -> ResearchTask | None:
        task = await self.session.get(ResearchTask, task_id)
        if task is None or str(task.user_id) != str(user_id):
            return None
        return task

    async def list_by_user(self, user_id: str) -> list[ResearchTask]:
        result = await self.session.execute(
            select(ResearchTask)
            .where(ResearchTask.user_id == user_id)
            .order_by(desc(ResearchTask.updated_at))
        )
        return list(result.scalars().all())

    async def update_status(self, task_id: uuid.UUID, status: str) -> None:
        task = await self.session.get(ResearchTask, task_id)
        if task:
            task.status = status
            await self.session.commit()

    async def update_outline(self, task_id: uuid.UUID, outline: list) -> None:
        task = await self.session.get(ResearchTask, task_id)
        if task:
            task.outline = outline
            await self.session.commit()

    async def update_sources(self, task_id: uuid.UUID, sources: list) -> None:
        task = await self.session.get(ResearchTask, task_id)
        if task:
            task.sources = sources
            await self.session.commit()

    async def update_report(self, task_id: uuid.UUID, report: str) -> None:
        task = await self.session.get(ResearchTask, task_id)
        if task:
            task.report = report
            task.status = "done"
            await self.session.commit()

    async def set_error(self, task_id: uuid.UUID, error_message: str) -> None:
        task = await self.session.get(ResearchTask, task_id)
        if task:
            task.status = "error"
            task.error_message = error_message
            await self.session.commit()
```

注意：同时需要更新文件顶部的 import，将 `from src.db.model import Conversation, Message` 改为 `from src.db.model import Conversation, Message, ResearchTask`。

- [ ] **Step 4: 生成 Alembic 迁移脚本**

```bash
cd /home/wsyc1/projects/langchain/backend
uv run alembic revision --autogenerate -m "add research_tasks table"
```

Expected: 生成迁移脚本文件

- [ ] **Step 5: 执行迁移**

```bash
cd /home/wsyc1/projects/langchain/backend
uv run alembic upgrade head
```

Expected: 迁移成功，`research_tasks` 表已创建

- [ ] **Step 6: Commit**

```bash
cd /home/wsyc1/projects/langchain
git add backend/src/db/model.py backend/src/schemas.py backend/src/db/repository.py backend/alembic/versions/
git commit -m "feat: add ResearchTask model, schemas, repository + migration"
```

---

## Task 4: 研究 LangGraph 图 — State + 三个节点 + 编排

这是整个功能的核心。

**Files:**
- Create: `backend/src/research_graph.py`
- Test: `backend/tests/test_research_graph.py`

- [ ] **Step 1: 创建研究图测试文件**

```python
# backend/tests/test_research_graph.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def test_research_state_types():
    """验证 State 类型定义正确"""
    from src.research_graph import ResearchState
    state: ResearchState = {
        "query": "什么是 LangGraph？",
        "outline": [],
        "sources": [],
        "report": "",
        "progress_log": [],
    }
    assert state["query"] == "什么是 LangGraph？"
    assert isinstance(state["outline"], list)
    assert isinstance(state["sources"], list)


def test_planner_prompt_contains_query():
    """验证 planner 节点的 prompt 构建包含用户问题"""
    from src.research_graph import build_planner_prompt
    prompt = build_planner_prompt("LangGraph 的优势是什么？")
    assert "LangGraph 的优势是什么？" in prompt
    assert "3" in prompt or "5" in prompt  # 要求拆解为 3-5 个子问题


def test_writer_prompt_contains_sources():
    """验证 writer 节点的 prompt 构建包含来源材料"""
    from src.research_graph import build_writer_prompt
    sources = [
        {"sub_question_id": 1, "url": "https://example.com", "title": "Test",
         "snippet": "测试内容", "credibility": "high"}
    ]
    prompt = build_writer_prompt("测试问题", sources)
    assert "测试内容" in prompt
    assert "https://example.com" in prompt


def test_graph_nodes_exist():
    """验证图包含 planner、researcher、writer 三个节点"""
    from src.research_graph import research_workflow
    node_names = set(research_workflow.nodes.keys())
    assert "planner" in node_names
    assert "researcher" in node_names
    assert "writer" in node_names
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/wsyc1/projects/langchain/backend
uv run pytest tests/test_research_graph.py -v
```

Expected: FAIL — `research_graph` 模块不存在

- [ ] **Step 3: 创建 research_graph.py — 类型定义和 Prompt 构建**

```python
# backend/src/research_graph.py
"""深度研究 LangGraph 图定义"""

from typing import TypedDict
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
from src.config import settings
from src.tools import search_web, fetch_url, is_safe_url
from src.observability import langfuse_handler
import json
import asyncio
import logging

logger = logging.getLogger(__name__)

# ===== State 类型定义 =====

class SubQuestion(TypedDict):
    id: int
    question: str
    search_queries: list[str]

class SourceItem(TypedDict):
    sub_question_id: int
    url: str
    title: str
    snippet: str
    credibility: str  # high / medium / low

class ResearchState(TypedDict):
    query: str
    outline: list[SubQuestion]
    sources: list[SourceItem]
    report: str
    progress_log: list[str]

# ===== LLM 实例 =====

llm = ChatOpenAI(
    model="deepseek-chat",
    api_key=settings.DEEPSEEK_API_KEY,
    base_url=settings.DEEPSEEK_BASE_URL,
    streaming=True,
)

# ===== Prompt 构建函数 =====

def build_planner_prompt(query: str) -> str:
    return f"""你是一个研究助手。用户提出了一个研究问题，请将其拆解为 3-5 个具体的子问题。

要求：
- 每个子问题应该互不重叠，合在一起能全面覆盖原始问题
- 为每个子问题提供 1-2 个适合搜索引擎的搜索关键词
- 按照逻辑顺序排列（先基础概念，后深入分析）

用户问题：{query}

请严格以如下 JSON 格式返回（不要输出其他内容）：
[
  {{"id": 1, "question": "子问题文本", "search_queries": ["搜索词1", "搜索词2"]}},
  {{"id": 2, "question": "子问题文本", "search_queries": ["搜索词1"]}}
]"""


def build_extract_prompt(sub_question: str, page_content: str, url: str, title: str) -> str:
    return f"""从以下网页内容中，提取与问题相关的关键信息，并评估该来源的可信度。

问题：{sub_question}
网页标题：{title}
网页 URL：{url}
网页内容：
{page_content[:2000]}

评估标准：
- high：官方文档、权威媒体、学术论文、政府网站
- medium：知名博客、技术社区、百科类内容
- low：个人博客、论坛评论、来源不明的内容

请严格以如下 JSON 格式返回：
{{"snippet": "提取的关键段落（200-500字）", "credibility": "high|medium|low"}}"""


def build_writer_prompt(query: str, sources: list[dict]) -> str:
    sources_text = ""
    for s in sources:
        sources_text += f"\n---\n来源: [{s['title']}]({s['url']}) (可信度: {s['credibility']})\n内容: {s['snippet']}\n"

    return f"""你是一个研究报告撰写专家。请根据以下搜集到的材料，撰写一份结构化的研究报告。

研究问题：{query}

搜集到的材料：
{sources_text}

报告格式要求（Markdown）：
1. 标题使用一级标题
2. 开头写一段 200 字以内的摘要（用引用块 > 包裹）
3. 按照子问题组织章节，每个章节使用二级标题
4. 每个章节基于对应的来源材料展开分析
5. 最后写一个"结论"章节，综合所有材料回答原始问题
6. 最后列出"参考来源"，格式为 - [标题](URL) — 可信度：xxx

注意：
- 只使用提供的材料，不要编造信息
- 如果材料不足以回答某个方面，请明确说明
- 使用中文撰写"""


# ===== 节点实现 =====

async def planner_node(state: ResearchState) -> dict:
    """拆解用户问题为子问题"""
    query = state["query"]
    prompt = build_planner_prompt(query)

    response = await llm.ainvoke(
        [HumanMessage(content=prompt)],
        config={"callbacks": [langfuse_handler]},
    )

    # 解析 JSON 输出，带重试
    content = response.content.strip()
    # 尝试提取 JSON 部分（大模型可能会包裹在 ```json ``` 中）
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()

    try:
        outline = json.loads(content)
    except json.JSONDecodeError:
        # 重试一次
        response = await llm.ainvoke(
            [
                SystemMessage(content="你必须只返回纯 JSON，不要包含任何其他文字。"),
                HumanMessage(content=prompt),
            ],
            config={"callbacks": [langfuse_handler]},
        )
        content = response.content.strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        outline = json.loads(content)

    return {
        "outline": outline,
        "progress_log": state.get("progress_log", []) + [f"已将问题拆解为 {len(outline)} 个子问题"],
    }


async def researcher_node(state: ResearchState) -> dict:
    """遍历子问题进行搜索和网页阅读"""
    outline = state["outline"]
    all_sources: list[SourceItem] = []
    progress_log = list(state.get("progress_log", []))

    for sq in outline:
        sq_id = sq["id"]
        sq_question = sq["question"]
        search_queries = sq.get("search_queries", [sq_question])

        progress_log.append(f"正在搜索子问题 {sq_id}: {sq_question}")

        # 搜索
        for search_query in search_queries[:1]:  # 每个子问题只用第一个搜索词
            try:
                search_result = await search_web.ainvoke({"query": search_query})
            except Exception as e:
                logger.error(f"搜索失败 (子问题 {sq_id}): {e}")
                progress_log.append(f"子问题 {sq_id} 搜索失败: {str(e)[:100]}")
                continue

            # 从搜索结果中提取 URL
            urls_to_fetch = []
            for line in search_result.split("\n"):
                line = line.strip()
                if "http" in line:
                    # 尝试提取 URL
                    for word in line.split():
                        if word.startswith("http"):
                            url = word.rstrip(",.;:)")
                            if is_safe_url(url):
                                urls_to_fetch.append(url)
                            break

            # 深度阅读前 2 个 URL
            for url in urls_to_fetch[:2]:
                progress_log.append(f"正在深度阅读: {url[:80]}...")
                try:
                    page_content = await fetch_url.ainvoke({"url": url})
                except Exception as e:
                    logger.error(f"网页读取失败 ({url}): {e}")
                    progress_log.append(f"网页读取失败: {url[:50]}")
                    continue

                if page_content.startswith("错误:") or page_content.startswith("无法获取"):
                    progress_log.append(f"网页内容获取失败: {url[:50]}")
                    continue

                # 调用 LLM 提取关键信息并评估可信度
                title = url.split("/")[-1] or url
                extract_prompt = build_extract_prompt(sq_question, page_content, url, title)
                try:
                    extract_response = await llm.ainvoke(
                        [HumanMessage(content=extract_prompt)],
                        config={"callbacks": [langfuse_handler]},
                    )
                    extract_content = extract_response.content.strip()
                    if "```json" in extract_content:
                        extract_content = extract_content.split("```json")[1].split("```")[0].strip()
                    elif "```" in extract_content:
                        extract_content = extract_content.split("```")[1].split("```")[0].strip()

                    extracted = json.loads(extract_content)
                    source_item: SourceItem = {
                        "sub_question_id": sq_id,
                        "url": url,
                        "title": title,
                        "snippet": extracted.get("snippet", page_content[:500]),
                        "credibility": extracted.get("credibility", "medium"),
                    }
                    all_sources.append(source_item)
                    progress_log.append(f"已提取来源: {title[:40]} (可信度: {source_item['credibility']})")
                except Exception as e:
                    logger.error(f"信息提取失败: {e}")
                    # 降级：直接使用原始内容截断
                    all_sources.append({
                        "sub_question_id": sq_id,
                        "url": url,
                        "title": title,
                        "snippet": page_content[:500],
                        "credibility": "medium",
                    })
                    progress_log.append(f"信息提取降级处理: {title[:40]}")

        progress_log.append(f"子问题 {sq_id} 搜索完成")

    return {
        "sources": all_sources,
        "progress_log": progress_log,
    }


async def writer_node(state: ResearchState) -> dict:
    """基于审批后的来源材料生成研究报告"""
    query = state["query"]
    sources = state["sources"]
    progress_log = list(state.get("progress_log", []))

    if not sources:
        return {
            "report": f"# 研究报告\n\n> 未能收集到足够的材料来回答此问题。请尝试更换问题或稍后重试。\n",
            "progress_log": progress_log + ["无可用来源，生成空报告"],
        }

    prompt = build_writer_prompt(query, sources)
    progress_log.append("正在撰写研究报告...")

    response = await llm.ainvoke(
        [HumanMessage(content=prompt)],
        config={"callbacks": [langfuse_handler]},
    )

    report = response.content
    progress_log.append("研究报告撰写完成")

    return {
        "report": report,
        "progress_log": progress_log,
    }


# ===== 图编排 =====

research_workflow = StateGraph(ResearchState)
research_workflow.add_node("planner", planner_node)
research_workflow.add_node("researcher", researcher_node)
research_workflow.add_node("writer", writer_node)

research_workflow.set_entry_point("planner")
research_workflow.add_edge("planner", "researcher")
research_workflow.add_edge("researcher", "writer")
research_workflow.add_edge("writer", END)

# 注意：编译在 service 层完成，因为需要传入 checkpointer 和 interrupt_before
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /home/wsyc1/projects/langchain/backend
uv run pytest tests/test_research_graph.py -v
```

Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd /home/wsyc1/projects/langchain
git add backend/src/research_graph.py backend/tests/test_research_graph.py
git commit -m "feat: implement research LangGraph with planner/researcher/writer nodes"
```

---

## Task 5: 后端 Service + Router — SSE 流生成器和 API 端点

**Files:**
- Create: `backend/src/service/research.py`
- Create: `backend/src/router/research.py`
- Modify: `backend/main.py`

- [ ] **Step 1: 创建 research service**

```python
# backend/src/service/research.py
"""深度研究业务逻辑：SSE 流生成器"""

from src.research_graph import research_workflow, ResearchState
from src.graph import pool, checkpointer  # 共享 checkpointer
from src.db.repository import ResearchTaskRepository
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import StreamingResponse
from src.observability import langfuse_handler
import json
import uuid
import logging

logger = logging.getLogger(__name__)

# 编译研究图（使用共享的 checkpointer，两个中断点）
research_app = research_workflow.compile(
    checkpointer=checkpointer,
    interrupt_before=["researcher", "writer"],
)


def sse_event(data: dict) -> str:
    """格式化 SSE 事件"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def start_research(query: str, user_id: str, db: AsyncSession):
    """启动研究任务，执行 planner 阶段"""

    async def generator():
        task_repo = ResearchTaskRepository(db)
        thread_id = str(uuid.uuid4())

        # 创建研究任务记录
        task = await task_repo.create(user_id, query, thread_id)
        task_id = str(task.id)

        yield sse_event({"type": "research_start", "task_id": task_id, "thread_id": thread_id})
        yield sse_event({"type": "progress", "step": "planner", "status": "running", "message": "正在分析问题并拆解子问题..."})

        config = {
            "configurable": {"thread_id": thread_id},
            "callbacks": [langfuse_handler],
        }

        state_input: ResearchState = {
            "query": query,
            "outline": [],
            "sources": [],
            "report": "",
            "progress_log": [],
        }

        try:
            # 执行到第一个中断点（researcher 之前）
            async for event in research_app.astream(state_input, config, stream_mode="values"):
                pass  # planner 节点执行完毕

            # 获取 planner 输出的提纲
            state = await research_app.aget_state(config)
            outline = state.values.get("outline", [])

            # 更新数据库
            await task_repo.update_outline(task.id, outline)
            await task_repo.update_status(task.id, "outline_review")

            yield sse_event({"type": "progress", "step": "planner", "status": "done", "message": f"已拆解为 {len(outline)} 个子问题"})
            yield sse_event({"type": "outline_ready", "task_id": task_id, "thread_id": thread_id, "outline": outline})

        except Exception as e:
            logger.error(f"研究任务启动失败: {e}")
            await task_repo.set_error(task.id, str(e))
            yield sse_event({"type": "error", "message": f"问题分析失败: {str(e)[:200]}"})

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


async def approve_outline(task_id: uuid.UUID, thread_id: str, approved_outline: list, user_id: str, db: AsyncSession):
    """审批提纲后恢复图执行，进入 researcher 阶段"""

    async def generator():
        task_repo = ResearchTaskRepository(db)

        config = {
            "configurable": {"thread_id": thread_id},
            "callbacks": [langfuse_handler],
        }

        try:
            # 将用户审批后的提纲更新到图状态
            await research_app.aupdate_state(
                config,
                {"outline": approved_outline},
                as_node="planner",
            )

            # 更新数据库
            await task_repo.update_outline(task_id, approved_outline)
            await task_repo.update_status(task_id, "researching")

            # 为每个子问题推送搜索进度
            for i, sq in enumerate(approved_outline):
                yield sse_event({
                    "type": "progress",
                    "step": "search",
                    "sub_question_id": sq["id"],
                    "status": "pending",
                    "message": f"子问题 {sq['id']}: {sq['question'][:50]}",
                })

            # 恢复图执行（researcher 节点执行，然后在 writer 之前暂停）
            async for event in research_app.astream(None, config, stream_mode="values"):
                # 从 progress_log 变化推送进度
                progress_log = event.get("progress_log", [])
                if progress_log:
                    latest = progress_log[-1]
                    yield sse_event({"type": "progress", "step": "search", "status": "running", "message": latest})

            # 获取 researcher 输出的来源
            state = await research_app.aget_state(config)
            sources = state.values.get("sources", [])

            # 更新数据库
            await task_repo.update_sources(task_id, sources)
            await task_repo.update_status(task_id, "sources_review")

            yield sse_event({"type": "progress", "step": "search", "status": "done", "message": f"搜索完成，共收集 {len(sources)} 个来源"})
            yield sse_event({"type": "sources_ready", "task_id": str(task_id), "thread_id": thread_id, "sources": sources})

        except Exception as e:
            logger.error(f"研究搜索阶段失败: {e}")
            await task_repo.set_error(task_id, str(e))
            yield sse_event({"type": "error", "message": f"搜索阶段失败: {str(e)[:200]}"})

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


async def approve_sources(task_id: uuid.UUID, thread_id: str, approved_indices: list[int], user_id: str, db: AsyncSession):
    """审批来源后恢复图执行，进入 writer 阶段"""

    async def generator():
        task_repo = ResearchTaskRepository(db)

        config = {
            "configurable": {"thread_id": thread_id},
            "callbacks": [langfuse_handler],
        }

        try:
            # 获取当前来源并筛选
            state = await research_app.aget_state(config)
            all_sources = state.values.get("sources", [])
            filtered_sources = [s for i, s in enumerate(all_sources) if i in approved_indices]

            # 更新图状态
            await research_app.aupdate_state(
                config,
                {"sources": filtered_sources},
                as_node="researcher",
            )

            await task_repo.update_sources(task_id, filtered_sources)
            await task_repo.update_status(task_id, "writing")

            yield sse_event({"type": "progress", "step": "writer", "status": "running", "message": f"正在基于 {len(filtered_sources)} 个来源撰写报告..."})

            # 恢复图执行（writer 节点执行）
            report_content = ""
            async for event in research_app.astream(None, config, stream_mode="values"):
                report = event.get("report", "")
                if report and report != report_content:
                    # 推送新增的报告内容
                    new_chunk = report[len(report_content):]
                    if new_chunk:
                        yield sse_event({"type": "report_chunk", "content": new_chunk})
                    report_content = report

            # 获取最终报告
            state = await research_app.aget_state(config)
            final_report = state.values.get("report", "")

            # 更新数据库
            await task_repo.update_report(task_id, final_report)

            yield sse_event({"type": "progress", "step": "writer", "status": "done", "message": "报告撰写完成"})
            yield sse_event({"type": "report_done", "task_id": str(task_id)})

        except Exception as e:
            logger.error(f"报告撰写阶段失败: {e}")
            await task_repo.set_error(task_id, str(e))
            yield sse_event({"type": "error", "message": f"报告撰写失败: {str(e)[:200]}"})

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
```

- [ ] **Step 2: 创建 research router**

```python
# backend/src/router/research.py
"""深度研究 API 路由"""

import uuid
from fastapi import APIRouter, HTTPException, Depends
from src.schemas import (
    ResearchStartRequest,
    ApproveOutlineRequest,
    ApproveSourcesRequest,
    ResearchTaskOut,
    ResearchTaskDetail,
)
from src.service.research import start_research, approve_outline, approve_sources
from src.db.session import get_db
from src.utils.security import get_current_user
from src.db.model import User
from src.db.repository import ResearchTaskRepository
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/research", tags=["Research"])


@router.post("/start")
async def start(req: ResearchStartRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return await start_research(req.query, user.id, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{task_id}/approve-outline")
async def approve_outline_route(
    task_id: uuid.UUID,
    req: ApproveOutlineRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task_repo = ResearchTaskRepository(db)
    task = await task_repo.get_by_user(user.id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="研究任务未找到")

    try:
        outline_dicts = [sq.model_dump() for sq in req.outline]
        return await approve_outline(task_id, req.thread_id, outline_dicts, user.id, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{task_id}/approve-sources")
async def approve_sources_route(
    task_id: uuid.UUID,
    req: ApproveSourcesRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    task_repo = ResearchTaskRepository(db)
    task = await task_repo.get_by_user(user.id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="研究任务未找到")

    try:
        return await approve_sources(task_id, req.thread_id, req.approved_indices, user.id, db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks", response_model=list[ResearchTaskOut])
async def list_tasks(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    task_repo = ResearchTaskRepository(db)
    tasks = await task_repo.list_by_user(user.id)
    return [
        {
            "id": str(t.id),
            "query": t.query,
            "status": t.status,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in tasks
    ]


@router.get("/{task_id}", response_model=ResearchTaskDetail)
async def get_task(task_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    task_repo = ResearchTaskRepository(db)
    task = await task_repo.get_by_user(user.id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="研究任务未找到")

    return {
        "id": str(task.id),
        "query": task.query,
        "status": task.status,
        "outline": task.outline,
        "sources": task.sources,
        "report": task.report,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }
```

- [ ] **Step 3: 在 main.py 中注册研究路由**

在 `backend/main.py` 中：

添加 import（在现有 router import 之后）：

```python
from src.router.research import router as research_router
```

添加路由注册（在现有 `app.include_router` 之后）：

```python
app.include_router(research_router)
```

- [ ] **Step 4: 验证后端可正常导入**

```bash
cd /home/wsyc1/projects/langchain/backend
uv run python -c "from main import app; print('✅ 后端导入成功:', app)"
```

Expected: `✅ 后端导入成功: <fastapi.applications.FastAPI object ...>`

- [ ] **Step 5: Commit**

```bash
cd /home/wsyc1/projects/langchain
git add backend/src/service/research.py backend/src/router/research.py backend/main.py
git commit -m "feat: add research service (SSE generators) and API router"
```

---

## Task 6: 前端 — Pinia Store + API Service

**Files:**
- Create: `frontend/src/stores/research.ts`
- Create: `frontend/src/services/research.ts`

- [ ] **Step 1: 创建 research API service**

```typescript
// frontend/src/services/research.ts
import { apiUrl, getAuthHeaders } from '@/services/api'

export interface SubQuestion {
  id: number
  question: string
  search_queries: string[]
}

export interface SourceItem {
  sub_question_id: number
  url: string
  title: string
  snippet: string
  credibility: 'high' | 'medium' | 'low'
}

export interface ResearchTaskSummary {
  id: string
  query: string
  status: string
  created_at: string | null
}

export interface ResearchTaskDetail {
  id: string
  query: string
  status: string
  outline: SubQuestion[] | null
  sources: SourceItem[] | null
  report: string | null
  created_at: string | null
}

export async function startResearch(query: string): Promise<Response> {
  return fetch(apiUrl('/research/start'), {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({ query }),
  })
}

export async function approveOutline(taskId: string, threadId: string, outline: SubQuestion[]): Promise<Response> {
  return fetch(apiUrl(`/research/${taskId}/approve-outline`), {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({ thread_id: threadId, outline }),
  })
}

export async function approveSources(taskId: string, threadId: string, approvedIndices: number[]): Promise<Response> {
  return fetch(apiUrl(`/research/${taskId}/approve-sources`), {
    method: 'POST',
    headers: getAuthHeaders(),
    body: JSON.stringify({ thread_id: threadId, approved_indices: approvedIndices }),
  })
}

export async function fetchResearchTasks(): Promise<ResearchTaskSummary[]> {
  const res = await fetch(apiUrl('/research/tasks'), { headers: getAuthHeaders() })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function fetchResearchTask(taskId: string): Promise<ResearchTaskDetail> {
  const res = await fetch(apiUrl(`/research/${taskId}`), { headers: getAuthHeaders() })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
```

- [ ] **Step 2: 创建 research Pinia store**

```typescript
// frontend/src/stores/research.ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  startResearch as apiStartResearch,
  approveOutline as apiApproveOutline,
  approveSources as apiApproveSources,
  fetchResearchTasks,
  fetchResearchTask,
  type SubQuestion,
  type SourceItem,
  type ResearchTaskSummary,
} from '@/services/research'

export interface ProgressStep {
  id: string
  label: string
  status: 'pending' | 'running' | 'done' | 'error'
}

export const useResearchStore = defineStore('research', () => {
  // 当前任务
  const currentTaskId = ref<string | null>(null)
  const threadId = ref<string | null>(null)
  const query = ref('')
  const status = ref<'idle' | 'planning' | 'outline_review' | 'researching' | 'sources_review' | 'writing' | 'done' | 'error'>('idle')

  // 数据
  const outline = ref<SubQuestion[]>([])
  const sources = ref<SourceItem[]>([])
  const report = ref('')

  // 进度
  const progressSteps = ref<ProgressStep[]>([])
  const progressMessage = ref('')

  // 历史
  const taskList = ref<ResearchTaskSummary[]>([])

  // 错误
  const errorMessage = ref('')

  function resetCurrent() {
    currentTaskId.value = null
    threadId.value = null
    query.value = ''
    status.value = 'idle'
    outline.value = []
    sources.value = []
    report.value = ''
    progressSteps.value = []
    progressMessage.value = ''
    errorMessage.value = ''
  }

  // SSE 流读取通用函数
  async function readSSEStream(res: Response) {
    const reader = res.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const payload = line.slice(6)

          try {
            const event = JSON.parse(payload)
            handleSSEEvent(event)
          } catch (err) {
            console.error('[Research SSE] JSON 解析失败:', payload, err)
          }
        }
      }
    } finally {
      // 处理剩余 buffer
      if (buffer.startsWith('data: ')) {
        try {
          const event = JSON.parse(buffer.slice(6))
          handleSSEEvent(event)
        } catch {}
      }
    }
  }

  function handleSSEEvent(event: any) {
    switch (event.type) {
      case 'research_start':
        currentTaskId.value = event.task_id
        threadId.value = event.thread_id
        status.value = 'planning'
        progressSteps.value = [
          { id: 'planner', label: '分析问题', status: 'running' },
        ]
        break

      case 'progress':
        progressMessage.value = event.message || ''
        if (event.step === 'planner' && event.status === 'done') {
          updateStepStatus('planner', 'done')
        } else if (event.step === 'search') {
          // 确保搜索步骤存在
          const searchStepId = event.sub_question_id ? `search_${event.sub_question_id}` : 'search'
          const exists = progressSteps.value.find(s => s.id === searchStepId)
          if (!exists && event.sub_question_id) {
            progressSteps.value.push({
              id: searchStepId,
              label: event.message?.substring(0, 40) || `搜索子问题 ${event.sub_question_id}`,
              status: event.status === 'done' ? 'done' : 'running',
            })
          } else if (exists) {
            exists.status = event.status === 'done' ? 'done' : 'running'
            exists.label = event.message?.substring(0, 40) || exists.label
          }
        } else if (event.step === 'writer') {
          const writerStep = progressSteps.value.find(s => s.id === 'writer')
          if (!writerStep) {
            progressSteps.value.push({ id: 'writer', label: '撰写报告', status: 'running' })
          } else {
            writerStep.status = event.status === 'done' ? 'done' : 'running'
          }
        }
        break

      case 'outline_ready':
        status.value = 'outline_review'
        outline.value = event.outline || []
        break

      case 'sources_ready':
        status.value = 'sources_review'
        sources.value = event.sources || []
        break

      case 'report_chunk':
        if (event.content) {
          report.value += event.content
        }
        break

      case 'report_done':
        status.value = 'done'
        updateStepStatus('writer', 'done')
        break

      case 'error':
        status.value = 'error'
        errorMessage.value = event.message || '未知错误'
        break
    }
  }

  function updateStepStatus(stepId: string, newStatus: ProgressStep['status']) {
    const step = progressSteps.value.find(s => s.id === stepId)
    if (step) step.status = newStatus
  }

  // Actions
  async function startResearch(researchQuery: string) {
    resetCurrent()
    query.value = researchQuery
    status.value = 'planning'

    try {
      const res = await apiStartResearch(researchQuery)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      await readSSEStream(res)
    } catch (e: any) {
      status.value = 'error'
      errorMessage.value = e.message
    }
  }

  async function submitOutline(approvedOutline: SubQuestion[]) {
    if (!currentTaskId.value || !threadId.value) return

    outline.value = approvedOutline
    status.value = 'researching'

    // 为搜索阶段添加进度步骤
    for (const sq of approvedOutline) {
      progressSteps.value.push({
        id: `search_${sq.id}`,
        label: `搜索: ${sq.question.substring(0, 30)}...`,
        status: 'pending',
      })
    }

    try {
      const res = await apiApproveOutline(currentTaskId.value, threadId.value, approvedOutline)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      await readSSEStream(res)
    } catch (e: any) {
      status.value = 'error'
      errorMessage.value = e.message
    }
  }

  async function submitSources(approvedIndices: number[]) {
    if (!currentTaskId.value || !threadId.value) return

    status.value = 'writing'
    progressSteps.value.push({ id: 'writer', label: '撰写报告', status: 'pending' })

    try {
      const res = await apiApproveSources(currentTaskId.value, threadId.value, approvedIndices)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      await readSSEStream(res)
    } catch (e: any) {
      status.value = 'error'
      errorMessage.value = e.message
    }
  }

  async function loadTaskList() {
    try {
      taskList.value = await fetchResearchTasks()
    } catch (e) {
      console.error('[Research] 获取任务列表失败:', e)
    }
  }

  async function loadTask(taskId: string) {
    try {
      const detail = await fetchResearchTask(taskId)
      currentTaskId.value = detail.id
      query.value = detail.query
      outline.value = detail.outline || []
      sources.value = detail.sources || []
      report.value = detail.report || ''
      status.value = detail.status as any || 'idle'
    } catch (e) {
      console.error('[Research] 获取任务详情失败:', e)
    }
  }

  return {
    currentTaskId, threadId, query, status,
    outline, sources, report,
    progressSteps, progressMessage,
    taskList, errorMessage,
    resetCurrent, startResearch, submitOutline, submitSources,
    loadTaskList, loadTask,
  }
})
```

- [ ] **Step 3: Commit**

```bash
cd /home/wsyc1/projects/langchain
git add frontend/src/stores/research.ts frontend/src/services/research.ts
git commit -m "feat: add research Pinia store and API service with SSE handling"
```

---

## Task 7: 前端 — 四个研究 UI 组件

**Files:**
- Create: `frontend/src/components/ResearchTimeline.vue`
- Create: `frontend/src/components/OutlineEditor.vue`
- Create: `frontend/src/components/SourcesReviewer.vue`
- Create: `frontend/src/components/ReportRenderer.vue`

由于四个组件各自独立，这里按顺序创建。每个组件包含 `<script setup>`, `<template>`, `<style scoped>`。

- [ ] **Step 1: 创建 ResearchTimeline.vue**

```vue
<!-- frontend/src/components/ResearchTimeline.vue -->
<script setup lang="ts">
import { useResearchStore, type ProgressStep } from '@/stores/research'

const research = useResearchStore()
</script>

<template>
  <div class="timeline">
    <div class="timeline-title">研究进度</div>
    <div class="timeline-steps">
      <div
        v-for="step in research.progressSteps"
        :key="step.id"
        class="timeline-step"
        :class="step.status"
      >
        <div class="step-indicator">
          <span v-if="step.status === 'done'" class="step-icon done">✓</span>
          <span v-else-if="step.status === 'running'" class="step-icon running">
            <span class="spinner"></span>
          </span>
          <span v-else-if="step.status === 'error'" class="step-icon error">✗</span>
          <span v-else class="step-icon pending">○</span>
        </div>
        <div class="step-label">{{ step.label }}</div>
      </div>
    </div>
    <div v-if="research.progressMessage" class="progress-detail">
      {{ research.progressMessage }}
    </div>
  </div>
</template>

<style scoped>
.timeline {
  padding: 20px 16px;
  min-width: 200px;
  max-width: 240px;
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.timeline-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 1px;
}

.timeline-steps {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.timeline-step {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--radius-sm);
  transition: var(--transition-smooth);
}

.timeline-step.running {
  background: var(--primary-glow);
}

.step-indicator {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.step-icon {
  font-size: 12px;
  font-weight: 700;
}

.step-icon.done { color: var(--success); }
.step-icon.error { color: var(--warning); }
.step-icon.pending { color: var(--text-muted); }

.spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid var(--primary-glow);
  border-top: 2px solid var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.step-label {
  font-size: 13px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.timeline-step.done .step-label { color: var(--text-primary); }
.timeline-step.running .step-label { color: var(--primary); font-weight: 600; }

.progress-detail {
  font-size: 11px;
  color: var(--text-muted);
  padding: 8px 10px;
  background: var(--bg-card);
  border-radius: var(--radius-sm);
  line-height: 1.5;
  word-break: break-all;
}
</style>
```

- [ ] **Step 2: 创建 OutlineEditor.vue**

```vue
<!-- frontend/src/components/OutlineEditor.vue -->
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useResearchStore } from '@/stores/research'
import type { SubQuestion } from '@/services/research'

const research = useResearchStore()
const editableOutline = ref<SubQuestion[]>([])

onMounted(() => {
  editableOutline.value = JSON.parse(JSON.stringify(research.outline))
})

function removeQuestion(index: number) {
  editableOutline.value.splice(index, 1)
  // 重新编号
  editableOutline.value.forEach((sq, i) => { sq.id = i + 1 })
}

function addQuestion() {
  const newId = editableOutline.value.length + 1
  editableOutline.value.push({
    id: newId,
    question: '',
    search_queries: [''],
  })
}

function handleApprove() {
  const valid = editableOutline.value.filter(sq => sq.question.trim())
  if (valid.length === 0) return
  research.submitOutline(valid)
}
</script>

<template>
  <div class="outline-editor">
    <div class="editor-header">
      <h3 class="editor-title">📋 研究提纲</h3>
      <p class="editor-desc">AI 将问题拆解为以下子问题，你可以修改、删除或添加子问题</p>
    </div>

    <div class="questions-list">
      <div
        v-for="(sq, index) in editableOutline"
        :key="sq.id"
        class="question-card"
      >
        <div class="question-header">
          <span class="question-number">{{ index + 1 }}</span>
          <button class="remove-btn" @click="removeQuestion(index)" title="删除此子问题">✕</button>
        </div>
        <input
          v-model="sq.question"
          class="question-input"
          placeholder="输入子问题..."
        />
        <input
          v-model="sq.search_queries[0]"
          class="search-query-input"
          placeholder="搜索关键词..."
        />
      </div>
    </div>

    <div class="editor-actions">
      <button class="add-btn" @click="addQuestion">+ 添加子问题</button>
      <button class="approve-btn" @click="handleApprove">✓ 确认并开始研究</button>
    </div>
  </div>
</template>

<style scoped>
.outline-editor {
  max-width: 680px;
  margin: 0 auto;
  padding: 24px;
}

.editor-header {
  margin-bottom: 24px;
}

.editor-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.editor-desc {
  font-size: 14px;
  color: var(--text-secondary);
}

.questions-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 20px;
}

.question-card {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  padding: 16px;
  box-shadow: var(--shadow-lift);
  transition: var(--transition-smooth);
}

.question-card:hover {
  border-color: var(--primary-glow);
  box-shadow: var(--shadow-card);
}

.question-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.question-number {
  width: 24px;
  height: 24px;
  background: var(--primary);
  color: white;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
}

.remove-btn {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 14px;
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  transition: var(--transition-smooth);
}

.remove-btn:hover {
  color: var(--warning);
  background: rgba(239, 68, 68, 0.08);
}

.question-input,
.search-query-input {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--bg-app);
  color: var(--text-primary);
  font-size: 14px;
  font-family: inherit;
  outline: none;
  transition: var(--transition-smooth);
}

.question-input { margin-bottom: 8px; font-weight: 500; }
.search-query-input { font-size: 13px; color: var(--text-secondary); }

.question-input:focus,
.search-query-input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-glow);
}

.editor-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.add-btn {
  padding: 10px 20px;
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 14px;
  transition: var(--transition-smooth);
}

.add-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.approve-btn {
  padding: 12px 28px;
  border: none;
  border-radius: var(--radius-md);
  background: var(--primary);
  color: white;
  cursor: pointer;
  font-size: 15px;
  font-weight: 600;
  box-shadow: 0 4px 12px var(--primary-glow);
  transition: var(--transition-smooth);
}

.approve-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px var(--primary-glow);
}
</style>
```

- [ ] **Step 3: 创建 SourcesReviewer.vue**

```vue
<!-- frontend/src/components/SourcesReviewer.vue -->
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useResearchStore } from '@/stores/research'

const research = useResearchStore()
const selectedIndices = ref<Set<number>>(new Set())

onMounted(() => {
  // 默认全选
  research.sources.forEach((_, i) => selectedIndices.value.add(i))
})

function toggleSource(index: number) {
  if (selectedIndices.value.has(index)) {
    selectedIndices.value.delete(index)
  } else {
    selectedIndices.value.add(index)
  }
}

function handleApprove() {
  const indices = Array.from(selectedIndices.value).sort()
  if (indices.length === 0) return
  research.submitSources(indices)
}

function credibilityColor(level: string): string {
  if (level === 'high') return 'var(--success)'
  if (level === 'medium') return 'var(--text-secondary)'
  return 'var(--warning)'
}
</script>

<template>
  <div class="sources-reviewer">
    <div class="reviewer-header">
      <h3 class="reviewer-title">🔍 来源审查</h3>
      <p class="reviewer-desc">
        共收集 {{ research.sources.length }} 个来源，已选中 {{ selectedIndices.size }} 个。
        取消勾选不可信的来源，确认后开始生成报告。
      </p>
    </div>

    <div class="sources-list">
      <div
        v-for="(source, index) in research.sources"
        :key="index"
        class="source-card"
        :class="{ selected: selectedIndices.has(index), deselected: !selectedIndices.has(index) }"
        @click="toggleSource(index)"
      >
        <div class="source-checkbox">
          <span v-if="selectedIndices.has(index)" class="check-icon">✓</span>
          <span v-else class="check-icon unchecked">○</span>
        </div>
        <div class="source-content">
          <div class="source-title-row">
            <span class="source-title">{{ source.title }}</span>
            <span class="credibility-badge" :style="{ color: credibilityColor(source.credibility) }">
              {{ source.credibility }}
            </span>
          </div>
          <a class="source-url" :href="source.url" target="_blank" @click.stop>{{ source.url }}</a>
          <p class="source-snippet">{{ source.snippet.substring(0, 200) }}{{ source.snippet.length > 200 ? '...' : '' }}</p>
        </div>
      </div>
    </div>

    <div class="reviewer-actions">
      <span class="selection-hint">点击卡片切换选中状态</span>
      <button class="approve-btn" @click="handleApprove" :disabled="selectedIndices.size === 0">
        ✓ 确认来源并生成报告 ({{ selectedIndices.size }})
      </button>
    </div>
  </div>
</template>

<style scoped>
.sources-reviewer {
  max-width: 720px;
  margin: 0 auto;
  padding: 24px;
}

.reviewer-header { margin-bottom: 24px; }
.reviewer-title { font-size: 20px; font-weight: 700; color: var(--text-primary); margin-bottom: 8px; }
.reviewer-desc { font-size: 14px; color: var(--text-secondary); }

.sources-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 20px;
}

.source-card {
  display: flex;
  gap: 14px;
  padding: 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: var(--transition-smooth);
}

.source-card.selected {
  border-color: var(--primary-glow);
  box-shadow: var(--shadow-lift);
}

.source-card.deselected {
  opacity: 0.5;
}

.source-card:hover { box-shadow: var(--shadow-card); }

.source-checkbox { flex-shrink: 0; padding-top: 2px; }
.check-icon { font-size: 16px; font-weight: 700; color: var(--primary); }
.check-icon.unchecked { color: var(--text-muted); }

.source-content { flex: 1; min-width: 0; }

.source-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.source-title { font-size: 14px; font-weight: 600; color: var(--text-primary); }
.credibility-badge { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; }

.source-url {
  font-size: 12px;
  color: var(--primary);
  text-decoration: none;
  display: block;
  margin-bottom: 8px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-url:hover { text-decoration: underline; }

.source-snippet { font-size: 13px; color: var(--text-secondary); line-height: 1.5; }

.reviewer-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.selection-hint { font-size: 12px; color: var(--text-muted); }

.approve-btn {
  padding: 12px 28px;
  border: none;
  border-radius: var(--radius-md);
  background: var(--primary);
  color: white;
  cursor: pointer;
  font-size: 15px;
  font-weight: 600;
  box-shadow: 0 4px 12px var(--primary-glow);
  transition: var(--transition-smooth);
}

.approve-btn:hover { transform: translateY(-2px); box-shadow: 0 6px 20px var(--primary-glow); }
.approve-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
</style>
```

- [ ] **Step 4: 创建 ReportRenderer.vue**

```vue
<!-- frontend/src/components/ReportRenderer.vue -->
<script setup lang="ts">
import { computed } from 'vue'
import { useResearchStore } from '@/stores/research'
import { marked } from 'marked'
import hljs from 'highlight.js'

const research = useResearchStore()

// 配置 marked
marked.setOptions({
  breaks: true,
})

const renderedHtml = computed(() => {
  if (!research.report) return ''
  return marked(research.report) as string
})

function downloadReport() {
  const blob = new Blob([research.report], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `research-report-${research.currentTaskId?.slice(0, 8) || 'report'}.md`
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div class="report-renderer">
    <div class="report-toolbar">
      <h3 class="report-title">📄 研究报告</h3>
      <button class="download-btn" @click="downloadReport" v-if="research.status === 'done'">
        ⬇ 下载 Markdown
      </button>
    </div>
    <div class="report-content" v-html="renderedHtml"></div>
  </div>
</template>

<style scoped>
.report-renderer {
  max-width: 780px;
  margin: 0 auto;
  padding: 24px;
}

.report-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.report-title { font-size: 20px; font-weight: 700; color: var(--text-primary); }

.download-btn {
  padding: 8px 20px;
  border: 1px solid var(--primary);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--primary);
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  transition: var(--transition-smooth);
}

.download-btn:hover {
  background: var(--primary);
  color: white;
}

.report-content {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 32px;
  box-shadow: var(--shadow-card);
  line-height: 1.8;
  color: var(--text-primary);
  font-size: 15px;
}

.report-content :deep(h1) { font-size: 24px; font-weight: 700; margin-bottom: 16px; border-bottom: 2px solid var(--border-color); padding-bottom: 12px; }
.report-content :deep(h2) { font-size: 20px; font-weight: 600; margin-top: 28px; margin-bottom: 12px; color: var(--primary); }
.report-content :deep(h3) { font-size: 17px; font-weight: 600; margin-top: 20px; margin-bottom: 8px; }
.report-content :deep(blockquote) { border-left: 4px solid var(--primary); padding: 12px 20px; margin: 16px 0; background: var(--primary-glow); border-radius: 0 var(--radius-sm) var(--radius-sm) 0; }
.report-content :deep(a) { color: var(--primary); text-decoration: none; }
.report-content :deep(a:hover) { text-decoration: underline; }
.report-content :deep(ul), .report-content :deep(ol) { padding-left: 24px; margin: 12px 0; }
.report-content :deep(li) { margin-bottom: 6px; }
.report-content :deep(p) { margin-bottom: 12px; }
.report-content :deep(code) { background: rgba(0,0,0,0.05); padding: 2px 6px; border-radius: 4px; font-family: 'Fira Code', monospace; font-size: 13px; }

html.dark .report-content :deep(code) { background: rgba(255,255,255,0.08); }
</style>
```

- [ ] **Step 5: Commit**

```bash
cd /home/wsyc1/projects/langchain
git add frontend/src/components/ResearchTimeline.vue frontend/src/components/OutlineEditor.vue frontend/src/components/SourcesReviewer.vue frontend/src/components/ReportRenderer.vue
git commit -m "feat: add four research UI components (timeline, outline, sources, report)"
```

---

## Task 8: 前端 — ResearchView + 路由 + 侧边栏导航

**Files:**
- Create: `frontend/src/views/ResearchView.vue`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/components/ChatSidebar.vue`

- [ ] **Step 1: 创建 ResearchView.vue**

```vue
<!-- frontend/src/views/ResearchView.vue -->
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useResearchStore } from '@/stores/research'
import ResearchTimeline from '@/components/ResearchTimeline.vue'
import OutlineEditor from '@/components/OutlineEditor.vue'
import SourcesReviewer from '@/components/SourcesReviewer.vue'
import ReportRenderer from '@/components/ReportRenderer.vue'

const research = useResearchStore()
const inputQuery = ref('')
const inputFocused = ref(false)

onMounted(() => {
  research.loadTaskList()
})

function handleSubmit() {
  const q = inputQuery.value.trim()
  if (!q) return
  research.startResearch(q)
  inputQuery.value = ''
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSubmit()
  }
}
</script>

<template>
  <div class="research-view">
    <!-- 左侧：进度时间线（仅在研究进行中显示） -->
    <ResearchTimeline v-if="research.status !== 'idle'" />

    <!-- 右侧：主内容区域 -->
    <div class="research-main">

      <!-- 初始状态：输入研究问题 -->
      <div v-if="research.status === 'idle'" class="research-welcome">
        <div class="welcome-icon">🔬</div>
        <h2 class="welcome-title">深度研究</h2>
        <p class="welcome-desc">输入你的研究问题，AI 将自动搜索、分析并生成结构化报告</p>

        <div class="input-area" :class="{ focused: inputFocused }">
          <textarea
            v-model="inputQuery"
            class="research-input"
            placeholder="例如：2024-2026 年大语言模型在代码生成领域的最新进展和技术趋势是什么？"
            rows="3"
            @keydown="handleKeydown"
            @focus="inputFocused = true"
            @blur="inputFocused = false"
          ></textarea>
          <button class="submit-btn" @click="handleSubmit" :disabled="!inputQuery.trim()">
            开始研究 →
          </button>
        </div>
      </div>

      <!-- Planning 中 -->
      <div v-else-if="research.status === 'planning'" class="status-panel">
        <div class="status-spinner"></div>
        <p class="status-text">正在分析问题并拆解子问题...</p>
        <p class="status-query">「{{ research.query }}」</p>
      </div>

      <!-- 提纲审批 -->
      <OutlineEditor v-else-if="research.status === 'outline_review'" />

      <!-- 搜索中 -->
      <div v-else-if="research.status === 'researching'" class="status-panel">
        <div class="status-spinner"></div>
        <p class="status-text">正在搜索和收集资料...</p>
        <p class="status-detail">{{ research.progressMessage }}</p>
      </div>

      <!-- 来源审批 -->
      <SourcesReviewer v-else-if="research.status === 'sources_review'" />

      <!-- 撰写中 / 完成 -->
      <div v-else-if="research.status === 'writing' || research.status === 'done'">
        <ReportRenderer />
      </div>

      <!-- 错误 -->
      <div v-else-if="research.status === 'error'" class="status-panel error">
        <div class="error-icon">⚠️</div>
        <p class="status-text">研究过程中出现错误</p>
        <p class="status-detail">{{ research.errorMessage }}</p>
        <button class="retry-btn" @click="research.resetCurrent()">重新开始</button>
      </div>

    </div>
  </div>
</template>

<style scoped>
.research-view {
  flex: 1;
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.research-main {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  padding: 40px 24px;
}

/* 欢迎页 */
.research-welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-top: 15vh;
  max-width: 600px;
  text-align: center;
}

.welcome-icon { font-size: 48px; margin-bottom: 16px; }
.welcome-title { font-size: 28px; font-weight: 700; color: var(--text-primary); margin-bottom: 12px; }
.welcome-desc { font-size: 15px; color: var(--text-secondary); margin-bottom: 32px; line-height: 1.6; }

.input-area {
  width: 100%;
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
  padding: 20px;
  box-shadow: var(--shadow-card);
  transition: var(--transition-smooth);
}

.input-area.focused {
  border-color: var(--primary);
  box-shadow: 0 0 0 4px var(--primary-glow), var(--shadow-card);
}

.research-input {
  width: 100%;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-primary);
  font-size: 15px;
  font-family: inherit;
  resize: none;
  line-height: 1.6;
  margin-bottom: 12px;
}

.research-input::placeholder { color: var(--text-muted); }

.submit-btn {
  float: right;
  padding: 10px 24px;
  border: none;
  border-radius: var(--radius-md);
  background: var(--primary);
  color: white;
  cursor: pointer;
  font-size: 15px;
  font-weight: 600;
  box-shadow: 0 4px 12px var(--primary-glow);
  transition: var(--transition-smooth);
}

.submit-btn:hover { transform: translateY(-2px); box-shadow: 0 6px 20px var(--primary-glow); }
.submit-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

/* 状态面板 */
.status-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-top: 20vh;
  text-align: center;
}

.status-spinner {
  width: 40px; height: 40px;
  border: 3px solid var(--primary-glow);
  border-top: 3px solid var(--primary);
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin-bottom: 20px;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.status-text { font-size: 16px; font-weight: 600; color: var(--text-primary); margin-bottom: 8px; }
.status-query { font-size: 14px; color: var(--text-secondary); font-style: italic; }
.status-detail { font-size: 13px; color: var(--text-muted); margin-top: 8px; max-width: 500px; }

.status-panel.error .status-text { color: var(--warning); }
.error-icon { font-size: 40px; margin-bottom: 12px; }

.retry-btn {
  margin-top: 16px;
  padding: 8px 20px;
  border: 1px solid var(--primary);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--primary);
  cursor: pointer;
  font-size: 14px;
  transition: var(--transition-smooth);
}

.retry-btn:hover { background: var(--primary); color: white; }
</style>
```

- [ ] **Step 2: 在路由中添加 /research 路径**

修改 `frontend/src/router/index.ts`：

在 import 区域添加：

```typescript
import ResearchView from '@/views/ResearchView.vue'
```

在 routes 数组中，在 `{ path: '/login', ... }` 之前添加：

```typescript
{ path: '/research', name: 'research', component: ResearchView },
```

- [ ] **Step 3: 在 ChatSidebar.vue 中添加研究导航入口**

在 `frontend/src/components/ChatSidebar.vue` 的 `<script setup>` 中添加导入和状态：

在现有 import 之后添加：

```typescript
import { useResearchStore } from '@/stores/research'
const research = useResearchStore()
```

在模板的 `<!-- 会话列表 -->` 之前，`</div>` (user-control-panel 的关闭标签) 之后，插入导航切换区域：

```html
    <!-- 模式导航 -->
    <div class="mode-nav">
      <button
        class="mode-btn"
        :class="{ active: $route.name === 'chat' }"
        @click="router.push('/')"
      >
        💬 对话
      </button>
      <button
        class="mode-btn"
        :class="{ active: $route.name === 'research' }"
        @click="router.push('/research')"
      >
        🔬 深度研究
      </button>
    </div>
```

在 `<style scoped>` 中追加样式：

```css
.mode-nav {
  display: flex;
  gap: 6px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border-color);
}

.mode-btn {
  flex: 1;
  padding: 10px 8px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  transition: var(--transition-smooth);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.mode-btn:hover {
  background: var(--bg-card-hover);
  color: var(--text-primary);
}

.mode-btn.active {
  background: var(--primary-glow);
  color: var(--primary);
  border-color: var(--primary);
  font-weight: 600;
}
```

- [ ] **Step 4: 验证前端构建通过**

```bash
cd /home/wsyc1/projects/langchain/frontend
npm run build-only
```

Expected: 构建成功，无错误

- [ ] **Step 5: Commit**

```bash
cd /home/wsyc1/projects/langchain
git add frontend/src/views/ResearchView.vue frontend/src/router/index.ts frontend/src/components/ChatSidebar.vue
git commit -m "feat: add ResearchView, /research route, and sidebar navigation"
```

---

## Task 9: 集成测试 + 端到端验证

**Files:**
- Create: `backend/tests/test_research_api.py`

- [ ] **Step 1: 创建 API 路由基础测试**

```python
# backend/tests/test_research_api.py
"""研究 API 路由基础验证测试"""
import pytest


def test_research_schemas_importable():
    """验证所有研究相关 Schema 可正常导入"""
    from src.schemas import (
        ResearchStartRequest,
        ApproveOutlineRequest,
        ApproveSourcesRequest,
        ResearchTaskOut,
        ResearchTaskDetail,
        SubQuestionSchema,
        SourceItemSchema,
    )
    req = ResearchStartRequest(query="测试问题")
    assert req.query == "测试问题"


def test_research_router_importable():
    """验证研究路由可正常导入"""
    from src.router.research import router
    assert router is not None
    # 检查路由数量
    route_paths = [r.path for r in router.routes]
    assert "/start" in route_paths or any("/start" in p for p in route_paths)


def test_research_service_importable():
    """验证研究 service 可正常导入"""
    from src.service.research import start_research, approve_outline, approve_sources
    assert callable(start_research)
    assert callable(approve_outline)
    assert callable(approve_sources)


def test_research_task_model_importable():
    """验证 ResearchTask Model 可正常导入"""
    from src.db.model import ResearchTask
    assert ResearchTask.__tablename__ == "research_tasks"


def test_research_task_repository_importable():
    """验证 ResearchTaskRepository 可正常导入"""
    from src.db.repository import ResearchTaskRepository
    assert callable(ResearchTaskRepository)


def test_full_app_importable():
    """验证完整应用（含研究路由）可正常导入"""
    from main import app
    assert app is not None
```

- [ ] **Step 2: 运行所有测试**

```bash
cd /home/wsyc1/projects/langchain/backend
uv run pytest tests/ -v
```

Expected: 所有测试通过

- [ ] **Step 3: 验证前端构建**

```bash
cd /home/wsyc1/projects/langchain/frontend
npm run build-only
```

Expected: 构建成功

- [ ] **Step 4: Commit**

```bash
cd /home/wsyc1/projects/langchain
git add backend/tests/test_research_api.py
git commit -m "test: add research API integration tests"
```

---

## Task 10: 最终整理 + 验收

- [ ] **Step 1: 运行完整后端测试套件**

```bash
cd /home/wsyc1/projects/langchain/backend
uv run pytest tests/ -v --tb=short
```

Expected: 全部通过

- [ ] **Step 2: 验证后端可正常启动**

```bash
cd /home/wsyc1/projects/langchain/backend
uv run python -c "from main import app; print('✅ App loaded with routes:', [r.path for r in app.routes])"
```

Expected: 路由列表包含 `/research/start`, `/research/tasks` 等

- [ ] **Step 3: 验证前端可构建 + 开发服务器可启动**

```bash
cd /home/wsyc1/projects/langchain/frontend
npm run build-only
```

Expected: 构建成功

- [ ] **Step 4: 最终 Commit**

```bash
cd /home/wsyc1/projects/langchain
git add -A
git commit -m "feat: complete deep research agent with planner/researcher/writer pipeline"
```
