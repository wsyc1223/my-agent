# 深度研究 Agent 设计文档

> **项目定位**：在现有 Agentic OS 项目中新增「深度研究」独立模式。用户输入一个问题，Agent 自动拆解子问题 → 联网搜索 → 深度阅读 → 筛选来源 → 生成结构化 Markdown 报告。全流程包含两个人机协同审批中断点（提纲审批、来源审批），充分展示 LangGraph 多阶段图编排、Context Window 管理、SSE 实时进度推送等核心工程能力。

> **创建日期**：2026-06-05  
> **状态**：待实施

---

## 1. 架构总览

### 1.1 与现有系统的关系

深度研究是与通用聊天**平级的独立模式**：

- 使用独立的 LangGraph 状态图（`research_graph`），与现有 `graph.py` 的聊天图互不干扰
- 共享同一个 PostgreSQL Checkpointer 连接池和 Langfuse 可观测性
- 共享同一套用户认证体系（JWT）
- 前端侧边栏新增「深度研究」入口，与会话列表并列

### 1.2 LangGraph 图结构

```
START → planner → ⏸ interrupt_before → researcher → ⏸ interrupt_before → writer → END
```

编译配置：

```python
research_app = research_workflow.compile(
    checkpointer=checkpointer,
    interrupt_before=["researcher", "writer"]
)
```

执行流程：

1. 用户提交研究问题 → `planner` 执行 → 图暂停
2. 前端展示提纲 → 用户审批/修改子问题 → `Command(resume=...)` 恢复
3. `researcher` 执行（逐个子问题搜索+阅读+提取） → 图暂停
4. 前端展示来源列表 → 用户筛选不可信来源 → `Command(resume=...)` 恢复
5. `writer` 执行 → 流式输出 Markdown 报告 → 结束

---

## 2. State 设计

### 2.1 核心类型定义

```python
from typing import TypedDict

class SubQuestion(TypedDict):
    id: int
    question: str              # 子问题文本
    search_queries: list[str]  # LLM 建议的搜索关键词（1-2 个）

class SourceItem(TypedDict):
    sub_question_id: int       # 归属的子问题 ID
    url: str                   # 来源网页 URL
    title: str                 # 网页标题
    snippet: str               # 提取的关键段落（截断至 2000 字符）
    credibility: str           # LLM 评估的可信度：high / medium / low

class ResearchState(TypedDict):
    query: str                          # 用户原始问题
    outline: list[SubQuestion]          # planner 输出的研究提纲
    sources: list[SourceItem]           # researcher 收集的来源材料
    report: str                         # writer 生成的最终 Markdown 报告
    progress_log: list[str]             # 进度日志条目，驱动前端时间线渲染
```

### 2.2 关键设计决策

**State 里不放 `messages` 列表。** 与通用聊天图不同，研究图使用结构化数据字段。每个节点只取自己需要的字段作为 LLM 输入：

| 节点 | 读取 | 写入 |
|---|---|---|
| `planner` | `query` | `outline`, `progress_log` |
| `researcher` | `outline` | `sources`, `progress_log` |
| `writer` | `query`, `sources` | `report`, `progress_log` |

这从根本上避免了长对话场景下 Context Window 爆炸的问题——每个 LLM 调用的输入都是可控的。

---

## 3. 各节点详细设计

### 3.1 planner 节点

**输入**：用户原始问题 `query`

**处理逻辑**：

1. 构建 System Prompt，指导 LLM 将问题拆解为 3-5 个互不重叠的子问题
2. 使用结构化输出（JSON Schema 约束）确保 LLM 返回符合 `list[SubQuestion]` 格式的结果
3. 如果 LLM 返回格式不合规，最多重试 2 次
4. 将拆解结果写入 `state["outline"]`

**Prompt 模板**（核心部分）：

```
你是一个研究助手。用户提出了一个研究问题，请将其拆解为 3-5 个具体的子问题。

要求：
- 每个子问题应该互不重叠，合在一起能全面覆盖原始问题
- 为每个子问题提供 1-2 个适合搜索引擎的搜索关键词
- 按照逻辑顺序排列（先基础概念，后深入分析）

用户问题：{query}

请以 JSON 格式返回...
```

**输出到 State**：`outline`（子问题列表）、`progress_log`（追加 "已完成问题拆解"）

### 3.2 researcher 节点

**输入**：经用户审批后的 `outline`

**处理逻辑**（串行遍历，每步推送 SSE 进度）：

```
for sub_question in outline:
    1. 调用 search_web(sub_question.search_queries[0])，获取搜索结果
    2. 从搜索结果中选取最相关的 1-2 个 URL
    3. 调用 fetch_url(url)，获取网页全文
    4. 截断网页内容至 2000 字符
    5. 调用 LLM 做两件事：
       a. 从网页内容中提取与子问题相关的关键段落
       b. 评估该来源的可信度（high/medium/low）
    6. 将结果追加到 state["sources"]
    7. 通过 SSE 推送进度事件
```

**关键约束**：

- 每个子问题最多调用 2 次 `search_web` + 2 次 `fetch_url`，总计不超过 15 次工具调用
- `fetch_url` 返回的内容截断至 2000 字符后再送入 LLM 提取
- 如果 `search_web` 或 `fetch_url` 失败，记录错误并跳过该子问题，不中断整个流程
- 工具调用必须使用 `asyncio.to_thread` 或原生 async 方式，不阻塞事件循环

**来源可信度评估 Prompt**（核心部分）：

```
根据以下网页内容，评估该来源的可信度。

评估标准：
- high：官方文档、权威媒体、学术论文、政府网站
- medium：知名博客、技术社区、百科类内容
- low：个人博客、论坛评论、来源不明的内容

网页标题：{title}
网页 URL：{url}
内容摘要：{snippet}

请返回 JSON：{"credibility": "high|medium|low", "reason": "..."}
```

**输出到 State**：`sources`（来源列表）、`progress_log`

### 3.3 writer 节点

**输入**：经用户筛选后的 `sources` + 原始 `query`

**处理逻辑**：

1. 将所有保留的来源材料按子问题分组
2. 构建 Writer Prompt，要求 LLM 生成结构化 Markdown 报告
3. 使用流式输出（streaming），逐 chunk 通过 SSE 推送到前端
4. 完成后将完整报告写入 `state["report"]`

**报告结构模板**：

```markdown
# {报告标题}

> 本报告由 AI 自动生成，基于 {N} 个来源的深度研究。生成时间：{datetime}

## 摘要
{对整个研究问题的 200 字概要回答}

## 1. {子问题 1 标题}
{基于相关来源的详细分析}

## 2. {子问题 2 标题}
{基于相关来源的详细分析}

...

## 结论
{综合所有子问题的总结性回答}

## 参考来源
1. [{title}]({url}) - 可信度：{credibility}
2. ...
```

**输出到 State**：`report`、`progress_log`

---

## 4. 后端 API 设计

### 4.1 新增路由

所有研究相关接口挂载在 `src/router/research.py`，前缀 `/research`。

| 方法 | 路径 | 功能 | 认证 | 返回类型 |
|---|---|---|---|---|
| POST | `/research/start` | 创建研究任务，启动 planner | JWT | SSE Stream |
| POST | `/research/{task_id}/approve-outline` | 审批/修改提纲后恢复图执行 | JWT | SSE Stream |
| POST | `/research/{task_id}/approve-sources` | 审批/筛选来源后恢复图执行 | JWT | SSE Stream |
| GET | `/research/tasks` | 获取当前用户的研究任务列表 | JWT | JSON |
| GET | `/research/{task_id}` | 获取单个研究任务详情（含报告） | JWT | JSON |

### 4.2 请求/响应 Schema

```python
# 启动研究
class ResearchStartRequest(BaseModel):
    query: str  # 用户的研究问题

# 审批提纲
class ApproveOutlineRequest(BaseModel):
    thread_id: str
    outline: list[SubQuestion]  # 用户可能修改过的提纲

# 审批来源
class ApproveSourcesRequest(BaseModel):
    thread_id: str
    approved_indices: list[int]  # 用户保留的来源索引列表

# 任务列表项
class ResearchTaskOut(BaseModel):
    id: str
    query: str
    status: str  # planning / outline_review / researching / sources_review / writing / done / error
    created_at: str

# 任务详情
class ResearchTaskDetail(BaseModel):
    id: str
    query: str
    status: str
    outline: list[SubQuestion] | None
    sources: list[SourceItem] | None
    report: str | None
    created_at: str
```

### 4.3 Resume 机制

审批后恢复图执行的核心逻辑：

```python
# 提纲审批后
async def approve_outline(task_id, approved_outline, thread_id, db):
    config = {"configurable": {"thread_id": thread_id}}

    # 将用户审批后的提纲更新到图状态
    await research_app.aupdate_state(
        config,
        {"outline": approved_outline},
        as_node="planner"  # 以 planner 节点的身份更新
    )

    # 恢复图执行（进入 researcher 节点）
    async for event in research_app.astream(None, config, stream_mode="values"):
        # 推送进度事件...
        pass

# 来源审批后
async def approve_sources(task_id, approved_indices, thread_id, db):
    config = {"configurable": {"thread_id": thread_id}}
    state = await research_app.aget_state(config)

    # 只保留用户批准的来源
    filtered_sources = [
        s for i, s in enumerate(state.values["sources"])
        if i in approved_indices
    ]

    await research_app.aupdate_state(
        config,
        {"sources": filtered_sources},
        as_node="researcher"
    )

    # 恢复图执行（进入 writer 节点）
    # ...
```

---

## 5. 数据库设计

### 5.1 新增表：research_tasks

```sql
CREATE TABLE research_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    query TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'planning',
    -- status 枚举: planning, outline_review, researching, sources_review, writing, done, error
    outline JSONB,          -- 存储提纲 list[SubQuestion]
    sources JSONB,          -- 存储来源 list[SourceItem]
    report TEXT,            -- 最终 Markdown 报告全文
    thread_id UUID NOT NULL, -- LangGraph checkpoint 的 thread_id
    error_message TEXT,     -- 如果 status=error，记录错误信息
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE INDEX idx_research_tasks_user_id ON research_tasks(user_id);
CREATE INDEX idx_research_tasks_status ON research_tasks(status);
```

### 5.2 SQLAlchemy Model

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

---

## 6. SSE 事件协议

研究流程使用与聊天不同的 SSE 事件类型，前端根据 `type` 字段分发处理。

### 6.1 事件类型定义

```jsonc
// 研究任务创建
{"type": "research_start", "task_id": "uuid", "thread_id": "uuid"}

// 进度推送（驱动前端时间线）
{"type": "progress", "step": "planner", "status": "running", "message": "正在分析问题并拆解子问题..."}
{"type": "progress", "step": "planner", "status": "done", "message": "已拆解为 4 个子问题"}
{"type": "progress", "step": "search", "sub_question_id": 1, "status": "running", "message": "正在搜索: LangGraph 状态管理"}
{"type": "progress", "step": "search", "sub_question_id": 1, "status": "done", "message": "找到 5 条结果"}
{"type": "progress", "step": "fetch", "sub_question_id": 1, "status": "running", "message": "正在深度阅读: https://..."}
{"type": "progress", "step": "fetch", "sub_question_id": 1, "status": "done", "message": "已提取关键内容（1847 字）"}
{"type": "progress", "step": "writer", "status": "running", "message": "正在撰写研究报告..."}

// 提纲中断（planner 完成后）
{"type": "outline_ready", "task_id": "uuid", "thread_id": "uuid", "outline": [
    {"id": 1, "question": "...", "search_queries": ["...", "..."]},
    {"id": 2, "question": "...", "search_queries": ["..."]}
]}

// 来源中断（researcher 完成后）
{"type": "sources_ready", "task_id": "uuid", "thread_id": "uuid", "sources": [
    {"sub_question_id": 1, "url": "...", "title": "...", "snippet": "...", "credibility": "high"},
    {"sub_question_id": 1, "url": "...", "title": "...", "snippet": "...", "credibility": "low"}
]}

// 报告流式输出（writer 阶段）
{"type": "report_chunk", "content": "## 1. 子问题标题\n\n根据调研..."}

// 完成
{"type": "report_done", "task_id": "uuid"}

// 错误
{"type": "error", "message": "搜索 API 调用超时，请稍后重试"}
```

### 6.2 与现有聊天 SSE 的区别

| | 通用聊天 SSE | 深度研究 SSE |
|---|---|---|
| 事件种类 | 5 种（conversation_id, text, interrupt, done, error） | 7 种（research_start, progress, outline_ready, sources_ready, report_chunk, report_done, error） |
| 中断点 | 1 个（工具调用前） | 2 个（提纲审批、来源审批） |
| 流式内容 | AI 消息片段 | 报告 Markdown 片段 |
| 进度反馈 | 无 | 细粒度步骤进度 |

---

## 7. 前端设计

### 7.1 新增组件

```
frontend/src/
├── views/
│   └── ResearchView.vue          # 研究主页面（对标 ChatView.vue）
├── components/
│   ├── ResearchTimeline.vue      # 左侧竖向进度时间线
│   ├── OutlineEditor.vue         # 提纲审批编辑器（增删改子问题）
│   ├── SourcesReviewer.vue       # 来源审批面板（勾选保留/剔除）
│   └── ReportRenderer.vue        # Markdown 报告渲染 + 下载按钮
├── stores/
│   └── research.ts               # Pinia store 管理研究状态
└── services/
    └── research.ts               # 研究相关 API 调用封装
```

### 7.2 ResearchView 布局

```
┌──────────────────────────────────────────────────────┐
│  Sidebar（共享）  │        ResearchView              │
│                   │  ┌────────┬───────────────────┐  │
│  [通用聊天]       │  │ 时间线  │   主内容区域       │  │
│  [深度研究] ←当前 │  │        │                   │  │
│                   │  │ ● 分析  │  (根据阶段切换)    │  │
│  研究历史列表     │  │ ● 搜索1 │  - 输入框          │  │
│  - 任务 A        │  │ ○ 搜索2 │  - 提纲编辑器      │  │
│  - 任务 B        │  │ ○ 搜索3 │  - 来源审批面板    │  │
│                   │  │ ○ 撰写  │  - 报告渲染器      │  │
│                   │  └────────┴───────────────────┘  │
└──────────────────────────────────────────────────────┘
```

### 7.3 各阶段 UI 状态

| 阶段 | 时间线状态 | 主内容区域 |
|---|---|---|
| 初始 | 空 | 显示输入框，用户输入研究问题 |
| planner 执行中 | "分析问题" 旋转中 | 显示 "正在分析并拆解研究问题..." |
| 提纲审批 | "分析问题" ✅ | OutlineEditor：展示子问题列表，可编辑/删除/新增，底部"开始研究"按钮 |
| researcher 执行中 | 各子问题逐个打勾 | 实时显示当前正在搜索/阅读的内容 |
| 来源审批 | 搜索步骤全部 ✅ | SourcesReviewer：来源卡片列表，带可信度徽章，可勾选保留 |
| writer 执行中 | "撰写报告" 旋转中 | 流式渲染 Markdown 报告内容 |
| 完成 | 全部 ✅ | ReportRenderer：完整报告 + 下载按钮 |

### 7.4 Pinia Store 结构

```typescript
interface ResearchStore {
  // 当前研究任务
  currentTaskId: string | null
  threadId: string | null
  query: string
  status: 'idle' | 'planning' | 'outline_review' | 'researching' | 'sources_review' | 'writing' | 'done' | 'error'

  // 数据
  outline: SubQuestion[]
  sources: SourceItem[]
  report: string

  // 进度
  progressSteps: ProgressStep[]  // { id, label, status: 'pending'|'running'|'done'|'error' }

  // 历史
  taskList: ResearchTaskSummary[]

  // Actions
  startResearch(query: string): Promise<void>
  approveOutline(outline: SubQuestion[]): Promise<void>
  approveSources(approvedIndices: number[]): Promise<void>
  fetchTaskList(): Promise<void>
  loadTask(taskId: string): Promise<void>
}
```

---

## 8. 错误处理策略

### 8.1 工具调用失败

| 失败场景 | 处理方式 |
|---|---|
| `search_web` 超时或 API 报错 | 记录错误，跳过该子问题的搜索，继续处理下一个子问题。在 `sources` 中标注该子问题"搜索失败" |
| `fetch_url` 超时或被反爬 | 回退到仅使用搜索摘要。在来源的 `snippet` 中注明"仅搜索摘要，未能获取全文" |
| `fetch_url` 内容过短（<100 字） | 标记为低质量来源（credibility: low），但仍保留供用户判断 |
| 所有子问题的搜索全部失败 | 中断流程，返回 error 事件，提示用户稍后重试或换个问题 |

### 8.2 LLM 输出解析失败

- planner 结构化输出不合规：最多重试 2 次。仍失败则返回错误提示用户
- 来源可信度评估格式错误：默认标为 medium，不中断流程
- writer 输出无需 JSON 解析，直接流式输出 Markdown，无解析风险

### 8.3 Context Window 管理

- 每个网页内容截断至 **2000 字符** 后再送入 LLM 提取
- writer 节点输入时，如果所有来源的 snippet 总长度超过 **8000 字符**，先对每个来源做进一步摘要压缩
- planner 和 researcher 的 LLM 调用各自独立，不共享消息历史，天然隔离了上下文膨胀

### 8.4 SSRF 防护（fetch_url 安全增强）

在 `fetch_url` 工具中增加 URL 校验逻辑：

```python
import ipaddress
from urllib.parse import urlparse
import socket

def is_safe_url(url: str) -> bool:
    parsed = urlparse(url)

    # 只允许 http/https 协议
    if parsed.scheme not in ("http", "https"):
        return False

    # 解析域名为 IP 地址
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(parsed.hostname))
    except (socket.gaierror, ValueError):
        return False

    # 禁止内网保留 IP 段
    if ip.is_private or ip.is_loopback or ip.is_reserved:
        return False

    return True
```

---

## 9. 需要同步修复的现有缺陷

在实现深度研究功能的过程中，以下现有缺陷必须同步修复：

### 9.1 同步 Embedding 阻塞事件循环

**位置**：`backend/src/service/agent.py` L34-35, L84-85, L158-159

**现状**：`embed_text()` 在 async 函数中同步调用，CPU 密集计算会阻塞整个事件循环。

**修复**：

```python
# 修复前
msg_emb = embed_text(message)

# 修复后
msg_emb = await asyncio.to_thread(embed_text, message)
```

### 9.2 多工具拒绝只处理首个 tool_call

**位置**：`backend/src/service/agent.py` L124-128

**现状**：用户拒绝时只为 `tool_calls[0]` 生成 ToolMessage，多工具并行调用时会导致 LangGraph 崩溃。

**修复**：

```python
# 修复前
tool_call_id = last_msg.tool_calls[0]["id"]
resume_input = Command(resume={"messages": [
    ToolMessage(content="用户拒绝了该工具调用", tool_call_id=tool_call_id)
]})

# 修复后
reject_messages = [
    ToolMessage(content="用户拒绝了该工具调用", tool_call_id=tc["id"])
    for tc in last_msg.tool_calls
]
resume_input = Command(resume={"messages": reject_messages})
```

### 9.3 RAG 检索未排除当前会话

**位置**：`backend/src/rag.py` L16-34

**现状**：`search_messages` 没有 `exclude_conversation_id` 参数，会检索到用户刚发出的当前消息。

**修复**：SQL 查询增加 `AND c.id != :exclude_conv_id` 条件。

---

## 10. 测试策略

### 10.1 后端测试

| 测试类别 | 测试内容 | 优先级 |
|---|---|---|
| 图流转测试 | Mock LLM 和工具，验证 State 在 planner → researcher → writer 之间正确传递 | P0 |
| 中断/恢复测试 | 验证图在 researcher 和 writer 之前正确暂停，resume 后正确恢复 | P0 |
| 提纲审批测试 | 验证用户修改后的 outline 正确写入 State 并被 researcher 使用 | P0 |
| 来源筛选测试 | 验证用户剔除的来源不会出现在 writer 的输入中 | P0 |
| SSE 事件格式测试 | 验证所有事件类型是合法 JSON，包含必需字段 | P1 |
| 工具失败降级测试 | 模拟 search_web 超时，验证流程跳过而非崩溃 | P1 |
| URL 安全校验测试 | 验证内网 IP、非 http 协议被正确拦截 | P1 |
| 权限隔离测试 | 验证用户 A 无法访问用户 B 的研究任务 | P1 |

### 10.2 前端测试

| 测试类别 | 测试内容 | 优先级 |
|---|---|---|
| 构建测试 | `npm run build` 通过 | P0 |
| Store 状态测试 | SSE 事件正确更新 Pinia store 中的 status、outline、sources、report | P1 |
| 时间线渲染测试 | progress 事件正确驱动时间线步骤的状态变化 | P1 |

---

## 11. 文件变更清单

### 新增文件

```
backend/
├── src/
│   ├── research_graph.py           # 研究 LangGraph 图定义（State + 节点 + 编排）
│   ├── router/research.py          # 研究相关 API 路由
│   ├── service/research.py         # 研究业务逻辑（start, approve, SSE 生成器）
│   ├── schemas.py                  # 新增研究相关 Schema（追加到现有文件）
│   └── db/
│       ├── model.py                # 新增 ResearchTask Model（追加到现有文件）
│       └── repository.py           # 新增 ResearchTaskRepository（追加到现有文件）
├── alembic/versions/
│   └── xxxx_add_research_tasks.py  # 数据库迁移脚本

frontend/
├── src/
│   ├── views/ResearchView.vue
│   ├── components/
│   │   ├── ResearchTimeline.vue
│   │   ├── OutlineEditor.vue
│   │   ├── SourcesReviewer.vue
│   │   └── ReportRenderer.vue
│   ├── stores/research.ts
│   ├── services/research.ts
│   └── router/index.ts            # 新增 /research 路由（修改现有文件）
```

### 修改文件

```
backend/
├── main.py                         # 注册 research_router
├── src/tools.py                    # fetch_url 增加 SSRF 防护
├── src/service/agent.py            # 修复 embed_text 异步 + 多工具拒绝
├── src/rag.py                      # search_messages 增加 exclude_conversation_id
├── src/db/model.py                 # 追加 ResearchTask Model
├── src/schemas.py                  # 追加研究相关 Schema

frontend/
├── src/App.vue                     # 无需改动（router-view 自动处理）
├── src/components/ChatSidebar.vue  # 新增「深度研究」导航入口和任务历史列表
```

---

## 12. 面试叙事要点

实现完成后，面试时应重点展示以下技术决策和工程亮点：

1. **"为什么用 LangGraph 而不是简单的链式调用？"**
   → Checkpoint 持久化让研究任务可以跨请求恢复；`interrupt_before` 实现声明式人机协同，而不是轮询式

2. **"怎么管理 Context Window？"**
   → 结构化 State 替代 messages 列表，每个节点只取自己需要的字段；网页内容截断 + 超长材料二次摘要

3. **"如果搜索 API 挂了怎么办？"**
   → 单子问题级别的失败隔离，不影响其他子问题；来源审批阶段用户可以看到哪些失败了

4. **"fetch_url 的安全风险？"**
   → SSRF 防护：协议白名单 + 内网 IP 段拦截

5. **"为什么 Embedding 要扔进线程池？"**
   → CPU 密集计算会阻塞 asyncio 事件循环，影响所有并发连接的 SSE 流式推送

6. **"进度反馈怎么做的？"**
   → SSE 细粒度事件协议设计，前端时间线组件根据事件类型和 sub_question_id 精确更新步骤状态
