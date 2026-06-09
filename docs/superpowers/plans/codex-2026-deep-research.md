# 文件检索报告 Agent 立即执行方案

> 创建日期：2026-06-06
> 目标读者：当前项目的实现者，也就是你自己。
> 方案定位：替换原 `2026-06-05-deep-research.md` 中过大的联网深度研究方案，先做一个能落地、能演示、能面试讲清楚的“文件检索 Agent”。

## 1. 当前项目结论

我已经按当前仓库读取了后端、前端、数据库、Agent、RAG、工具、认证、迁移和 `question.md`。当前项目已经具备这些基础：

- 后端：FastAPI、JWT 登录、SQLAlchemy AsyncSession、Alembic、PostgreSQL、pgvector。
- Agent：`backend/src/graph.py` 已有 LangGraph 状态图，使用 `AsyncPostgresSaver` 做 checkpoint。
- 工具：`backend/src/tools.py` 有 `search_web`、`fetch_url`、天气、计算器、当前时间。
- RAG：`backend/src/rag.py` 已有本地 BGE embedding、BGE reranker、`messages.embedding` 向量检索。
- 前端：Vue 3、Pinia、Vite，已有 SSE 读取逻辑、Markdown 渲染、登录和聊天页面。

当前项目还没有这些能力：

- 没有文件上传接口。
- 没有文件表、文件 chunk 表、文件报告任务表。
- 没有面向文件内容的检索 API。
- 没有文件检索独立页面。
- 没有 Markdown 报告下载接口。
- 没有 `backend/tests/` 测试目录。

所以这次不要继续做“联网深度研究”。应该先做“用户上传文件 -> 系统切块入库 -> 用户输入检索问题 -> 后端检索相关 chunk -> LLM 生成 Markdown 报告 -> 前端下载”的闭环。

## 2. 功能范围

### 2.1 MVP 必须完成

1. 用户上传文本类文件。
2. 后端解析文本，切成 chunk，生成 768 维向量并写入 PostgreSQL。
3. 用户输入“想要检索的内容”。
4. 后端从当前用户上传的文件 chunk 中检索最相关内容。
5. 后端调用 LLM 生成一份 Markdown 报告。
6. 前端展示报告，并提供 `.md` 下载按钮。

### 2.2 第一版支持的文件类型

只支持能直接解析为文本的文件：

- `.txt`
- `.md`
- `.py`
- `.ts`
- `.vue`
- `.js`
- `.json`
- `.html`
- `.css`
- `.log`
- `.csv`

第一版不要做 PDF、Word、Excel。原因很简单：当前项目没有 `pypdf`、`python-docx`、`openpyxl`，而文件检索 Agent 的核心竞争力不是“支持所有格式”，而是“检索、引用、生成报告的链路可靠”。

### 2.3 明确不做

- 不做联网搜索。
- 不做人机审批中断。
- 不做多文件夹同步。
- 不做复杂权限系统。
- 不做 PDF/Word 解析。
- 不把文件原文存到本地磁盘，第一版只把 chunk 文本存数据库。

## 3. 技术依据

- FastAPI 官方文件上传使用 `UploadFile`，接收表单文件需要安装 `python-multipart`。
- LangGraph 当前可以用 `stream_mode="updates" | "values" | "messages" | "custom"` 做流式事件。第一版为了降低风险，报告生成流式输出在 service 层直接做 SSE，不强依赖图内部 custom stream。
- 当前项目已有 `embed_text()` 和 `search_messages()`，但 `embed_text()` 是同步 CPU/模型推理调用，放在 FastAPI 协程里必须用 `asyncio.to_thread()`。

## 4. 推荐架构

### 4.1 后端数据流

```text
UploadFile
  -> validate_file
  -> read_text
  -> chunk_text
  -> embed chunks
  -> insert file_documents + file_chunks

query
  -> embed query
  -> vector search file_chunks
  -> rerank chunks
  -> build prompt with citations
  -> stream Markdown report
  -> save file_reports.report_md
  -> download .md
```

### 4.2 文件职责

新增文件：

| 文件 | 职责 |
|---|---|
| `backend/src/file_research/parser.py` | 文件类型校验、文本读取、chunk 切分 |
| `backend/src/file_research/retriever.py` | 文件 chunk 向量检索和 rerank |
| `backend/src/file_research/reporter.py` | 构建 prompt，调用 LLM 生成 Markdown |
| `backend/src/service/file_research.py` | 上传、索引、检索报告、下载的业务编排 |
| `backend/src/router/file_research.py` | 文件检索 API 路由 |
| `backend/tests/test_file_parser.py` | 解析和切块单元测试 |
| `backend/tests/test_file_retriever.py` | 检索 SQL 和权限过滤测试 |
| `frontend/src/services/fileResearch.ts` | 前端 API 封装 |
| `frontend/src/stores/fileResearch.ts` | Pinia 状态管理 |
| `frontend/src/views/FileResearchView.vue` | 文件检索页面 |

修改文件：

| 文件 | 改动 |
|---|---|
| `backend/pyproject.toml` | 增加 `python-multipart` |
| `backend/src/db/model.py` | 增加 `FileDocument`、`FileChunk`、`FileReport` |
| `backend/src/db/repository.py` | 增加文件检索相关 Repository |
| `backend/src/schemas.py` | 增加文件检索请求/响应 schema |
| `backend/main.py` | 注册 `file_research_router` |
| `frontend/src/router/index.ts` | 增加 `/files` 路由 |
| `frontend/src/components/ChatSidebar.vue` | 增加“文件检索”入口 |
| `frontend/package.json` | 建议增加 `dompurify`，避免 Markdown HTML 注入风险 |

## 5. 数据库设计

在 `backend/src/db/model.py` 增加 3 张表。

```python
class FileDocument(Base):
    __tablename__ = "file_documents"
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=True)
    size_bytes = Column(BigInteger, nullable=False)
    sha256 = Column(String(64), nullable=False, index=True)
    status = Column(String(20), nullable=False, default="indexed")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User")
    chunks = relationship("FileChunk", back_populates="document", cascade="all, delete-orphan")


class FileChunk(Base):
    __tablename__ = "file_chunks"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    document_id = Column(UUID, ForeignKey("file_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(BigInteger, nullable=False)
    content = Column(Text, nullable=False)
    token_estimate = Column(BigInteger, nullable=False, default=0)
    embedding = Column(Vector(768), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    document = relationship("FileDocument", back_populates="chunks")


class FileReport(Base):
    __tablename__ = "file_reports"
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    query = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="running")
    report_md = Column(Text, nullable=True)
    selected_chunk_ids = Column(JSONB, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User")
```

迁移命令：

```bash
cd /home/wsyc1/projects/langchain/backend
uv run alembic revision --autogenerate -m "add file research tables"
uv run alembic upgrade head
```

## 6. API 设计

### 6.1 上传文件

```text
POST /file-research/files
Content-Type: multipart/form-data
Auth: Bearer token
field: file
```

返回：

```json
{
  "id": "uuid",
  "filename": "demo.md",
  "chunk_count": 12,
  "status": "indexed"
}
```

### 6.2 文件列表

```text
GET /file-research/files
Auth: Bearer token
```

### 6.3 生成检索报告

```text
POST /file-research/reports/stream
Auth: Bearer token
Content-Type: application/json
```

请求：

```json
{
  "query": "检索和 Agent 工具调用相关的内容，并整理成面试讲解稿",
  "file_ids": ["uuid-1", "uuid-2"],
  "top_k": 8
}
```

SSE 事件：

```json
{"type":"report_start","report_id":"uuid"}
{"type":"progress","message":"正在检索相关文件片段..."}
{"type":"sources","chunks":[{"chunk_id":1,"filename":"question.md","score":0.82}]}
{"type":"text","content":"# 文件检索报告\n\n"}
{"type":"done","report_id":"uuid","download_url":"/file-research/reports/uuid/download"}
```

### 6.4 下载报告

```text
GET /file-research/reports/{report_id}/download
Auth: Bearer token
```

返回 `text/markdown; charset=utf-8`，带 `Content-Disposition: attachment`。

## 7. 执行任务清单

### Task 0：先修当前项目的基础风险

- [ ] 新建 `backend/tests/` 目录。
- [ ] 把 `backend/src/service/agent.py` 中所有 `embed_text(...)` 改成 `await asyncio.to_thread(embed_text, ...)`。
- [ ] 修复拒绝多工具调用时只返回一个 `ToolMessage` 的问题。
- [ ] 给 `backend/src/rag.py::search_messages` 增加 `exclude_conversation_id`，避免当前会话污染。
- [ ] 不要用旧计划里的自证式测试，要测试真实函数行为。

### Task 1：安装上传依赖

```bash
cd /home/wsyc1/projects/langchain/backend
uv add python-multipart
```

如果后续要支持 PDF/Word，再单独加：

```bash
uv add pypdf python-docx
```

第一版先不要加。

### Task 2：增加数据库模型和迁移

- [ ] 修改 `backend/src/db/model.py`，增加 `FileDocument`、`FileChunk`、`FileReport`。
- [ ] 修改 `backend/src/db/repository.py`，增加 `FileDocumentRepository`、`FileChunkRepository`、`FileReportRepository`。
- [ ] 生成并执行 Alembic 迁移。
- [ ] 手动检查迁移脚本，不要把 checkpoint 表纳入迁移。

### Task 3：实现文件解析和切块

创建 `backend/src/file_research/parser.py`：

```python
from dataclasses import dataclass
from pathlib import Path

ALLOWED_SUFFIXES = {".txt", ".md", ".py", ".ts", ".vue", ".js", ".json", ".html", ".css", ".log", ".csv"}
MAX_FILE_BYTES = 5 * 1024 * 1024


@dataclass
class ParsedFile:
    filename: str
    text: str
    size_bytes: int


def validate_filename(filename: str) -> str:
    safe_name = Path(filename).name
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError(f"不支持的文件类型: {suffix}")
    return safe_name


def decode_text_file(filename: str, data: bytes) -> ParsedFile:
    safe_name = validate_filename(filename)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("文件超过 5MB 限制")
    text = data.decode("utf-8", errors="replace").strip()
    if not text:
        raise ValueError("文件内容为空")
    return ParsedFile(filename=safe_name, text=text, size_bytes=len(data))


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 180) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(normalized):
            break
        start = max(0, end - overlap)
    return chunks
```

### Task 4：实现上传索引服务

创建 `backend/src/service/file_research.py`，核心逻辑：

- 读取 `UploadFile` 的 bytes。
- `decode_text_file()` 校验和解码。
- `chunk_text()` 切块。
- 对每个 chunk 使用 `await asyncio.to_thread(embed_text, chunk)`。
- 写入 `file_documents` 和 `file_chunks`。
- 返回 chunk 数量。

### Task 5：实现文件检索

创建 `backend/src/file_research/retriever.py`：

- 查询必须包含 `user_id` 条件。
- 如果前端传 `file_ids`，必须同时校验这些文件属于当前用户。
- 先用 pgvector 召回 `top_k * 4`。
- 再用当前项目已有 `reranker_model.predict()` 重排。
- 返回 `chunk_id`、`filename`、`content`、`score`。

SQL 形态：

```sql
SELECT
  fc.id,
  fd.filename,
  fc.content,
  1 - (fc.embedding <=> cast(:qv as vector)) AS score
FROM file_chunks fc
JOIN file_documents fd ON fc.document_id = fd.id
WHERE fc.user_id = :user_id
  AND fc.embedding IS NOT NULL
ORDER BY fc.embedding <=> cast(:qv2 as vector)
LIMIT :limit
```

### Task 6：实现 Markdown 报告生成

创建 `backend/src/file_research/reporter.py`：

报告 Prompt 必须包含这些规则：

- 只允许基于检索到的文件片段回答。
- 每个关键结论后面标注来源，例如：`（来源：question.md #chunk-12）`。
- 如果证据不足，必须写“当前上传文件中没有足够证据确认”。
- 输出 Markdown。
- 报告结构固定为：标题、摘要、关键发现、详细分析、引用片段、下一步建议。

### Task 7：实现后端路由

创建 `backend/src/router/file_research.py`：

- `POST /file-research/files`
- `GET /file-research/files`
- `POST /file-research/reports/stream`
- `GET /file-research/reports/{report_id}`
- `GET /file-research/reports/{report_id}/download`

在 `backend/main.py` 注册：

```python
from src.router.file_research import router as file_research_router
app.include_router(file_research_router)
```

### Task 8：实现前端页面

新增：

- `frontend/src/services/fileResearch.ts`
- `frontend/src/stores/fileResearch.ts`
- `frontend/src/views/FileResearchView.vue`

页面布局：

- 左侧：已上传文件列表、上传按钮。
- 中间：检索问题输入框、开始生成按钮、进度日志。
- 右侧/下方：Markdown 报告预览、下载按钮。

下载按钮直接请求：

```ts
window.location.href = apiUrl(`/file-research/reports/${reportId}/download`)
```

如果需要带 JWT，不能直接用 `window.location.href`，应使用 `fetch` 获取 blob：

```ts
const res = await fetch(apiUrl(`/file-research/reports/${reportId}/download`), {
  headers: getAuthHeaders(),
})
const blob = await res.blob()
const url = URL.createObjectURL(blob)
const a = document.createElement('a')
a.href = url
a.download = `file-research-${reportId.slice(0, 8)}.md`
a.click()
URL.revokeObjectURL(url)
```

### Task 9：前端路由和侧边栏

修改 `frontend/src/router/index.ts`：

```ts
import FileResearchView from '@/views/FileResearchView.vue'

routes: [
  { path: '/', name: 'chat', component: ChatView },
  { path: '/files', name: 'file-research', component: FileResearchView },
  { path: '/login', name: 'login', component: AuthView },
]
```

修改 `ChatSidebar.vue` 增加入口：

```html
<button class="mode-btn" :class="{ active: $route.name === 'file-research' }" @click="router.push('/files')">
  文件检索
</button>
```

### Task 10：测试与验收

后端至少补这些测试：

- `test_chunk_text_keeps_overlap`
- `test_decode_text_file_rejects_unknown_suffix`
- `test_upload_file_creates_chunks`
- `test_retrieve_chunks_filters_by_user`
- `test_report_download_rejects_other_user`

执行：

```bash
cd /home/wsyc1/projects/langchain/backend
uv run pytest tests/ -v
```

前端执行：

```bash
cd /home/wsyc1/projects/langchain/frontend
npm run build-only
```

最后手动验收：

1. 注册/登录。
2. 打开 `/files`。
3. 上传 `question.md`。
4. 输入：`根据这个文件，总结 Agent 面试高频问题，并指出哪些说法和当前项目不一致。`
5. 看到报告流式生成。
6. 下载 `.md` 文件。
7. 打开下载文件，确认有标题、摘要、引用来源、下一步建议。

## 8. 面试讲法

这版功能可以这样讲：

> 我没有把文件直接塞进 prompt，而是做了一个文件级 RAG Agent。用户上传文件后，系统先做类型校验、文本解析、chunk 切分和向量化，存入 PostgreSQL + pgvector。用户提出检索目标后，后端用 query embedding 做召回，再用 reranker 做精排，最后把高相关片段交给 LLM 生成带来源引用的 Markdown 报告。报告通过 SSE 实时返回，最终支持下载。这个设计解决了上下文窗口爆炸、来源不可追溯、长任务无反馈和多用户数据隔离问题。

## 9. 为什么这个方案比旧 deep research 方案更适合你现在做

旧方案同时做联网搜索、网页阅读、人机审批、报告生成、时间线 UI、任务表、SSRF、SSE、报告下载，范围太大，而且有几个和当前代码不匹配的地方。

这个方案更适合当前阶段：

- 直接复用你已有的 embedding、reranker、pgvector、SSE、JWT。
- 不依赖外部搜索质量，演示稳定。
- 面试时更容易展示工程闭环。
- 文件检索和报告下载正好能成为你大三结束前项目的核心竞争点。

## 10. 执行顺序建议

不要一次性全做。按这个顺序：

1. 先修 Agent/RAG 基础 bug。
2. 做后端文件上传 + chunk 入库。
3. 做检索 API。
4. 做报告生成 + 下载。
5. 做前端页面。
6. 最后补测试和面试材料。

每完成一阶段都能演示，避免做了很多 UI 但后端核心链路不通。

## 11. 面试驱动实现矩阵

这一节是为了把 `question.md` 里的面试题和真实实现绑定起来。你每完成一个 Task，都要能回答“为什么这么设计、解决了什么企业级问题、代码在哪里体现”。

### 11.1 Agent 整体流程：哪些是确定 workflow，哪些交给 LLM

实现落点：

- `backend/src/service/file_research.py`
- `backend/src/file_research/retriever.py`
- `backend/src/file_research/reporter.py`

第一版文件检索 Agent 不建议让 LLM 自由决定所有步骤，而是采用“确定流程 + LLM 只负责语义任务”的设计：

```text
确定流程：
上传文件 -> 校验 -> 切块 -> embedding -> 入库 -> 检索 -> rerank -> 生成报告 -> 保存 -> 下载

LLM 决策：
1. 根据检索片段组织报告结构
2. 总结关键发现
3. 判断证据是否足够
4. 用自然语言解释结果
```

面试官会问：

> 为什么不让 Agent 自己决定要不要读文件、读哪些文件、循环检索几次？

回答：

> 企业系统里 Agent 的不确定性要被关在可控边界内。文件上传、权限过滤、切块、向量检索、下载这些步骤必须是确定 workflow，否则会出现成本不可控、权限越界、结果不可复现。LLM 适合做语义理解和报告组织，不适合决定安全边界。所以我的设计是“确定管道 + LLM 语义节点”。

企业级问题：

- 成本可控：检索 top_k 有上限。
- 行为可复现：同一 query 和同一批文件能追踪到相同 chunk。
- 权限安全：所有 SQL 都强制带 `user_id`。
- 失败可定位：每一步都有明确状态和错误消息。

验收标准：

- 报告中必须能看到引用的文件名和 chunk id。
- 后端日志或 SSE 能显示“上传、索引、检索、生成、完成”阶段。

### 11.2 Tool schema 如何定义

实现落点：

- `backend/src/schemas.py`
- `backend/src/router/file_research.py`
- `backend/src/file_research/parser.py`

虽然文件检索第一版不一定要把上传/检索封装成 LangChain `@tool`，但所有外部输入都必须有清晰 schema。否则面试官问 tool schema 时，你只能讲概念，不能落到代码。

建议 schema：

```python
class FileResearchReportRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=1000)
    file_ids: list[UUID] | None = None
    top_k: int = Field(default=8, ge=1, le=20)


class FileChunkHitOut(BaseModel):
    chunk_id: int
    document_id: UUID
    filename: str
    score: float
    preview: str


class FileResearchReportOut(BaseModel):
    id: UUID
    query: str
    status: str
    report_md: str | None = None
    created_at: str | None = None
```

面试官会问：

> 你的 tool/schema 是怎么防止模型乱传参数的？

回答：

> 我把外部输入分成两层校验。API 层用 Pydantic 限制 query 长度、top_k 范围和 file_ids 类型；业务层再校验 file_ids 是否属于当前 user。即使 LLM 或前端传了非法参数，也会在进入检索 SQL 前被拦截。企业里不能只相信 prompt，要用 schema 和权限查询做硬约束。

企业级问题：

- 参数过大导致成本失控：`top_k <= 20`。
- 越权读取别人的文件：`file_ids` 必须和 `user_id` 同时校验。
- 空 query 或恶意长 query：Pydantic 长度限制。

验收标准：

- 非法 `top_k=999` 返回 422。
- 传入别人的 `file_id` 不返回任何 chunk，或直接 404。

### 11.3 为什么要分层记忆

实现落点：

- `backend/src/db/model.py`
- `backend/src/rag.py`
- `backend/src/file_research/retriever.py`

当前项目已有两类记忆：

| 记忆层 | 当前实现 | 用途 |
|---|---|---|
| Checkpoint 记忆 | LangGraph `AsyncPostgresSaver` | 恢复工具审批前后的图状态 |
| 聊天长期记忆 | `messages.embedding` | 检索历史对话 |

文件检索要新增第三层：

| 记忆层 | 新增实现 | 用途 |
|---|---|---|
| 文件知识记忆 | `file_chunks.embedding` | 检索用户上传文件内容 |

面试官会问：

> 为什么不直接把文件内容也存进 messages？

回答：

> 因为聊天记忆和文件知识的生命周期、权限边界、检索目标都不同。messages 是对话历史，适合辅助上下文；file_chunks 是用户显式上传的知识库，适合做可追溯引用。如果混在一起，会出现当前会话污染、文件无法单独删除、报告来源不可解释等问题。所以我把 checkpoint、聊天记忆、文件知识拆成三层。

企业级问题：

- 数据隔离：文件删除不能影响聊天记录。
- 可解释性：报告引用来自文件 chunk，而不是聊天上下文。
- 合规删除：用户删除文件时可以 cascade 删除 chunks。
- 检索污染：聊天废话不会进入文件报告证据。

验收标准：

- 删除一个 `FileDocument` 后，对应 `FileChunk` 自动删除。
- 文件报告检索不会查询 `messages` 表。

### 11.4 Context Window 如何控制

实现落点：

- `backend/src/file_research/parser.py`
- `backend/src/file_research/retriever.py`
- `backend/src/file_research/reporter.py`

关键参数：

```python
chunk_size = 1200
overlap = 180
top_k = 8
candidate_limit = top_k * 4
```

面试官会问：

> 如果用户上传 100 个文件，你怎么避免上下文窗口爆炸？

回答：

> 文件上传时我不会把全文交给模型，而是预先切 chunk 并向量化。用户查询时先用 query embedding 从数据库召回候选 chunk，再用 reranker 精排，只把 top_k 片段送进 LLM。这样 prompt 大小由 top_k 控制，而不是由文件总大小控制。

企业级问题：

- 大文件成本不可控：上传时限制 5MB，检索时限制 top_k。
- Lost in the Middle：只放高相关片段，不放全文。
- 证据缺失：报告必须写“证据不足”，不能编造。

验收标准：

- 上传大于 5MB 的文件返回错误。
- 报告 prompt 中只出现 top_k 个 chunk。

### 11.5 RAG 为什么要召回 + 重排

实现落点：

- `backend/src/rag.py`
- `backend/src/file_research/retriever.py`

当前项目已经有 BGE embedding 和 BGE reranker。文件检索应复用这个能力：

```text
query -> embedding -> pgvector 召回 32 条 -> reranker 精排 -> top 8 -> writer
```

面试官会问：

> 向量检索已经能找相似内容了，为什么还要 reranker？

回答：

> 向量召回适合快速从大量 chunk 中找候选，但它的相似度比较粗，尤其是长文本和相近主题容易混。reranker 是 cross-encoder，会同时看 query 和候选 chunk，对相关性判断更精细。企业 RAG 常见做法就是先召回扩大覆盖面，再重排提高 Precision@K。

企业级问题：

- 只看召回：可能把主题相近但不能回答问题的 chunk 放进 prompt。
- 只看 reranker：成本太高，不可能全库逐条比较。
- top_k 太小：召回不足。
- top_k 太大：上下文污染。

验收标准：

- 检索接口返回 score。
- 同一个 query 能看到 reranker 后排序变化。

### 11.6 工具失败和异常兜底

实现落点：

- `backend/src/file_research/parser.py`
- `backend/src/service/file_research.py`
- `backend/src/router/file_research.py`

面试官会问：

> 文件解析失败、embedding 失败、LLM 失败时怎么办？

回答：

> 每一层失败策略不同。文件解析失败是用户输入问题，直接返回 400；embedding 失败是索引失败，要把 `file_documents.status` 标成 `error` 并记录 error_message；LLM 生成报告失败时，`file_reports.status` 标成 `error`，前端 SSE 收到 error 事件。不能让异常直接变成无结构的 500，也不能让半成品任务显示成成功。

错误事件格式：

```json
{"type":"error","message":"报告生成失败，请稍后重试","report_id":"uuid"}
```

企业级问题：

- 用户能看到失败原因。
- 任务状态可追踪。
- 失败不会污染已索引文件。
- 便于排查线上问题。

验收标准：

- 上传空文件返回 400。
- LLM 报错时 `file_reports.status = "error"`。

### 11.7 安全：文件上传比网页抓取更容易被忽视

实现落点：

- `backend/src/file_research/parser.py`
- `backend/src/router/file_research.py`
- `frontend/src/views/FileResearchView.vue`

面试官会问：

> 你怎么防止用户上传危险文件？

回答：

> 第一版只允许文本白名单后缀，不执行文件，不信任原始 filename 路径，只取 basename。文件大小限制 5MB，解码使用 UTF-8 errors replace，避免解析器崩溃。原文件不落磁盘，只存文本 chunk。所有文件和 chunk 都绑定 user_id，下载报告也要校验 user_id。

企业级问题：

- 路径穿越：`../../secret` 只取 basename。
- 文件炸弹：限制大小。
- 二进制解析风险：第一版不解析 PDF/Word。
- 越权访问：所有查询带 `user_id`。

验收标准：

- 上传 `.exe` 返回错误。
- 上传文件名 `../../a.md`，数据库只保存 `a.md`。
- 用户 A 不能下载用户 B 的报告。

### 11.8 SSE 协议如何设计

实现落点：

- `backend/src/service/file_research.py`
- `frontend/src/stores/fileResearch.ts`

面试官会问：

> 为什么用 SSE，不用普通 HTTP 请求？

回答：

> 报告生成可能持续几十秒，普通 HTTP 只能等最终结果，用户会以为卡死。SSE 更适合后端单向推送进度和文本 chunk，实现成本比 WebSocket 低，也符合这个场景：前端发起任务后，只需要接收后端事件，不需要双向实时通信。

事件设计：

| type | 含义 |
|---|---|
| `report_start` | 创建报告任务 |
| `progress` | 阶段进度 |
| `sources` | 检索到的引用 chunk |
| `text` | Markdown 增量文本 |
| `done` | 完成并返回下载地址 |
| `error` | 失败 |

企业级问题：

- 长任务可观测。
- 前端状态机清晰。
- 出错时能恢复 UI。

验收标准：

- 断网或后端报错时前端显示错误，不一直 loading。
- `done` 后下载按钮可用。

### 11.9 Markdown 渲染和 XSS

实现落点：

- `frontend/package.json`
- `frontend/src/views/FileResearchView.vue`

当前聊天页直接 `v-html="marked.parse(...)"`，文件报告如果照做，会扩大 XSS 风险。文件内容来自用户上传，LLM 输出也可能包含 HTML。

面试官会问：

> 你把 Markdown 渲染成 HTML，怎么防 XSS？

回答：

> Markdown 渲染不能直接信任。前端如果使用 `v-html`，需要在 `marked` 后接 DOMPurify sanitize。更保守的第一版可以直接显示 Markdown 文本，下载为 `.md`，预览再做 sanitize。企业系统里 prompt 不能当安全边界，模型输出也不能当可信 HTML。

建议：

```bash
cd /home/wsyc1/projects/langchain/frontend
npm install dompurify
npm install -D @types/dompurify
```

验收标准：

- 上传包含 `<script>alert(1)</script>` 的文件，报告预览不能执行脚本。

### 11.10 测试怎么证明不是玩具项目

实现落点：

- `backend/tests/test_file_parser.py`
- `backend/tests/test_file_retriever.py`
- `backend/tests/test_file_research_api.py`

面试官会问：

> 你怎么证明这个 RAG 系统真的可靠？

回答：

> 我会分层测试。parser 测文件类型、大小、chunk overlap；retriever 测 user_id 隔离和 top_k；API 测上传、生成报告、下载鉴权；再用固定样本文档做一个端到端 case，确认报告包含预期来源。RAG 的质量无法只靠单元测试证明，但工程正确性必须先用测试保证。

测试矩阵：

| 测试 | 证明什么 |
|---|---|
| 文件后缀拒绝 | 上传安全边界 |
| chunk overlap | 切块不丢上下文 |
| user_id 过滤 | 多租户隔离 |
| report download 鉴权 | 防止越权 |
| fixed query e2e | 基础检索链路可用 |

验收标准：

- `uv run pytest tests/ -v` 能跑。
- 至少覆盖 parser、retriever、API 三层。

## 12. 每个实现阶段要沉淀的面试素材

| 阶段 | 你要写进项目总结的问题 | 能回答的面试题 |
|---|---|---|
| 修 Agent/RAG 基础 bug | 为什么 async 服务里不能直接跑 embedding？ | FastAPI 并发、CPU 阻塞、线程池 |
| 文件表和 chunk 表 | 为什么文件知识不能存 messages？ | 分层记忆、数据隔离、生命周期 |
| 文件解析 | 如何定义安全边界？ | 文件上传安全、白名单、大小限制 |
| 向量检索 | 为什么召回后还要 rerank？ | Recall/Precision、RAG 质量 |
| 报告生成 | 如何减少幻觉？ | 证据引用、只基于 chunk、证据不足 |
| SSE | 长任务怎么给用户反馈？ | SSE vs WebSocket、事件协议 |
| 下载 | 怎么防止越权？ | JWT、user_id 过滤、资源归属 |
| 测试 | 怎么证明不是 demo？ | 分层测试、权限测试、e2e 样例 |

你做项目时，每完成一个阶段，就把对应问题写进 `codex-question.md` 或 README。这样不是为了背面试题，而是让每个功能都能对应一个真实工程问题。
