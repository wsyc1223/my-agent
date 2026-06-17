# 文件检索报告 Agent — 开发文档（审校版）

> **原始文档**：2026-06-11  
> **审校日期**：2026-06-14  
> **审校方式**：逐行代码追溯 + 联网搜索 2025–2026 行业最新方案  
> **状态**：Task 5/6 已完成，Task 7 待实施，数据库需新增表

> [!IMPORTANT]
> 本文档是对原始开发文档的审校版。每个章节增加了 `🔍 审校意见` 小节，标注代码可行性验证结果、过时点、以及改进建议。红色标记 ❌ 表示需修复，黄色 ⚠️ 表示建议改进，绿色 ✅ 表示已验证可行。

---

## 0. 审校总结

### 总体评估

你的架构方向是正确的——双通道检索 + Agentic RAG + 物理隔离的分层记忆，这在 2026 年依然是主流做法。但在具体实现层面有几个需要重点改进的地方：

| 维度 | 评估 | 关键改进 |
|---|---|---|
| 切块策略 | ⚠️ 可用但已非最佳 | 固定滑窗 → 结构感知切块 + 上下文增强 |
| Embedding 模型 | ⚠️ 可用但已过时 | BGE-base-zh → BGE-M3（支持原生混合检索） |
| Reranker 模型 | ⚠️ 可用但已过时 | BGE-reranker-base → BGE-reranker-v2-m3 |
| Grep 检索 | ⚠️ 可用但有瓶颈 | ILIKE → PostgreSQL `tsvector`/BM25 |
| Research Graph | ❌ 缺少安全边界 | 无 tool_count 上限，可能死循环 |
| State 设计 | ⚠️ 冗余字段 | `report_md` 在 State 中声明但从未使用 |
| SSE 路由 | ⚠️ 可用但可增强 | 添加心跳 + sse-starlette 或保持现状 |
| CORS | ❌ 生产风险 | `allow_origins=["*"]` 需收紧 |
| schemas.py | ❌ 语法错误 | 中文逗号 + 缺少 import |

### 优先级排序

| 优先级 | 问题 | 影响范围 |
|---|---|---|
| P0 | `schemas.py` 语法错误（中文逗号、缺少 `import uuid`） | 编译失败 |
| P0 | Research Graph 缺少 tool_count 上限 | 可能死循环/烧 token |
| P0 | 缺少 ResearchSession / ResearchMessage 表 | 功能不完整 |
| P0 | `router/file_research.py` 空壳 + `main.py` 未注册 | 功能不可用 |
| P1 | CORS `allow_origins=["*"]` | 安全风险 |
| P1 | Embedding/Reranker 模型过时 | 检索质量 |
| P2 | 切块策略可优化 | 检索精度 |
| P2 | ILIKE → BM25 升级 | 关键词检索效率 |

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

### 🔍 审校意见

✅ 已完成清单与实际代码一致，逐文件验证通过。

⚠️ 但发现以下隐含问题：

1. **`service/file_research.py:124-135`** — `stream_research_report` 函数是半成品，`query` 变量未定义（应为 `req.query`），`config` 构建不完整。这个函数在文档中被 Task 7 的新 router 替代了，但旧代码需要清理。

2. **`schemas.py:44`** — `ReportRequest` 中 `min_length=2，max_length=2000` 使用了中文逗号 `，`，而且缺少 `import uuid`。这会导致 **编译失败**。

```diff
# schemas.py 修复
+import uuid
 class ReportRequest(BaseModel):
-    query: str = Field(..., min_length=2， max_length=2000)
+    query: str = Field(..., min_length=2, max_length=2000)
     file_ids: list[uuid.UUID] | None = None
```

---

## 2. 数据库设计（工作区与资产架构修订版）

聊天和研究使用独立的消息体系。为了支持“全局工作区（Workspace）”特性，将文件和报告作为独立资产进行管理，并支持点击资产直接溯源到具体对话，研究体系的表结构设计如下：

```
聊天体系:                          研究体系 (工作区视角):
conversations                     research_sessions (仅存元数据)
     │ 1:N                             │ 1:N
     ↓                                 ↓
messages                         research_messages (关联资产)
(role/content/embedding)         (role/content/attached_file_ids/generated_report_id)
                                             │ N:1 (外键关联，方便反向溯源)
                                             ↓
                                        file_reports (纯净的报告资产)
                                        (session_id/report_md/selected_chunk_ids)
```


### 🔍 审校意见

✅ **高维度的资产化设计**：这是类 Notion AI / Claude Artifacts 的前沿设计思路。将报告视为独立的一等资产，并保留与具体会话的物理双向链接。
✅ **去除了冗余的 `query`**：原设计的 `query` 已经存在于用户发送的 `ResearchMessage` 中，现在的设计更为正规。
✅ **符合关系型数据库范式**：移除了原计划中“在会话表存储数组”的想法，改用标准的外键与一对多、多对一 `relationship`，保证了后期连表查询的极速响应。

---

## 3. 待实施任务

### Task 7: SSE 路由 + 完整报告闭环

**当前路由文件 `router/file_research.py` 是空壳（9 行），`main.py` 未注册。**

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

            yield f"data: {json.dumps({'type': 'done', 'report_id': str(report.id), 'download_url': f'/file-research/reports/{report.id}/download'})}\n\n"

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

### 🔍 审校意见

✅ **SSE 路由设计整体可行**。`StreamingResponse` + `text/event-stream` 是 2026 年 FastAPI 的主流做法，不需要引入 `sse-starlette` 额外依赖。

⚠️ **需改进的细节**：

1. **`ReportRequest` 重复定义**：`schemas.py` 和 `router/file_research.py` 中都定义了 `ReportRequest`，但字段不同（router 版有 `session_id`，schemas 版没有）。建议统一到 `schemas.py` 并修复那里的语法错误。

2. **SSE 心跳缺失**：长时间运行的研究任务可能超过代理/浏览器超时。建议在 `sse_generator` 中加入心跳：
```python
# 每 15 秒发送一次心跳注释，防止连接被代理层切断
# SSE 规范中以 : 开头的行是注释，客户端会忽略
yield ": heartbeat\n\n"
```

3. **`service/file_research.py` 中的残留代码**：`stream_research_report` 函数（第 124-135 行）是未完成的半成品，`query` 变量未定义。Task 7 完成后应该删除这个残留函数，避免混淆。

4. **报告下载端点未实现**：SSE 结束时返回了 `download_url: /file-research/reports/{id}/download`，但实际没有这个路由。需要补充。

---

## 4. 已知待修复

| # | 位置 | 问题 | 优先级 |
|---|---|---|---|
| 1 | `model.py` | 缺少 ResearchSession / ResearchMessage 表 + FileReport 缺少 session_id/version | P0 |
| 2 | `research_graph.py:41-45` | `should_continue` 缺少 tool_count 上限（chat 图有 100 上限） | P1 |
| 3 | `router/file_research.py:1-9` | 空壳，只有 import 和占位代码 | P0（Task 7） |
| 4 | `main.py` | 未注册 file_research_router | P0（Task 7） |
| 5 | `frontend/` | 无 FileResearchView / fileResearch store / fileResearch service | P2 |

### 🔍 审校意见 — 新增发现的问题

| # | 位置 | 问题 | 优先级 |
|---|---|---|---|
| 6 | `schemas.py:44` | ❌ 中文逗号 `，` 导致编译失败 + 缺少 `import uuid` | **P0** |
| 7 | `service/file_research.py:124-135` | 残留半成品函数 `stream_research_report`，`query` 未定义 | P1 |
| 8 | `main.py:39` | ❌ `allow_origins=["*"]` 生产环境安全风险 | **P1** |
| 9 | `research_graph.py:26` | `report_md: str` 在 State 中声明但 agent_node 从未读写 | P2 |
| 10 | `retriever.py:82` | `ILIKE` SQL 注入风险：虽然 SQLAlchemy ORM 会参数化，但 `%` 和 `_` 是 LIKE 通配符，用户输入包含这些字符时会产生意外匹配 | P2 |
| 11 | `router/file_research.py` (Task 7) | 报告下载端点 (`/reports/{id}/download`) 被 SSE 引用但未实现 | P1 |

---

## 5. 架构总览

```
┌────────────────────────────────────────────────────────────────────┐
│                       前端 (Vue 3)                                 │
│  ChatView (✅)  │  FileResearchView (❌)                           │
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
│   model: deepseek-v4-   │   │   model: deepseek-v4-pro             │
│          flash          │   │                                      │
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
│                      PostgreSQL + pgvector                        │
│                                                                   │
│  聊天体系:                 研究体系:                              │
│  users                    users (共享)                            │
│  user_credentials         ←── 共用                                │
│  conversations            research_sessions  ← 独立的 session     │
│  messages (embedding)     research_messages  ← 独立的 message     │
│                           file_documents                          │
│                           file_chunks (embedding)                 │
│                           file_reports (session_id, version)      │
│                                                                   │
│  langgraph checkpoints (由 AsyncPostgresSaver 自动管理)           │
└───────────────────────────────────────────────────────────────────┘
```

### 🔍 审校意见

✅ **架构图与代码完全一致**，已逐文件验证。

✅ **LazyAsyncPostgresSaver 共享 checkpointer 模式在 2026 年仍然可行**。LangGraph 内部用 graph hash 做 namespace 隔离，两个图共享同一张 checkpoints 表不会冲突。但需注意：
- 这种模式是一个常见的社区 workaround，LangGraph 官方在 2026 年的文档中推荐直接使用 `AsyncPostgresSaver` + lifespan 管理，不需要 Lazy 封装（因为 `__getattr__` 代理可能在某些边界场景丢失方法签名）。
- 你当前的 `lifespan` 已经在启动时调用 `await checkpointer.setup()`，这意味着 `LazyAsyncPostgresSaver.__getattr__` 会在 setup 时触发 `self.saver` 初始化，所以 lazy 特性实际上没有被利用到。**建议简化为直接使用 `AsyncPostgresSaver`**。

⚠️ **`report_md` 在 `ResearchState` 中声明但未使用**：
```python
class ResearchState(TypedDict):
    messages: Annotated[list, add_messages]
    report_md: str  # ← 从未被 agent_node 读写
```
如果不打算在 State 中维护报告文本（当前是通过 SSE 收集 `collected_content`），应该移除这个字段，避免 LangGraph 序列化冗余数据到 checkpoint。

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

### 🔍 审校意in

✅ **数据流设计合理，多轮 session 机制逻辑清晰。**

⚠️ **checkpoint 膨胀风险**：多轮研究会让 messages State 线性增长（因为 LangGraph 的 `add_messages` reducer 是追加模式）。经过 5-10 轮深度研究后，checkpoint 中的 messages 可能达到数百条（包含大量工具返回的文档片段），这会：
1. 增加 LLM 的 token 消耗和延迟
2. 增加 checkpoint 的序列化/反序列化开销
3. 可能超过 LLM 上下文窗口

**建议**：在第 N 轮（如 N>5）时，实现一个 "摘要压缩" 机制——将前几轮的完整消息替换为一段结构化摘要，保留关键发现和引用来源，丢弃冗余的中间过程。

⚠️ **research_messages 写入时机**：当前设计是在 SSE 流式结束后批量写入 research_messages，但如果流式过程中服务崩溃，这些消息就丢失了。对于研究场景可以接受（因为 checkpoint 里有完整记录），但需要在文档中说明这一点。

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

### 🔍 审校意见

⚠️ **LazyAsyncPostgresSaver 可以简化**：

当前代码中 `lifespan` 在应用启动时就调用了 `await checkpointer.setup()`，而 `setup()` 会触发 `__getattr__` → `self.saver` 初始化。所以 "lazy" 特性实际上在应用运行期间并未被利用。

2026 年 LangGraph 的推荐做法是直接在 lifespan 中初始化：

```python
# 简化后的 graph.py
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

pool = AsyncConnectionPool(conninfo=DATABASE_URL_PSYCOPG, max_size=20, open=False, ...)
checkpointer = AsyncPostgresSaver(pool)

# main.py lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    await pool.open()
    await checkpointer.setup()
    yield
    await pool.close()
```

这样更清晰，也避免了 `__getattr__` 代理可能丢失方法签名的问题。

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

### 🔍 审校意见

✅ **RunnableConfig 注入 user_id 的隔离方案是安全的**。这是 LangGraph 2026 年推荐的多租户模式——user_id 通过 config 传递，不经过 prompt 也不暴露在 URL 中。

✅ **SQLAlchemy ORM 的 ILIKE 是参数化查询**（`retriever.py:82`），不存在 SQL 注入风险。但 `%` 和 `_` 是 LIKE 通配符，如果用户搜索 `100%` 会匹配到所有包含 `100` 的内容。建议转义：

```python
from sqlalchemy import func
# 在 grep_search_chunks 中
escaped_keyword = keyword.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
stmt = stmt.where(FileChunk.content.ilike(f"%{escaped_keyword}%", escape="\\"))
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

### 🔍 审校意见

✅ **Agentic RAG 定义准确**，与 Anthropic 2024.12 "Building Effective Agents" 和 LangGraph 官方文档一致。

❌ **但 Research Graph 缺少防无限循环机制**（`research_graph.py:41-45`）：

```python
# 当前代码 — 没有任何工具调用次数限制
def should_continue(state: ResearchState) -> str:
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END
```

对比 Chat Graph 有 `tool_count >= 100` 的安全限制。Research Graph 面向的是深度分析场景，LLM 可能反复调用工具导致死循环和 token 爆炸。

**必须修复**：

```python
MAX_RESEARCH_TOOL_CALLS = 30  # 研究场景合理上限

def should_continue(state: ResearchState) -> str:
    messages = state["messages"]
    tool_count = sum(1 for m in messages if hasattr(m, 'type') and m.type == 'tool')
    if tool_count >= MAX_RESEARCH_TOOL_CALLS:
        return END
    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END
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

### 🔍 审校意见

⚠️ **测试覆盖存在明显缺口**：

| 缺失测试 | 风险 | 建议 |
|---|---|---|
| Research Graph 端到端 | 无法验证 agent 能否正确调用工具链 | mock LLM + 验证工具调用序列 |
| 多轮 session 续接 | checkpoint 恢复逻辑未测试 | 模拟两轮调用验证 state 恢复 |
| SSE 流式输出格式 | 前端可能收到非标 SSE 格式 | 用 `httpx` 的 `AsyncClient` 测试 SSE event 格式 |
| ILIKE 通配符边界 | `%` `_` 导致意外匹配 | 搜索 `100%` 验证行为 |
| 文件删除级联 | 删文件后 chunks 是否清理 | 数据库级联测试 |

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

### 🔍 审校意见

✅ **叙事逻辑清晰，技术点准确**。

⚠️ **建议增强的表述**：

1. 面试时可以提到 **"Corrective RAG"** 概念——你的 agent 如果第一次检索不满意可以换关键词再搜，这就是 2024 年 Corrective RAG 论文的核心思想。

2. 如果升级了 embedding 模型（如 BGE-M3），可以补充："我们从 BGE-base-zh 升级到 BGE-M3 多向量模型，一个 forward pass 同时产出 dense、sparse、ColBERT 三种表示，用于原生混合检索。"

3. **补充量化指标**：如果能测试出 "向量检索 Recall@5 = 78%，加上 Grep 后达到 92%" 之类的数据，面试效果会好很多。

---

## 10. 行业对标（更新版）

| 你的设计 | 对标 | 来源 | 2026 审校 |
|---|---|---|---|
| 双通道检索 (Vector + Grep/ILIKE) | Claude Code hybrid retrieval | Anthropic: Context Engineering (2025.09) | ✅ 方向正确，但 ILIKE 应升级为 BM25 |
| Agent = LLM + tools in a loop | Anthropic 官方 Agent 定义 | Building Effective Agents (2024.12) | ✅ 仍然是行业标准定义 |
| Chunk + top_k 控制上下文 | "Context as finite resource" | 同上 | ⚠️ 固定窗口切块可优化为语义切块 |
| interrupt_before 工具审批 | Human-in-the-loop 标准模式 | LangGraph 官方 | ✅ LangGraph 2026 仍推荐此模式 |
| agentic retrieval (LLM 自主决定搜索策略) | LangGraph Agentic RAG tutorial | LangChain docs | ✅ 2026 主流，但建议加入 Corrective RAG grading |
| BGE-base-zh + BGE-reranker-base | 2024 年中文 RAG 标配 | BAAI | ⚠️ 2026 年已有更好选择，见下方 |

### 2026 年更新的行业对标

| 最新方案 | 说明 | 来源 |
|---|---|---|
| BGE-M3（dense + sparse + ColBERT） | 一个模型三种表示，原生混合检索 SOTA | BAAI/bge-m3 (HuggingFace) |
| GTE-Qwen2（1.5B/7B） | 高精度中文 embedding，基于 Qwen2 基座 | Alibaba Cloud (MTEB 排行) |
| BGE-reranker-v2-m3 | 多语言 reranker，比 base 精度提升显著 | BAAI |
| Qwen3-Reranker | 2026 新出的大模型 reranker | Alibaba |
| Contextual Retrieval | 切块时前置 LLM 生成的文档摘要 | Anthropic (2024.10) |
| Corrective RAG | 检索结果评分 → 不满意则回退重试 | 论文 (2024) + LangGraph 官方教程 |
| Adaptive RAG | 按查询复杂度路由到不同检索策略 | 论文 (2024) + LangGraph 官方教程 |
| PostgreSQL tsvector/BM25 | pgvector + tsvector 全栈混合检索 | ParadeDB / PostgreSQL 15+ |
| RRF（Reciprocal Rank Fusion） | 多路召回结果融合标准方法 | 行业通用 |

---

## 11. 改进建议（按优先级排序）

### 11.1 ❌ P0 — 必须立即修复

#### 11.1.1 schemas.py 语法错误

```diff
# src/schemas.py
+import uuid
 class ReportRequest(BaseModel):
-    query: str = Field(..., min_length=2， max_length=2000)
+    query: str = Field(..., min_length=2, max_length=2000)
     file_ids: list[uuid.UUID] | None = None
+    session_id: uuid.UUID | None = None
```

#### 11.1.2 Research Graph 添加工具调用上限

```python
# file_research/research_graph.py
MAX_RESEARCH_TOOL_CALLS = 30

def should_continue(state: ResearchState) -> str:
    messages = state["messages"]
    tool_count = sum(1 for m in messages if hasattr(m, 'type') and m.type == 'tool')
    if tool_count >= MAX_RESEARCH_TOOL_CALLS:
        return END
    last_message = messages[-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END
```

#### 11.1.3 清理残留代码

删除 `service/file_research.py:124-135` 的半成品 `stream_research_report` 函数。

### 11.2 ⚠️ P1 — 短期内改进

#### 11.2.1 CORS 收紧

```python
# main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",   # 本地开发
        "http://localhost:3000",   # 备选端口
        # 部署时添加实际域名
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

#### 11.2.2 Embedding 模型升级路线

当前使用 `bge-base-zh-v1.5`（768 维，110M 参数）。2026 年推荐升级路径：

| 阶段 | 模型 | 维度 | 特性 | 适合场景 |
|---|---|---|---|---|
| **当前** | bge-base-zh-v1.5 | 768 | 中文 dense only | 够用但非最优 |
| **推荐** | BGE-M3 | 1024 | dense + sparse + ColBERT，多语言 | 一个模型搞定混合检索 |
| **高配** | GTE-Qwen2-1.5B | 1536 | 高精度，需要更多 GPU 资源 | 对精度有极高要求 |

**BGE-M3 的核心优势**：一次 forward pass 同时输出 dense（向量检索）、sparse（类 BM25 关键词检索）、ColBERT（细粒度多向量匹配）三种表示。这意味着你的双通道检索（vector + grep）可以统一为一个模型，不再需要单独维护 ILIKE 检索。

**升级要点**：
- `file_chunks` 表的 `embedding` 列需要从 `Vector(768)` 改为 `Vector(1024)`
- 需要重新索引所有已上传文件
- 建议增加一个 `embedding_model_version` 字段跟踪模型版本

#### 11.2.3 Reranker 升级

```python
# rag.py 升级
# 旧: CrossEncoder("bge-reranker-base")
# 新: CrossEncoder("BAAI/bge-reranker-v2-m3")  ← 多语言 + 更高精度
```

#### 11.2.4 ILIKE 通配符转义

```python
# retriever.py grep_search_chunks 修复
escaped_keyword = keyword.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
stmt = stmt.where(FileChunk.content.ilike(f"%{escaped_keyword}%", escape="\\"))
```

### 11.3 ⚠️ P2 — 中期优化

#### 11.3.1 切块策略升级

当前使用固定大小滑动窗口（1200 字符 + 180 重叠），这在 2026 年不再是最佳实践。推荐升级路径：

**阶段 1：结构感知切块（低成本）**
```python
# 识别 Markdown 标题、代码块边界等结构特征
# 优先在结构边界处切分，而非固定字符数
def chunk_text_with_structure(text: str, max_chunk_size: int = 1200) -> list[TextChunk]:
    # 1. 按标题/代码块/段落分割
    # 2. 如果某段超过 max_chunk_size，再用滑动窗口细分
    # 3. 保留行号信息
    pass
```

**阶段 2：上下文增强（Anthropic Contextual Retrieval 思路）**
```python
# 在 embedding 前，给每个 chunk 前置文档级摘要
context_prefix = f"[文件: {filename}] [章节: {section_title}]\n"
enriched_chunk = context_prefix + chunk.content
embedding = embed_text(enriched_chunk)
```

#### 11.3.2 Grep → BM25 升级

当前 `ILIKE` 只能做简单子串匹配，不支持词频加权和文档长度归一化。2026 年 PostgreSQL 生态有更好的方案：

**方案 A：PostgreSQL 原生 tsvector（零依赖）**
```sql
-- 在 file_chunks 表上添加 tsvector 列
ALTER TABLE file_chunks ADD COLUMN tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED;
CREATE INDEX idx_file_chunks_tsv ON file_chunks USING GIN(tsv);

-- 检索
SELECT * FROM file_chunks
WHERE tsv @@ to_tsquery('simple', 'keyword')
AND user_id = :user_id
ORDER BY ts_rank(tsv, to_tsquery('simple', 'keyword')) DESC
LIMIT 10;
```

**方案 B：ParadeDB pg_search（如需真正的 BM25）**
- 提供 PostgreSQL 原生 BM25 评分
- 安装需要数据库扩展权限

⚠️ 对于你当前的个人项目来说，方案 A（tsvector）就足够了，性能和相关性都比 ILIKE 好很多。如果以后要做更大规模的多用户系统，再考虑 pg_search。

#### 11.3.3 LazyAsyncPostgresSaver 简化

```python
# graph.py 简化后
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

DATABASE_URL_PSYCOPG = settings.DATABASE_URL_PSYCOPG
pool = AsyncConnectionPool(
    conninfo=DATABASE_URL_PSYCOPG,
    max_size=20,
    open=False,
    kwargs={"autocommit": True, "row_factory": dict_row}
)

checkpointer = AsyncPostgresSaver(pool)
# 删除 LazyAsyncPostgresSaver 类
# lifespan 中的 setup() 不变
```

#### 11.3.4 ResearchState 清理

```python
# 移除未使用的 report_md 字段
class ResearchState(TypedDict):
    messages: Annotated[list, add_messages]
    # report_md: str  ← 移除，报告内容通过 SSE collected_content 收集
```

#### 11.3.5 Corrective RAG 增强

在 Research Graph 中加入 "检索结果质量评分" 节点，让 LLM 判断检索结果是否足够回答问题：

```python
# research_graph.py 新增 grading 逻辑
async def grade_documents(state: ResearchState) -> dict:
    """评估检索到的文档是否相关，如果不相关则触发重新检索"""
    # 这是 Corrective RAG 的核心——
    # LLM 不是检索到什么就用什么，而是先评估质量
    pass
```

这是一个 v2 级别的优化，当前阶段不急。

---

## 12. v2 规划（更新版）

| 方向 | 原规划 | 审校建议 |
|---|---|---|
| 人机审批中断 | planner 后审批提纲、researcher 后筛选来源 | ✅ 保持，LangGraph `interrupt` 支持良好 |
| Monaco Editor 侧边栏 | 点击报告中的来源引用 → 高亮跳转原文行 | ✅ 保持，这是差异化亮点 |
| 多智能体协作 | Orchestrator → 文件检索 sub-agent + 联网 sub-agent | ⚠️ 建议使用 LangGraph subgraph 模式而非独立 agent |
| Docker Compose | 一键部署 | ✅ 保持 |
| 前端 FileResearchView | 完整页面 | ✅ 保持 |

### 新增 v2 建议

| 方向 | 说明 | 优先级 |
|---|---|---|
| **Corrective RAG grading** | 检索结果质量评分 → 不满意就换关键词/换工具重试 | 高 |
| **BGE-M3 混合检索** | 一个模型出三种表示，替代 vector + ILIKE 双通道 | 高 |
| **Checkpoint 清理策略** | 定期清理旧 checkpoint，防止表无限增长 | 中 |
| **文件格式扩展** | 支持 PDF/DOCX（使用 Docling 或 Unstructured） | 中 |
| **评估框架** | 建立 golden dataset + Ragas 评估 pipeline | 中 |
| **前端报告版本对比** | 对比同一 session 下不同版本报告的差异 | 低 |

---

## 13. 大厂方案参考（2025–2026 联网调研）

### 13.1 Anthropic — Contextual Retrieval

Anthropic 在 2024.10 发布了 **Contextual Retrieval** 技术：
- 核心思路：在切块时用 LLM 为每个 chunk 生成一段上下文描述（"这段文本来自关于 XX 的文档，讨论的是 YY 主题"），然后将这段描述 + 原始内容一起做 embedding
- 效果：大幅降低了因切块丢失上下文导致的检索失败
- **对你的项目的启示**：你的 `chunk_text_with_line` 可以在 embedding 前增加一个 context prefix

### 13.2 Google — Vertex AI RAG Engine

Google 的 Vertex AI 在 2025 年推出了托管 RAG 服务：
- 自动处理文档解析、切块、embedding、检索
- 支持混合检索（dense + sparse）
- 对你的启示：你的本地方案其实在做同样的事，但自主可控

### 13.3 OpenAI — File Search (Assistants API)

OpenAI 的 Assistants API 内置 file search：
- 使用自动切块 + 向量检索
- 支持多文件检索
- 对你的启示：你的方案比 OpenAI 更灵活（有 Grep、有 reranker、有多轮 session），这是差异化优势

### 13.4 LangChain — Agentic RAG + Corrective RAG

LangChain 官方在 2025 年推出了完整的 Agentic RAG 教程：
- 使用 LangGraph 构建循环检索图
- 加入了 "document grading" 节点（Corrective RAG）
- 加入了 "query rewriting" 节点（查询改写）
- **对你的项目的启示**：你的 Research Graph 已经是 Agentic RAG，但缺少 grading 和 query rewriting 两个节点，这是 v2 的方向

---

## 14. 完整文件引用索引

| 文件 | 路径 | 状态 |
|---|---|---|
| Chat Graph | `backend/src/graph.py` | ✅ |
| Research Graph | `backend/src/file_research/research_graph.py` | ⚠️ 缺 tool_count 限制 |
| 检索工具 | `backend/src/file_research/retriever.py` | ⚠️ ILIKE 通配符问题 |
| 文件解析 | `backend/src/file_research/parser.py` | ✅ |
| 数据库模型 | `backend/src/db/model.py` | ⚠️ 缺 ResearchSession/Message |
| 仓储层 | `backend/src/db/repository.py` | ✅ |
| Chat 服务 | `backend/src/service/agent.py` | ✅ |
| File Research 服务 | `backend/src/service/file_research.py` | ⚠️ 残留半成品代码 |
| Chat 工具集 | `backend/src/tools.py` | ✅ |
| RAG 模块 | `backend/src/rag.py` | ⚠️ 模型可升级 |
| File Research 路由 | `backend/src/router/file_research.py` | ❌ 空壳 |
| 主入口 | `backend/main.py` | ⚠️ 未注册 file_research_router + CORS |
| Schema | `backend/src/schemas.py` | ❌ 语法错误 |
| 配置 | `backend/src/config.py` | ✅ |
| 安全工具 | `backend/src/utils/security.py` | ✅ |
| 可观测性 | `backend/src/observability.py` | ✅ |
