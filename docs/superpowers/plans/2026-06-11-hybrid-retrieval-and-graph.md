# 文件检索报告 Agent — 开发文档

> **最后更新**：2026-06-14  
> **状态**：Task 5/6 已完成，Task 7 待实施，数据库需新增表

---

## 1. 已完成清单

| 模块 | 文件 | 说明 |
|---|---|---|
| Chat Agent 图 | `graph.py` | agent→tools→agent + `interrupt_before` + `LazyAsyncPostgresSaver` |
| Chat 流式 SSE | `service/agent.py` | `chat_stream()` + `resume()`，含消息 RAG + embedding 持久化 |
| RAG 检索 | `rag.py` | BGE embedding + pgvector 粗筛 + BGE reranker 精排，含 `exclude_conversation_id` |
| 通用工具集 | `tools.py` | weather / calculator / search_web / fetch_url / get_current_time，含 SSRF 防护 |
| JWT 认证 | `utils/security.py` + `router/auth.py` | 注册/登录/鉴权 |
| 会话管理 | `router/conversation.py` | 会话列表/消息历史 |
| 文件解析 | `file_research/parser.py` | 后缀白名单、路径穿越防护、大小限制、UTF-8 解码、按行切块 |
| 文件上传 | `router/file.py` + `service/file_research.py` | 秒传(SHA256)、后台向量化、线程池并行 embedding |
| 向量 + Grep 检索 | `file_research/retriever.py` | 双通道检索 + `@tool` 封装 + `RunnableConfig` user_id 注入 |
| Research Graph | `file_research/research_graph.py` | agent→tools→agent + 共享 `checkpointer` |
| 前端 XSS 防护 | `ChatView.vue` | `DOMPurify.sanitize(marked.parse())` |
| 测试 | `tests/` | parser(7) + chunk_line(2) + indexing_service(1) + retriever(1) = 11 tests |

---

## 2. 数据库设计

聊天和研究使用独立的消息体系，物理隔离：

```
聊天体系:                          研究体系:
conversations                     research_sessions
     │ 1:N                             │ 1:N
     ↓                                 ↓
messages                         research_messages
(role/content/embedding)         (role/content/report_id)
                                      │ N:1
                                      ↓
                                 file_reports
                                 (session_id/version/report_md)
```

### 新增表：ResearchSession

```python
# db/model.py 新增
class ResearchSession(Base):
    __tablename__ = "research_sessions"
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    title = Column(String(256), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User")
    messages = relationship("ResearchMessage", back_populates="session",
                            cascade="all, delete-orphan",
                            order_by="ResearchMessage.created_at")
    reports = relationship("FileReport", back_populates="session",
                           cascade="all, delete-orphan")
```

### 新增表：ResearchMessage

```python
class ResearchMessage(Base):
    __tablename__ = "research_messages"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    session_id = Column(UUID, ForeignKey("research_sessions.id", ondelete="CASCADE"),
                        index=True)
    role = Column(String(16), nullable=False)        # user / assistant / tool
    content = Column(Text, nullable=False)
    tool_calls = Column(JSONB, nullable=True)
    report_id = Column(UUID, ForeignKey("file_reports.id", ondelete="SET NULL"),
                       nullable=True)                # 归属哪份报告
    created_at = Column(DateTime, server_default=func.now())

    session = relationship("ResearchSession", back_populates="messages")
    report = relationship("FileReport", back_populates="messages")
```

### FileReport 新增字段

```python
class FileReport(Base):
    # ... 现有字段 ...
    session_id = Column(UUID, ForeignKey("research_sessions.id", ondelete="CASCADE"),
                        nullable=False, index=True)          # ← 新增
    version = Column(Integer, nullable=False, default=1)     # ← 新增

    session = relationship("ResearchSession", back_populates="reports")
    messages = relationship("ResearchMessage", back_populates="report")
```

### 为什么不复用 conversations / messages 表

| | 聊天 messages | 研究 research_messages |
|---|---|---|
| 用途 | 闲聊历史 | 深度检索过程 |
| 关联 | → conversation | → session + → report |
| embedding | 存 768 维（做长期记忆 RAG） | 不存（检索靠 file_chunks，不需回忆闲聊） |
| 额外字段 | 无 | `report_id`（归属报告）、`version` 通过 report 关联 |
| 生命周期 | 伴随 conversation | 伴随 session，report 删了消息可选保留（ON DELETE SET NULL） |

### Migration

```bash
cd /home/wsyc1/projects/langchain/backend
uv run alembic revision --autogenerate -m "add research_sessions and research_messages"
uv run alembic upgrade head
```

---

## 3. 待实施任务

### Task 7: SSE 路由 + 完整报告闭环

**当前路由文件 `router/file_research.py` 是空壳（8 行），`main.py` 未注册。**

#### Step 1: 重写 `router/file_research.py`

```python
import uuid
import json
import re
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.messages import HumanMessage, AIMessageChunk, SystemMessage
from src.db.session import get_db
from src.utils.security import get_current_user
from src.db.model import User, FileDocument
from src.db.repository import FileReportRepository, FileDocumentRepository
from src.file_research.research_graph import research_app
from src.observability import langfuse_handler

router = APIRouter(prefix="/file-research", tags=["file-research"])


class ReportRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=2000)
    file_ids: list[uuid.UUID] | None = None
    session_id: uuid.UUID | None = None


@router.post("/reports/stream")
async def stream_research_report(
    req: ReportRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    user_id = str(user.id)

    report_repo = FileReportRepository(db)
    report = await report_repo.create(user_id, req.query)

    async def sse_generator():
        session_id = str(req.session_id or report.id)
        config = {
            "configurable": {
                "thread_id": session_id,
                "user_id": user_id,
                "document_ids": [str(fid) for fid in req.file_ids] if req.file_ids else None
            },
            "callbacks": [langfuse_handler]
        }

        system_prompt = (
            "你是一个专业的文档分析与研究报告生成助手。\n"
            "你只能依据工具检索到的本地文档内容（或联网检索到的内容）进行分析并回答。\n"
            "你在给出结论时，必须在其后精准引用来源，引用格式为：\n"
            "  `[Source: 文件名#L起始行号-L结束行号](chunk_id)`\n"
            "你的输出必须是一份结构严密的 Markdown 格式报告，包含标题、摘要、关键发现、详细分析和来源引用列表。"
        )

        inputs = {
            "messages": [
                SystemMessage(content=system_prompt),
                HumanMessage(content=req.query)
            ]
        }

        yield f"data: {json.dumps({'type': 'report_start', 'report_id': str(report.id)})}\n\n"

        collected_content = ""

        try:
            async for msg, metadata in research_app.astream(
                inputs, config, stream_mode="messages"
            ):
                if isinstance(msg, AIMessageChunk) and msg.content:
                    collected_content += msg.content
                    val = msg.content.replace(chr(10), '\\n')
                    yield f"data: {json.dumps({'type': 'text', 'content': val})}\n\n"

            chunk_ids = [
                int(cid) for cid in re.findall(r'\[Source:[^\]]+\]\((\d+)\)', collected_content)
            ]

            await report_repo.update_report(
                report_id=report.id,
                status="success",
                report_md=collected_content,
                selected_chunk_ids=chunk_ids
            )

            yield f"data: {json.dumps({
                'type': 'done',
                'report_id': str(report.id),
                'download_url': f'/file-research/reports/{report.id}/download'
            })}\n\n"

        except Exception as e:
            await report_repo.update_report(
                report_id=report.id, status="error", error_message=str(e)
            )
            yield f"data: {json.dumps({'type': 'error', 'message': str(e), 'report_id': str(report.id)})}\n\n"

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )


@router.get("/files/{file_id}/content")
async def get_file_content(
    file_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """提供给前端侧边栏：读取源文件全文"""
    doc = await db.get(FileDocument, file_id)
    if not doc or str(doc.user_id) != str(user.id):
        raise HTTPException(status_code=404, detail="文件不存在或无权查看")
    return {"content": doc.full_content}


@router.get("/files")
async def list_files(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """获取当前用户的文件列表"""
    repo = FileDocumentRepository(db)
    docs = await repo.list_by_user(str(user.id))
    return [
        {
            "id": str(d.id),
            "filename": d.filename,
            "size_bytes": d.size_bytes,
            "status": d.status,
            "created_at": d.created_at.isoformat() if d.created_at else None
        }
        for d in docs
    ]
```

#### Step 2: 修改 `main.py`

```python
# 新增 import（在现有 router import 之后）
from src.router.file_research import router as file_research_router

# 新增路由注册（在现有 app.include_router 之后）
app.include_router(file_research_router)
```

#### Step 3: 编写 API 权限测试

```python
# backend/tests/test_file_research_api.py
import pytest
import uuid
from src.db.model import User, FileDocument
from fastapi import HTTPException

@pytest.mark.asyncio
async def test_get_file_content_permission_denied(db_session):
    user_a = User()
    user_b = User()
    db_session.add(user_a)
    db_session.add(user_b)
    await db_session.commit()

    doc = FileDocument(
        id=uuid.uuid4(),
        user_id=user_a.id,
        filename="private.txt",
        size_bytes=10,
        sha256="sha256_private",
        status="indexed",
        full_content="top secret data"
    )
    db_session.add(doc)
    await db_session.commit()

    from src.router.file_research import get_file_content
    with pytest.raises(HTTPException) as exc_info:
        await get_file_content(file_id=doc.id, db=db_session, user=user_b)
    assert exc_info.value.status_code == 404
```

#### Step 4: 运行测试 + 提交

```bash
cd /home/wsyc1/projects/langchain/backend
uv run pytest tests/test_file_research_api.py -v
git add src/router/file_research.py main.py tests/test_file_research_api.py
git commit -m "feat: SSE research report API with file content & list endpoints"
```

---

## 4. 已知待修复

| # | 位置 | 问题 | 优先级 |
|---|---|---|---|
| 1 | `model.py` | 缺少 ResearchSession / ResearchMessage 表 + FileReport 缺少 session_id/version | P0 |
| 2 | `research_graph.py:41-45` | `should_continue` 缺少 tool_count 上限（chat 图有 100 上限） | P1 |
| 3 | `router/file_research.py:1-8` | 空壳，只有 import 和占位代码 | P0（Task 7） |
| 4 | `main.py` | 未注册 file_research_router | P0（Task 7） |
| 5 | `frontend/` | 无 FileResearchView / fileResearch store / fileResearch service | P2 |

---

## 5. 架构总览

```
┌────────────────────────────────────────────────────────────────────┐
│                       前端 (Vue 3)                                  │
│  ChatView (✅)  │  FileResearchView (❌)                            │
│  + DOMPurify    │  文件上传 | 检索输入 | 报告预览 | 下载           │
└─────────────────┬───────────────────────────────────┬──────────────┘
                  │ HTTP/SSE                          │
┌─────────────────┴───────┐   ┌───────────────────────┴──────────────┐
│  Chat API Routes (✅)   │   │  File Research Routes (❌ 待实施)    │
│  POST /agent/chat/stream│   │  POST /file-research/reports/stream  │
│  POST /agent/resume     │   │  GET  /file-research/files/{id}/content│
│  GET  /conversations    │   │  GET  /file-research/files           │
│  POST /file/upload      │   │                                      │
└─────────┬───────────────┘   └───────────────────────┬──────────────┘
          │                                           │
┌─────────┴───────────────┐   ┌───────────────────────┴──────────────┐
│   Chat Graph (✅)       │   │   Research Graph (✅)                │
│   graph.py              │   │   research_graph.py                  │
│                         │   │                                      │
│   agent──→tools         │   │   agent──→tools                      │
│    ↑       ↓            │   │    ↑         ↓                       │
│    └───interrupt_before │   │    └─────────┘                       │
│   State: messages       │   │   State: messages, report_md         │
│                         │   │                                      │
│   tools: weather, calc, │   │   tools: grep, vector, search_web    │
│           search_web... │   │                                      │
│   model: v4-flash       │   │   model: v4-pro                      │
└─────────┬───────────────┘   └───────────────────────┬──────────────┘
          │                                           │
          └──────────────┬────────────────────────────┘
                         │
           ┌─────────────┴─────────────┐
           │  LazyAsyncPostgresSaver   │
           │  (同一个 pool, 同一张表)  │
           │  graph.py:83              │
           └─────────────┬─────────────┘
                         │
┌────────────────────────┴──────────────────────────────────────────┐
│                      PostgreSQL + pgvector                         │
│                                                                    │
│  聊天体系:                 研究体系:                                │
│  users                    users (共享)                             │
│  user_credentials         ←── 共用                                │
│  conversations            research_sessions  ← 独立的 session      │
│  messages (embedding)     research_messages  ← 独立的 message       │
│                           file_documents                          │
│                           file_chunks (embedding)                 │
│                           file_reports (session_id, version)      │
│                                                                    │
│  langgraph checkpoints (由 AsyncPostgresSaver 自动管理)           │
└───────────────────────────────────────────────────────────────────┘
```

---

## 6. 数据流

### 文件上传（✅）
```
UploadFile → validate_filename → decode_text_file → SHA256 秒传判定
  ├── 已存在 → 直接返回
  └── 新文件 → FileDocument(status="processing")
                → BackgroundTasks → process_file_in_background
                   → chunk_text_with_line → 并行 embedding
                   → bulk_create(file_chunks) → update_status("indexed")
```

### 文件检索报告（Task 7 实现后）
```
POST /file-research/reports/stream  { query, session_id? }
  ↓ session_id 不存在 → 新建 ResearchSession + FileReport(version=1)
  ↓ session_id 存在   → 复用 ResearchSession + FileReport(version=N+1)
  ↓
  config.configurable: thread_id=session_id, user_id, document_ids
  ↓ SystemMessage: "引用格式 [Source: file#L12-L15](42)"
  ↓ research_app.astream(stream_mode="messages")
  ↓ 
  agent 判断 → tool_calls?
  ├── vector_search → pgvector ORDER BY cosine_distance → reranker → top 5
  ├── grep_search   → ILIKE %keyword% → top 10
  └── search_web    → Tavily API
  ↓
  agent 收到结果 → 生成 Markdown → 无 more tool_calls → END
  ↓
  SSE: text chunk → text chunk → ... → done + download_url
  ↓
  file_reports: status=success, report_md=..., selected_chunk_ids=[...]
  research_messages: 写入本轮所有 user/assistant/tool 消息（关联 session+report）
```

### 多轮研究对话（session_id 机制）
```
第1轮: POST reports/stream { query: "Agent工具调用设计", session_id: null }
  → 新建 ResearchSession(id=AAA)
  → 新建 FileReport(session_id=AAA, version=1)
  → thread_id=AAA → checkpoint 新建
  → 检索 → 生成报告 V1
  → 流式结束后:
      research_messages 写入 user消息(report_id=V1) + assistant消息 + tool消息
      file_reports: status=success, report_md="..."

第2轮: POST reports/stream { query: "安全方面呢？", session_id: AAA }
  → 复用 ResearchSession(id=AAA)
  → 新建 FileReport(session_id=AAA, version=2)
  → thread_id=AAA → LangGraph 从 pg 恢复 messages State
  → LLM 看到第1轮的所有检索结果和报告（因为 checkpoint 里有完整 messages）
  → "那安全方面呢？" → 基于历史继续检索
  → 生成报告 V2
  → research_messages 追加新的消息（report_id=V2）

第3轮: POST reports/stream { query: "联网验证一下", session_id: AAA }
  → thread_id=AAA → 恢复前两轮的完整 messages
  → LLM 调用 search_web → 综合前两轮本地检索结果 + 新联网结果
  → file_reports(version=3)

一个 ResearchSession 下有多版 FileReport
  ↓ 前端展示:
  Session "Agent工具调用设计分析"
    ├── Report V1 — 工具调用设计分析
    ├── Report V2 — 安全防护补充
    └── Report V3 — 联网验证版
  每份 report 的 research_messages 可追溯对话过程和引用来源
```

---

## 7. 关键技术细节

### LazyAsyncPostgresSaver（graph.py:67-83）
```
Chat App 和 Research App 共享同一个 checkpointer 对象。
LazyAsyncPostgresSaver 延迟创建真正的 AsyncPostgresSaver：
  - import 时不连库
  - 首次调用 setup() 时才初始化
  - 两个图读写同一张 checkpoints 表，但 State 互不冲突
    （LangGraph 内部用图的 hash 做 namespace 隔离）
```

### RunnableConfig 注入 user_id（retriever.py:103）
```
router 构建 config:
  configurable = {
    "thread_id": session_id,
    "user_id": user_id,       ← 注入
    "document_ids": [fid...]   ← 注入
  }

工具函数:
  async def search_document_by_vector(query, config: RunnableConfig):
    user_id = config["configurable"]["user_id"]   ← 取出
    stmt.where(FileChunk.user_id == user_id)       ← 隔离

全程 user_id 不进入 prompt，不暴露在 URL，通过框架内部传递。
```

### 文件检索的 agentic 本质
```
传统 RAG: query → embed → search → generate（一次性确定流程）
Agentic RAG: query → LLM决定 → search → LLM评估 → 不满意就换工具/换关键词再搜 → generate

你的 Research Graph 就是 agentic retrieval——LLM 自主决定：
  - 要不要搜索（也可能直接回答）
  - 用哪个工具（vector / grep / web）
  - 搜几轮才停止（loop 直到无 tool_calls）
  - 怎么组织报告（SystemMessage 约束引用格式）
```

---

## 8. 测试矩阵

| 测试文件 | 覆盖 | 状态 |
|---|---|---|
| `test_file_parser.py` | 文件名校验、解码、大小限制、chunk 逻辑 | ✅ 7 |
| `test_file_chunk_line.py` | 行号计算、空白边界 | ✅ 2 |
| `test_file_indexing_service.py` | 后台全链路入库 | ✅ 1 |
| `test_file_retriever.py` | Grep + 异步 Tool 测试 | ✅ 1 |
| `test_file_research_api.py` | 权限隔离、报告生成 | ❌ 待创建 |

---

## 9. 面试叙事

> "我做的是一个面向个人知识库的文件检索报告 Agent。核心差异化有三点：
>
> **双通道检索**：向量语义搜索（概念理解）+ Grep 精确匹配（变量名/函数名/配置项）。这和 Claude Code 的 hybrid retrieval 策略一致。
>
> **分层记忆系统**：聊天记忆存 `messages` 表（带 embedding 做长期语义检索），文件检索历史存 `research_messages` 表（关联 session + report）。物理隔离确保闲聊不会污染研究报告的证据链。
>
> **Agentic RAG 而不是传统 RAG**：LLM 自主决定调用哪个工具、搜几轮、什么时候停。不是'搜一次就生成'的固定流水线。
>
> **安全工程落地**：所有 DB 查询强制 user_id 多租户隔离；文件上传感知路径穿越；fetch_url 有 DNS 级别的 SSRF 防护。前端 `marked` 输出经 DOMPurify sanitize。
>
> **可追溯引用**：切块时记录物理行号，LLM 生成的报告中每个结论标注文件名+行号。前端通过 `/file-research/files/{id}/content` 加载全文并在侧边栏高亮跳转。"

---

## 10. 行业对标

| 你的设计 | 对标 | 来源 |
|---|---|---|
| 双通道检索 (Vector + Grep) | Claude Code hybrid retrieval | Anthropic: Context Engineering (2025.09) |
| Agent = LLM + tools in a loop | Anthropic 官方 Agent 定义 | Building Effective Agents (2024.12) |
| Chunk + top_k 控制上下文 | "Context as finite resource" | 同上 |
| interrupt_before 工具审批 | Human-in-the-loop 标准模式 | LangGraph 官方 |
| agentic retrieval (LLM 自主决定搜索策略) | LangGraph Agentic RAG tutorial | LangChain docs |

---

## 11. v2 规划

- **人机审批中断**（planner 后审批提纲、researcher 后筛选来源）
- **Monaco Editor 侧边栏**（点击报告中的来源引用 → 高亮跳转原文行）
- **多智能体协作**（Orchestrator → 文件检索 sub-agent + 联网 sub-agent）
- **Docker Compose** 一键部署
- **前端 FileResearchView** 完整页面
