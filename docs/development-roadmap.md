# Agentic OS 发展方向与面试备战方案

> 基于 2026 年 6 月 20 日行业最新动态，结合 question.md 中的面试题逐条分析。

---

## 一、项目现状评估

### 优势

- 三层架构清晰：Router → Service/Graph → Repository
- 核心功能可用：聊天智能体、文件深度检索、JWT认证、SSE流式、人机回环审批、双通道检索
- 技术栈选型合理：FastAPI + LangGraph + pgvector + Vue 3 + Vite
- 安全措施到位：SSRF防护、DOMPurify XSS清理、路径穿越防护、多租户隔离

### 当前面试得分预估：60/100

核心问题：功能能跑通，但缺少**工程化深度**（错误处理、评测、降级、重试）和**面试叙事完整性**（每个问题的答案链条不闭合）。

---

## 二、2026年6月行业关键趋势

| 趋势 | 来源 | 启示 |
|---|---|---|
| Desktop Agent 成为主流 | Andrew Ng 发布 OpenCoworker (12星)，Anthropic 80%代码由AI生成 | agent不只是聊天，应能操控本地文件、执行任务 |
| Agent Harness 工程与模型同等重要 | Cursor Composer 2.5 专为 agentic coding 训练 | 展示你定制了 agent harness（tool policy、中断恢复、状态持久化） |
| Voice for AI Agents | DeepLearning.AI 6月推出语音课程 | 语音交互是当下最热方向 |
| MCP 成为标准 | aisuite 原生支持 MCP，Anthropic 推动 | 工具应支持 MCP 协议，而非硬编码 tool list |
| Eval 体系升级 | SWE-bench 被 DeepSWE/ProgramBench 取代 | 项目需要有可量化的评测指标 |
| 开源模型权重崛起 | Nvidia Nemotron 3 Ultra 开源，DeepSeek V4 领先 | 选用 DeepSeek 是对的，应支持多模型切换/fallback |
| AI Engineer 需求激增 | Andrew Ng 明确说 AI Engineer 比 FDE 需求量更大 | 你的项目定位正好命中这个岗位 |
| 中国开源模型领先代理赛道 | Kimi K2.6、Qwen3.7-Max、DeepSeek V4 Pro、GLM-5.2 | 关注国产模型，面试时可展示追踪能力 |

---

## 三、逐条面试题差距分析与改进方案

### Q1：Agent 整体流程（question.md 第1-15行）

**已有**：agent→tools→agent + `interrupt_before`  
**面试会追问的漏洞**：

1. **没有失败分支**：工具调用失败后没有降级/重试路径
2. **没有明确区分 workflow vs LLM决策**：需要能说清楚"代码里写死的是哪些路由,模型自己决定的是哪些动作"
3. **没有重试机制**：工具调用失败、LLM 返回异常时直接崩溃
4. **多 agent 分工不清晰**：research graph 的 researcher→writer 为什么是两个节点而不是一个

**改进方案（改 graph.py 和 research_graph.py）**：
- 在 chat graph 加 `error_handler` 节点，连续错误 ≥3 次终止（面试可答"有限重试策略"）
- 在 `State` 中新增 `agent_errors` 字段计数
- `should_continue` 增加错误分支：`agent_errors >= 3 → END`

**面试话术**：
> "我把图的控制流分为两类：workflow 层（代码写死的路由，比如 query_rewriter→researcher→tools→researcher）和 Agent 决策层（LLM 在每个决策节点自主选择调哪个工具、搜多少次）。这样既保证了流程的可控性，又保留了 Agentic 的灵活性。"

---

### Q2：Tool Calling 设计（question.md 第18-30行）

**已有**：SSRF防护、多工具并发拒绝对齐  
**面试会追问的漏洞**：

1. **工具错误没有分层**：网络超时 vs 参数错误 vs API 限流，应该有不同的兜底策略
2. **没有回答"如何判断是prompt问题还是模型能力问题"**
3. **工具 schema 靠 docstring 描述**，没有严格 Pydantic 校验

**改进方案（改 tools.py）**：
- 新增 `ToolErrorType` 枚举：`TEMPORARY`(可重试) / `PERMANENT`(不可重试)
- `classify_http_error()` 函数：超时→临时，403/404→永久，429/503→临时
- 工具返回消息标注 `[可重试]` 或 `[不可重试]`，LLM 据此决定是否重试

**面试话术**：
> "我在工具返回的错误信息里打了标签：`[可重试]` 表示网络抖动、服务繁忙，模型应稍后重试；`[不可重试]` 表示参数错误、权限拒绝，模型应调整策略。这比通用 try-catch 更精细——不是所有错误都应该触发重试。"

---

### Q3：Context Window 与记忆机制（question.md 第32-37行）

**已有**：聊天历史 RAG（embedding → pgvector → reranker）  
**面试会追问的漏洞**：

1. **没有项目级规则/用户偏好层**：面试官期待听到三层记忆架构
2. **文件检索记忆和聊天记忆没有融合**

**改进方案（改 model.py + service/agent.py）**：
- 新增 `UserPreference` 表：`preferred_language`、`expertise_level`、`custom_instructions`
- 在 `chat_stream` 中读取用户偏好，拼入 HumanMessage 前缀

**三层记忆架构**：

| 层 | 生命周期 | 存储 | 用途 |
|---|---|---|---|
| 短期记忆 | 当前会话内 | LangGraph checkpoint (PostgresSaver) | 上下文窗口内消息 |
| 会话级记忆 | 跨会话 RAG | Message.embedding + pgvector | 历史对话语义检索 |
| 长期记忆 | 用户级别 | UserPreference 表 | 偏好、专业水平、自定义指令 |

**面试话术**：
> "我设计了分层记忆架构。短期记忆靠 LangGraph 的状态持久化，会话级记忆靠 pgvector 做语义检索，长期记忆靠 UserPreference 表存储用户偏好。每次对话时，三层信息依次拼接到 SystemMessage 里，保证模型始终了解用户背景。"

---

### Q4：RAG 需要做哪些优化（question.md 第40-48行）

**已有**：向量检索 + reranker + grep 双通道  
**面试会追问的漏洞**：

1. **没有 BM25 基线**：面试官会问"你怎么知道语义搜索比 BM25 好？"
2. **没有 Recall@K / Precision@K 量化**
3. **切块策略是固定滑动窗口**，不是结构感知切块
4. **grep 用 ILIKE**，不是 PostgreSQL 原生的 tsvector BM25

**改进方案**：

**A. BM25 全文检索（改 model.py + retriever.py）**
- `FileChunk` 表加 `tsv_content` 列（PostgreSQL TSVECTOR 类型）
- 用 GIN 索引加速
- 插入/更新时通过 trigger 自动填充 tsvector
- 新增 `tsvector_search_chunks()` 函数，用 `ts_rank` + `plainto_tsquery` 做 BM25 检索

**B. 结构感知切块（改 parser.py）**
- 新增 `chunk_text_structural()`：优先按 Markdown 标题（# ## ###）切分，再按空行（段落边界）切分
- 回退到现有固定窗口切块
- 比固定 1200 字符窗口能更好地保持语义完整

**C. 评测脚本（新建 tests/test_rag_eval.py）**
- 设计 50+ 条测试用例，包含 `expected_keywords`
- 分别跑向量检索、BM25 检索、向量+重排序
- 输出 Recall@5 和 Precision@5 对比表

**面试话术**：
> "我做了一个完整的评测。不是凭感觉说'语义搜索更好'，而是用 50 条标注数据对比了纯向量、纯 BM25、向量+重排序三种方案。结果是：语义搜索在概念类问题上 Recall 高，BM25 在代码/变量名查找上 Precision 高——两者互补，所以我用双通道方案。"

---

### Q5：Agentic RAG 和传统 RAG 的区别（question.md 第50-58行）

**缺失最严重**：

1. **没有 Query Rewrite**——这是 Agentic RAG 最核心的标志
2. **检索失败后没有调整策略**
3. **成本和稳定性没有量化讨论**

**改进方案（改 research_graph.py）**：

- 新增 `query_rewriter` 节点：LLM 将模糊提问改写为 1-3 个精确检索短语
- `ResearchState` 新增 `rewritten_queries` 字段
- 工作流变为：`query_rewriter → researcher → tools → researcher → writer → END`
- 在 `RESEARCH_PROMPT` 中嵌入降级链指导：
  ```
  检索策略（按优先级尝试）:
  1. 优先用 search_document_by_vector 做语义检索
  2. 如果语义检索无结果，改用 search_document_by_grep 做精确匹配
  3. 如果本地都无结果，使用 search_web 联网搜索
  ```

**面试话术**：
> "传统 RAG 是'用户提问→embedding→查向量库→拼接结果→LLM生成'一次性流水线。Agentic RAG 的关键不同是：LLM 自己决定检索策略。我的实现是：先用 query_rewriter 改写模糊提问为精确短语，然后模型每轮自己评估检索质量、决定下一步用哪个工具——语义搜索没结果就切 grep，grep 没结果就联网。这不靠 hardcode，靠模型的自主决策。"

---

### Q6：Agent 框架选型（question.md 第60-67行）

**准备话术即可，不需要改代码**：

**LangGraph vs LangChain**：
> "LangChain 是 LLM 应用的胶水层（Chains、Prompts、Tools），LangGraph 是有状态的图编排引擎。核心区别是 state——LangGraph 的每条边都传递一个类型化的 State，支持 checkpoint 持久化和人机回环（interrupt_before），这是 Chains 做不到的。"

**LangGraph 的 state、node、edge**：
> "State 是一个 TypedDict，在整个图中流转——这就是我的上下文窗口。Node 是执行单元（agent、tools、writer 各一个），Edge 是 State 的流转规则。Conditional Edge 是关键——`should_continue` 函数根据当前 state 决定下一步走 tools 还是 writer 还是 END。"

**为什么选 LangGraph 而不是 AutoGen/CrewAI/手写状态机**：
> "AutoGen 和 CrewAI 的核心是多 agent 对话，但实际生产中 agent 之间靠自由对话容易死循环，不如预定义图结构可靠。手写状态机维护成本高。LangGraph 提供了明确的 flow 控制和灵活的 LLM 决策节点，是目前 Agent 框架里最成熟的方案。2026 年 Anthropic 的 Claude Code 和 Andrew Ng 的 OpenCoworker 都是类似的 harness 设计思路。"

---

## 四、分阶段执行计划

### 第一阶段：即战力（2-3周，面试杀手锏）

| # | 任务 | 改哪些文件 | 回答面试题 |
|---|---|---|---|
| 1 | 加 Query Rewrite 节点 | research_graph.py | Q5 |
| 2 | 嵌入降级链到 prompt | research_graph.py, graph.py | Q5 |
| 3 | 加 error_handler 节点 + 重试 | graph.py | Q1 |
| 4 | 工具错误分层（可重试/不可重试） | tools.py | Q2 |
| 5 | BM25 tsvector + 评测脚本 | model.py, retriever.py, tests/test_rag_eval.py | Q4 |
| 6 | 三层记忆架构 + UserPreference 表 | model.py, repository.py, service/agent.py | Q3 |

**第一阶段完成后，6道面试题你全部能完整回答。**

### 第二阶段：生产可用（2-4周）

| # | 任务 | 说明 |
|---|---|---|
| 7 | Docker Compose 一键部署 | PG + Redis + 后端 + 前端 |
| 8 | CORS 收紧 + `/health` 端点 | main.py |
| 9 | 升级嵌入模型 BGE-M3 | 1024维，多语言，更长上下文 |
| 10 | 结构感知切块 | parser.py |
| 11 | E2E 测试 | tests/test_e2e.py |
| 12 | tsvector 替换 ILIKE | retriever.py |

**第二阶段完成后，项目看起来像一个真正的生产级产品。**

### 第三阶段：差异化亮点（4-6周）

| # | 任务 | 说明 |
|---|---|---|
| 13 | MCP 协议集成 | Agent 可接入任意 MCP server |
| 14 | 多模型 Fallback | DeepSeek 挂了自动切 Qwen/本地 Ollama |
| 15 | 语音交互 | Whisper TTS + 语音输入 |
| 16 | 自定义 eval benchmark | 100条测试用例，面试时展示数据 |
| 17 | 文件系统工具 | read_file, write_file, list_directory 等 |

---

## 五、技术栈升级建议

| 当前 | 建议升级 | 理由 |
|---|---|---|
| BGE-base-zh-v1.5 (768维) | **BGE-M3** (1024维) | 多语言、更长上下文、2026年主流 |
| BGE-reranker-base | **BGE-reranker-v2-m3** | 精度提升明显 |
| ILIKE 文本搜索 | **pgvector + tsvector (BM25)** | 面试时能和 Q4 呼应 |
| langgraph==1.2.4 | **>=1.3.x** | 支持更多 agent 模式 |
| 无 Docker | **Docker Compose** | 生产部署的基本要求 |
| 固定 1200 字符切块 | **结构感知切块**（按 Markdown 标题/段落边界） | RAG 质量的关键提升 |
| 无评测体系 | **RAG eval 脚本**（Recall@K + Precision@K） | 回答 Q4 必备 |

---

## 六、最推荐的差异化方向

结合 2026 年 6 月趋势，最佳方向是：

**核心定位**：不只是"聊天+文件检索"，而是一个**能自主使用电脑的 AI 同事（Desktop Agent）**

Andrew Ng 2026 年 6 月 12 日文章指出当前 AI 交互三大接口：
1. Chat 界面（你已实现）
2. Coding CLI
3. **Desktop Agent**（能读写文件、操作本地系统、定时执行任务）

你的项目天然可以从 (1) 延伸到 (3)，差异化亮点在于：

- **将 agent 做成 OpenCoworker 的开源替代** — 你已有文件检索能力，扩展为"操作本地文件系统"是自然延伸
- **加入 MCP 支持** — 这是 2026 年 agent 工具的**标准协议**，Anthropic 和 aisuite 都在推
- **构建自己的 eval benchmark** — 面试中最独特的亮点：你不仅做了项目，还为这个项目**设计了评测体系**

---

## 七、附录：新文件创建清单

### 第一阶段需要新建的文件

1. **`backend/alembic/versions/xxxx_add_tsvector_and_user_preferences.py`**
   - 加 `tsv_content` 列（TSVECTOR），GIN 索引，自动更新 trigger
   - 创建 `user_preferences` 表

2. **`backend/tests/test_rag_eval.py`**
   - 50+ 条测试用例，Recall@5 + Precision@5 对比

3. **`backend/download_models.py`**
   - 下载 BGE-M3 和 BGE-reranker-v2-m3 的脚本

### 第二阶段需要新建的文件

4. **`docker-compose.yml`**（项目根目录）
   - PostgreSQL (pgvector/pgvector:pg17) + Redis + 后端 + 前端

5. **`backend/Dockerfile`**
   - Python 3.12-slim + uv 安装依赖 + uvicorn 启动

6. **`frontend/my-vue-project/Dockerfile`**
   - Node 22-alpine + npm 构建 + dev 模式启动

7. **`backend/tests/test_e2e.py`**
   - health check + 注册/登录 + 会话列表 + SSE 流式聊天
