
# 第一章：基于 FastAPI 与 asyncio 的高并发异步架构规范

## 1.1 事件循环与线程池协同机制
在高性能 Web 服务开发中，FastAPI 依赖 Python 的 `asyncio` 事件循环处理高并发 I/O 请求。为了保证事件循环主线程不被 CPU 密集型任务或同步阻塞 I/O 挂起，系统必须严格区分异步协程与同步阻塞函数。
对于同步 CPU 密集型计算（如加密哈希计算、图像处理或大型 JSON 解析），必须通过 `asyncio.to_thread` 或 `run_in_executor` 将其派发至 ThreadPoolExecutor 线程池中运行。

### 配置参数规范
* `ASYNC_THREAD_POOL_MAX_WORKERS` = 64 (线程池最大工作线程数)
* `ASYNC_EVENT_LOOP_POLICY` = "uvloop" (生产环境高吞吐事件循环驱动)
* `ASYNC_TASK_TIMEOUT_SECONDS` = 30 (默认协程执行超时阈值)

## 1.2 异常边界与全局 Middleware 拦截
所有的 API 异常均需收拢至 `src/exceptions.py` 的统一分层异常体系中。全局中间件 `CorrelationIdMiddleware` 在接收到 HTTP 请求的瞬间，会自动生成或提取 `X-Request-ID`，并通过 Python 的 `contextvars` 模块将其绑定至当前的异步执行上下文。

### 错误响应码对照表
* `ERR_ASYNC_TIMEOUT_504`: 协程等待超时，系统放弃当前请求并记录日志。
* `ERR_ASYNC_THREAD_EXHAUSTED_503`: 线程池已满，拒绝新的 CPU 密集型任务派发。
* `ERR_INVALID_CORRELATION_ID_400`: 请求头中传入的 Correlation ID 格式非法。


---


# 第二章：PostgreSQL 与 pgvector 向量检索及 HNSW/IVFFlat 索引原理

## 2.1 pgvector 扩展及余弦距离匹配
PostgreSQL 结合 `pgvector` 扩展为 AI Agent 提供了高效的向量持久化与相似度检索能力。在我们的向量表 `file_chunks` 中，`embedding` 字段被声明为 `Vector(768)` 类型，专门用于存放 768 维度的 BGE 语义嵌入。

在 SQL 查询中，余弦距离运算符为 `<=>`，L2 距离运算符为 `<->`，内积运算符为 `<#>`。
根据定义，余弦相似度（Cosine Similarity）与余弦距离（Cosine Distance）的关系公式为：
$$\text{Cosine Similarity} = 1 - \text{Cosine Distance}$$

## 2.2 HNSW 与 IVFFlat 索引选择策略
在 pgvector 中，主要支持 IVFFlat（Inverted File Flat）与 HNSW（Hierarchical Navigable Small World）两种向量索引：
* **IVFFlat 索引**：基于 K-Means 聚类中心划分倒排列表。建索引速度快，但查询前必须设置 `SET ivfflat.probes = 10`。在数据量小或频繁更新时召回率有波动。
* **HNSW 索引**：基于分层小世界图结构。建索引耗费更多内存与时间，但查询性能极佳且不需要预热配置，能够在无需完全扫描的情况下实现高达 98%+ 的 Recall@K。

### 索引配置参数规范
* `PG_VECTOR_INDEX_TYPE` = "hnsw"
* `PG_VECTOR_HNSW_M` = 16 (每个图节点的最大双向链接数)
* `PG_VECTOR_HNSW_EF_CONSTRUCTION` = 64 (构建索引时的动态候选列表大小)
* `ERR_PG_VECTOR_DIM_MISMATCH_422`: 传入的查询向量维度与表声明的 768 维不一致。
* `ERR_PG_VECTOR_INDEX_NOT_READY_500`: 向量索引尚未创建完成，回退至全表顺序扫描。


---


# 第三章：大语言模型（LLM）防线与三态熔断器（LLM_BREAKER）设计

## 3.1 进程内三态熔断器机制
为防止底层 LLM 供应商（如 DeepSeek 或 Qwen）因网络故障、机房宕机或 API 429 大规模限流导致整个 Web 服务响应卡死，系统在 `src/resilience.py` 中实现了进程内的“三态熔断器（LLM_BREAKER）”。

熔断器包含三种内部状态：
1. **CLOSED（关闭状态）**：正常转发所有 LLM 调用请求。当连续失败次数达到阈值 `5` 次时，触发熔断，状态自动切换至 OPEN。
2. **OPEN（开启状态）**：直接拒绝所有 LLM 调用请求，立即抛出 `LLMBreakerOpenError`，绝不向第三方 API 发起任何网络连接。经过冷却时间 `30` 秒后，状态自动切换至 HALF-OPEN。
3. **HALF-OPEN（半开状态）**：允许试探性地放行 `1` 次 LLM 请求。若该请求成功，则熔断器恢复至 CLOSED 状态并清空失败计数器；若该请求依然失败，则重新切回 OPEN 状态并重新开始 30 秒冷却。

## 3.2 错误类型重试与映射规范
* **429 Rate Limit (Too Many Requests)**：自动触发指数退避重试（Exponential Backoff），最大重试次数为 `3` 次，基础等待时间为 `2` 秒。
* **402 Payment Required (欠费)**：不可重试错误，直接映射为致命业务异常 `LLMPaymentRequiredError`，终止当前 Agent 执行流。
* **400 Context Length Exceeded (上下文超限)**：自动触发 `ainvoke_with_context_recovery`，自动裁剪历史对话的最早 30% 消息，并进行单次重试。

### 熔断器配置参数规范
* `LLM_BREAKER_FAILURE_THRESHOLD` = 5 (连续失败阈值)
* `LLM_BREAKER_COOL_DOWN_SECONDS` = 30 (OPEN 状态冷却秒数)
* `ERR_LLM_BREAKER_OPEN_503`: 熔断器处于开启状态，请求被拦截。
* `ERR_LLM_CONTEXT_OVERFLOW_400`: 上下文长度超出大模型 Token 容限上限。


---


# 第四章：LangGraph 状态持久化与 PostgreSQL Checkpointer 架构

## 4.1 LazyAsyncPostgresSaver 设计原理
LangGraph 1.2.4 使用 Checkpointer 机制在每个 Graph Node 执行完毕后自动将 `State` 状态快照持久化至数据库。在主流程中，由于应用启动阶段事件循环（Event Loop）可能尚未完全就绪，直接实例化 `AsyncPostgresSaver` 会触发底层事件循环绑定异常。

为此，系统自研了 `LazyAsyncPostgresSaver` 类，继承自 `AsyncPostgresSaver`。它采用延迟初始化（Lazy Initialization）设计模式，在首次触发 `get_tuple`、`put` 或 `setup` 方法时，才在运行中的事件循环上下文中安全激活底层连接池。

## 4.2 状态快照与中断恢复（HITL）
当 Agent 推理遇到敏感操作（如删除数据库记录、执行高危 Shell 命令）时，图会在 Tool 节点前触发 `interrupt_before=["tools"]`，将图执行挂起。

系统通过 `thread_id`（通常与 `conversation_id` 保持一致）隔离不同会话的状态。当用户在前端点击“同意”或“拒绝”后，路由层通过 `/agent/resume` 接口向图发送 `Command(resume="continue")` 或拒绝 Command，驱动图继续向下流转。

### 状态配置参数规范
* `LANGGRAPH_RECURSION_LIMIT` = 25 (主图节点最大递归深度阀值)
* `LANGGRAPH_RESEARCH_RECURSION_LIMIT` = 50 (深度研究子图最大递归深度)
* `ERR_GRAPH_RECURSION_EXCEEDED_429`: 图触发无限递归死循环安全阀。
* `ERR_CHECKPOINT_NOT_FOUND_404`: 传入的 thread_id 在数据库中未找到任何历史状态快照。


---


# 第五章：Agent 容错机制：工具异常分类（ToolRetryableError/ToolFatalError/ToolDangerousError）

## 5.1 三级工具异常分类体系
当 Agent 调用外部 Tool（如 Tavily 搜索、网页抓取、向量检索）发生故障时，系统将工具异常严格划分为三级，防止工具失败拖垮整个 Agent 执行链：

1. **`ToolRetryableError`（可重试工具错误）**：
   * 触发场景：Tavily 网络超时、HTTP 502/503 瞬时错误、解析 HTML 临时失败。
   * 处理逻辑：由 `error_handler` 节点捕获，自动重试调用该工具，最大重试次数为 `3` 次。
2. **`ToolFatalError`（致命工具错误）**：
   * 触发场景：传入参数格式完全错误、数据库连接彻底中断、请求无权限。
   * 处理逻辑：不再重试，由 `error_summary` 节点将其转化为结构化中文错误提示返回给 LLM，提示大模型更改策略或告知用户。
3. **`ToolDangerousError`（危险工具操作）**：
   * 触发场景：工具检测到即将修改系统配置文件、删除全局数据或执行危险命令。
   * 处理逻辑：立刻中断图执行，强制进入人机协同（HITL）审批流。

## 5.2 错误结构化 JSON 规范
工具在抛出异常时，必须返回规范的 JSON 结构给 LLM 节点：
```json
{
  "status": "error",
  "error_type": "retryable",
  "error_code": "ERR_TOOL_TAVILY_TIMEOUT_504",
  "message": "Tavily Web Search API 超时",
  "suggestion": "请更换更具体的关键词重试"
}
```

### 工具配置参数规范
* `TOOL_MAX_RETRY_ATTEMPTS` = 3 (可重试工具的最大重试次数)
* `TOOL_TIMEOUT_SECONDS` = 10 (单个工具调用的硬超时时间)


---


# 第六章：Redis 分布式便签补偿机制（need_sync）与数据一致性降级

## 6.1 PostgreSQL 写入失败与 asyncio.shield 保护
在流式对话（`chat_stream`）和恢复执行（`resume`）流程中，大模型生成的回答片段已经成功通过 SSE（Server-Sent Events）推送给了前端用户。如果在收尾阶段写入 PostgreSQL 数据库（如消息落库、Embedding 存储）发生突发故障（如 DB 暂时锁死），系统绝对不能向前端发送 Error 帧破坏用户体验。

为此，落库异步任务使用 `asyncio.shield` 进行保护。当 DB 写入异常被捕获后，系统触发降级机制——向 Redis 中写入一张“分布式补偿便签”。

## 6.2 Redis 补偿便签规范
* **Key 格式**：`need_sync:{conversation_id}`
* **TTL（过期时间）**：86400 秒 (24 小时)
* **Value 内容**：存储包含 `conversation_id`、失败来源（`chat_stream` 或 `resume`）及时间戳的 JSON 字符串。
* **补偿 Worker 逻辑**：后台的定时数据补偿 Worker 轮询扫描 `need_sync:*` 键，根据 `conversation_id` 从 LangGraph Checkpointer (`app.aget_state`) 中重新提取状态真相，重新补写入 PostgreSQL。

### 补偿参数规范
* `REDIS_COMPENSATION_TTL_SECONDS` = 86400
* `ERR_REDIS_SYNC_LABEL_FAILED_500`: 向 Redis 写入补偿便签时发生连接故障。


---


# 第七章：网络安全规范：SSRF 防御与私有 IP (is_safe_url) 过滤算法

## 7.1 服务器端请求伪造（SSRF）风险
Agent 具备 `fetch_url` 工具，允许根据用户要求抓取任意外部网页内容。若攻击者诱导 Agent 抓取内部网络地址（如 `http://127.0.0.1:8000/admin` 或 `http://169.254.169.254/latest/meta-data/` 云服务器元数据），将造成极大的内部资产泄露风险。

## 7.2 `is_safe_url` 防御校验算法
在 `src/tools.py` 中，`fetch_url` 工具在发起真正的 HTTP 请求前，必须调用 `is_safe_url(url)` 函数进行三级拦截：

1. **协议校验**：仅允许 `http` 和 `https` 协议，拒绝 `file://`、`gopher://`、`dict://` 等非法 Scheme。
2. **域名解析校验**：通过 `socket.getaddrinfo` 将目标域名解析为具体 IP 地址。
3. **私有 IP 段拦截**：使用 Python `ipaddress` 模块，校验解析后的 IP 是否属于以下私有/保留网段：
   * `127.0.0.0/8` (环回地址)
   * `10.0.0.0/8` (A 类私有网段)
   * `172.16.0.0/12` (B 类私有网段)
   * `192.168.0.0/16` (C 类私有网段)
   * `169.254.0.0/16` (本地链路地址/云元数据地址)
   * `::1/128` (IPv6 环回地址)

### SSRF 错误码规范
* `ERR_SSRF_BLOCKED_PRIVATE_IP_403`: 目标 URL 解析为内部私有 IP，已被安全防御拦截。
* `ERR_SSRF_UNSUPPORTED_SCHEME_400`: 目标 URL 使用了不受支持的协议 Scheme。


---


# 第八章：前端 Vue3 虚拟滚动与大列表 SSE 渲染性能优化

## 8.1 频繁 SSE 消息与 Vue 响应式开销
在深度研究与长文本生成场景中，后端 SSE 流每秒可能推送数十个 `text` 或 `tool_run` 帧。如果直接将这些帧不断 `push` 到 Vue 3 的 `reactive` 数组中，频繁触发 DOM 重新渲染会导致浏览器 CPU 飙升甚至卡死。

## 8.2 渲染优化策略
1. **节流与缓冲队列（Buffer & Throttle）**：前端建立一个离屏缓冲区，将每 50ms 内接收到的文本帧拼接合并后，再一次性更新到 Vue 的 `shallowRef` 状态中，避免深度响应式监听。
2. **虚拟滚动（Virtual Scrolling）**：对于包含成百上千条历史消息或长文档报告的视口，使用 `vue-virtual-scroller` 仅渲染当前可见区域及上下缓冲区（O(1) 复杂度），极大降低 DOM 节点总数。

### 前端参数规范
* `FRONTEND_SSE_BUFFER_FLUSH_MS` = 50 (SSE 消息合并渲染节流间隔)
* `FRONTEND_VIRTUAL_SCROLL_ITEM_SIZE` = 60 (默认消息卡片预估高度)


---


# 第九章：RAG 混合召回（BM25 与 Vector）及 Reciprocal Rank Fusion (RRF) 算法

## 9.1 多路召回的必要性
纯语义向量检索（Vector Search）擅长抓取概念相似度，但对于专有名词、错误代码、函数名等精确字符极易漏召或排名靠后；纯全文检索（BM25）擅长精确字符匹配，但无法理解近义词与语义延伸。

混合召回将两者的优势结合，形成“粗筛双路 -> RRF 融合 -> CrossEncoder 重排”的三阶段完整流水线。

## 9.2 RRF 评分公式与精排
Reciprocal Rank Fusion（互惠名次融合）算法通过以下公式对来自 BM25 和 Vector 两个通道的候选集进行去重与融合重新打分：

$$RRF\_Score(d) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$

其中：
* $M$ 为召回通道集合（本系统 $M = \{\text{BM25}, \text{Vector}\}$）；
* $r_m(d)$ 为文档片段 $d$ 在通道 $m$ 中的排名位置（从 1 开始）；
* $k$ 为常数常取值 `60`，用以降低靠后排名的分值权重悬殊。

经过 RRF 融合打分后，取出 Top 20 的候选集，最后送入 `bge-reranker-base` 交叉编码器进行深度精准打分，挑选出 Top 5 喂给 LLM。

### RRF 参数规范
* `RRF_K_CONSTANT` = 60
* `RAG_HYBRID_TOP_K` = 20
* `RAG_FINAL_TOP_K` = 5


---


# 第十章：全链路结构化日志（structlog）与 Correlation ID 上下文透传

## 10.1 结构化 JSON 日志规范
在分布式与异步微服务体系中，传统的文本日志极难被 ELK 或 Grafana Loki 检索分析。系统全面采用 `structlog` 库，在生产环境下输出单行标准的 JSON 格式日志。

所有的日志输出必须包含以下基础键：
* `timestamp`: ISO8601 格式的标准 UTC 时间戳
* `level`: 日志级别 (`info`, `warning`, `error`, `exception`)
* `event`: 简短、大蛇形命名法（snake_case）的事件说明文本（如 `llm_invoke_start`, `db_save_failed`）
* `request_id`: 从 `contextvars` 中提取的 Correlation ID

## 10.2 日志上下文绑定示例
```python
import structlog
logger = structlog.get_logger(__name__)

# 在业务逻辑中绑定上下文参数
logger.info("vector_search_completed", hits_count=15, duration_ms=120, user_id=str(user_id))
```

### 日志配置规范
* `LOG_FORMAT` = "json" (生产环境) / "console" (本地开发环境)
* `ERR_LOGGING_CONTEXT_MISSING_500`: 日志上下文上下文中缺少必要的基础元数据。


---


# 第十一章：基于 Taskiq 的后台 Worker 任务队列与崩溃守卫（Task Guard）

## 11.1 Taskiq 异步任务调度
深度文档研究、向量批量生成及 Ragas 评估打分属于耗时较长的后台任务，不能在 API 线程中同步等待。系统引入 `Taskiq` 配合 Redis 消息 Broker 进行任务派发与消费。

定义任务示例：
```python
@redis_broker.task
async def evaluate_trace_task(trace_id: str, user_id: str) -> None:
    ...
```

## 11.2 Task 强引用防垃圾回收 Guard
在异步 Python 编程中，使用 `asyncio.create_task` 创建的后台 Task，若没有显式保留强引用，可能会在事件循环运行期间被垃圾回收器（GC）意外回收，导致任务无故中断且不报任何报错。

系统在 `src/tools.py` 和后台 Service 中实现了全局强引用集合 `background_tasks = set()`：
* 任务创建后：`task = asyncio.create_task(...)` -> `background_tasks.add(task)`
* 挂载回调：`task.add_done_callback(background_tasks.discard)`
* 异常捕获回调：在 `done_callback` 中显式调用 `task.exception()`，记录未捕获的致命异常。

### 任务参数规范
* `TASKIQ_WORKER_CONCURRENCY` = 4 (Worker 进程最大并发任务数)
* `ERR_TASK_GC_RECLAIMED_500`: 后台 Task 被垃圾回收器意外回收。


---


# 第十二章：系统限流与真实 IP 提取（Slowapi & X-Forwarded-For 安全处理）

## 12.1 Slowapi 速率限制
为了防止恶意用户刷爆大模型 API 额度，系统在 FastAPI 接口层挂载了 `slowapi` 限流器。不同的 API 路由配置了不同的限流策略：
* 普通对话接口 (`/agent/chat/stream`)：`10/minute` (每分钟最多 10 次)
* 登录认证接口 (`/auth/login`)：`5/minute` (每分钟最多 5 次)
* 文件上传接口 (`/file/upload`)：`20/minute`

## 12.2 真实 IP 安全提取算法
在反向代理（如 Nginx、Cloudflare）后面运行服务时，客户端请求的底层 `request.client.host` 通常是反向代理服务器的内部 IP。如果直接基于 `request.client.host` 限流，会导致所有用户共用一个额度限制。

系统在 `src/limiter.py` 中实现了安全的 `get_real_ip` 函数：
1. 优先读取 `X-Forwarded-For` 请求头。
2. 由于 `X-Forwarded-For` 可能被客户端伪造，系统按照自右向左的顺序，剥离掉已知的信任代理 IP，提取最外层的真实客户端 IP。
3. 若请求头不存在，回退使用 `request.client.host`。

### 限流响应与错误码
当请求超出限制时，Slowapi 中间件会拦截并返回 429 帧：
* `ERR_RATE_LIMIT_EXCEEDED_429`: 请求频率超出安全配额限制，请稍后再试。


---


# 第十三章：数据库审计日志（audit_log）与防抵赖合规设计

## 13.1 审计日志防抵赖要求
为了符合网络安全等级保护与合规审计要求，系统建立了专门的 `audit_logs` 数据库表，无感记录所有的敏感增删改操作（如用户登录、删除会话、删除文件、导出报告）。

## 13.2 异步无感审计埋点
审计日志写入逻辑通过 `audit_log()` 辅助函数实现。该函数自动从 `contextvars` 执行上下文中提取当前的 `user_id`、`conversation_id`、`ip_address` 以及 `user_agent`。

写库操作采用异步非阻塞方式进行，若审计日志写入数据库发生失败，系统仅记录 warning 日志，**绝对不阻断和影响主业务流程的正常响应**。

### 审计字段规范
* `action`: 操作行为（如 `user_login`, `delete_file`, `human_approve`）
* `resource`: 操作资源（如 `user`, `file_document`, `conversation`）
* `success`: 布尔值，记录操作成功或失败
* `ERR_AUDIT_LOG_WRITE_FAILED_500`: 审计日志写库失败警报。


---


# 第十四章：模型路由（ModelRouter）与 Qwen/DeepSeek 回退机制

## 14.1 多模型路由架构
系统集成了 DeepSeek 和 阿里云通义千问（Qwen）两个模型提供商。根据不同的业务节点需求，系统通过 `ModelRouter` 进行智能路由派发：
* **主推理节点（Agent Core）**：默认路由至 `deepseek-v4-pro` 或 `deepseek-v4-flash`。
* **低延迟简单节点（Query Rewrite / Title Update）**：路由至轻量级模型。
* **Fallback 备用节点**：当 DeepSeek 发生服务故障时，平滑回退至 `qwen-plus`。

## 14.2 自动降级与 Saga 补偿
在 Writer（报告生成）节点中，若挂载的主模型重试耗尽，系统触发 Saga 降级机制：将所有已收集到的原始 Intelligence 情报进行文本拼接，直接产出 Markdown 报告，并将报告的 `degraded` 标识设置为 `True`，同时在报告顶部显示警告标签：“当前报告由服务降级模式产出”。

### 路由错误码规范
* `ERR_MODEL_ROUTER_NO_BACKEND_503`: 所有配置的模型后端均无法提供服务。
* `ERR_MODEL_DEGRADED_OUTPUT_200`: 模型调用失败，当前输出为降级模式产出的半成品。


---


# 第十五章：基于 Ragas 的离线与在线评测体系落地规范

## 15.1 离线与在线双轨评估体系
评测体系是保证 AI Agent 迭代质量的“眼睛”。系统支持离线与在线双轨评估：
* **在线实时评估**：在 `chat_stream` 结束后，`evaluate_trace_task` 异步任务从 Langfuse 拉取最新的 Trace 数据，调用 Ragas 对用户实际对话进行打分，结果回传至 Langfuse 仪表盘。
* **离线回归评估**：基于 `golden_set.json` 黄金数据集，通过 `run_offline_eval.py` 在相同的沙盒环境下批量对不同版本的代码进行 Recall、Faithfulness 及 Answer Relevancy 对比跑分。

## 15.2 核心指标考核划线
* **Recall@5**：要求 $\ge 90.0\%$。
* **Faithfulness（忠实度）**：要求 $\ge 0.85$。
* **Answer Relevancy（相关度）**：要求 $\ge 0.80$。

### 评测配置规范
* `EVAL_GOLDEN_SET_SIZE` = 15
* `ERR_EVAL_TRACE_NOT_FOUND_404`: 在 Langfuse 中未找到待评估的 Trace ID。
* `ERR_EVAL_METRIC_COMPUTE_FAILED_500`: Ragas 打分计算过程发生崩溃。


---


# 第一章：基于 FastAPI 与 asyncio 的高并发异步架构规范

## 1.1 事件循环与线程池协同机制
在高性能 Web 服务开发中，FastAPI 依赖 Python 的 `asyncio` 事件循环处理高并发 I/O 请求。为了保证事件循环主线程不被 CPU 密集型任务或同步阻塞 I/O 挂起，系统必须严格区分异步协程与同步阻塞函数。
对于同步 CPU 密集型计算（如加密哈希计算、图像处理或大型 JSON 解析），必须通过 `asyncio.to_thread` 或 `run_in_executor` 将其派发至 ThreadPoolExecutor 线程池中运行。

### 配置参数规范
* `ASYNC_THREAD_POOL_MAX_WORKERS` = 64 (线程池最大工作线程数)
* `ASYNC_EVENT_LOOP_POLICY` = "uvloop" (生产环境高吞吐事件循环驱动)
* `ASYNC_TASK_TIMEOUT_SECONDS` = 30 (默认协程执行超时阈值)

## 1.2 异常边界与全局 Middleware 拦截
所有的 API 异常均需收拢至 `src/exceptions.py` 的统一分层异常体系中。全局中间件 `CorrelationIdMiddleware` 在接收到 HTTP 请求的瞬间，会自动生成或提取 `X-Request-ID`，并通过 Python 的 `contextvars` 模块将其绑定至当前的异步执行上下文。

### 错误响应码对照表
* `ERR_ASYNC_TIMEOUT_504`: 协程等待超时，系统放弃当前请求并记录日志。
* `ERR_ASYNC_THREAD_EXHAUSTED_503`: 线程池已满，拒绝新的 CPU 密集型任务派发。
* `ERR_INVALID_CORRELATION_ID_400`: 请求头中传入的 Correlation ID 格式非法。


*(数据版本代号: V-REF-02)*


---


# 第二章：PostgreSQL 与 pgvector 向量检索及 HNSW/IVFFlat 索引原理

## 2.1 pgvector 扩展及余弦距离匹配
PostgreSQL 结合 `pgvector` 扩展为 AI Agent 提供了高效的向量持久化与相似度检索能力。在我们的向量表 `file_chunks` 中，`embedding` 字段被声明为 `Vector(768)` 类型，专门用于存放 768 维度的 BGE 语义嵌入。

在 SQL 查询中，余弦距离运算符为 `<=>`，L2 距离运算符为 `<->`，内积运算符为 `<#>`。
根据定义，余弦相似度（Cosine Similarity）与余弦距离（Cosine Distance）的关系公式为：
$$\text{Cosine Similarity} = 1 - \text{Cosine Distance}$$

## 2.2 HNSW 与 IVFFlat 索引选择策略
在 pgvector 中，主要支持 IVFFlat（Inverted File Flat）与 HNSW（Hierarchical Navigable Small World）两种向量索引：
* **IVFFlat 索引**：基于 K-Means 聚类中心划分倒排列表。建索引速度快，但查询前必须设置 `SET ivfflat.probes = 10`。在数据量小或频繁更新时召回率有波动。
* **HNSW 索引**：基于分层小世界图结构。建索引耗费更多内存与时间，但查询性能极佳且不需要预热配置，能够在无需完全扫描的情况下实现高达 98%+ 的 Recall@K。

### 索引配置参数规范
* `PG_VECTOR_INDEX_TYPE` = "hnsw"
* `PG_VECTOR_HNSW_M` = 16 (每个图节点的最大双向链接数)
* `PG_VECTOR_HNSW_EF_CONSTRUCTION` = 64 (构建索引时的动态候选列表大小)
* `ERR_PG_VECTOR_DIM_MISMATCH_422`: 传入的查询向量维度与表声明的 768 维不一致。
* `ERR_PG_VECTOR_INDEX_NOT_READY_500`: 向量索引尚未创建完成，回退至全表顺序扫描。


*(数据版本代号: V-REF-02)*


---


# 第三章：大语言模型（LLM）防线与三态熔断器（LLM_BREAKER）设计

## 3.1 进程内三态熔断器机制
为防止底层 LLM 供应商（如 DeepSeek 或 Qwen）因网络故障、机房宕机或 API 429 大规模限流导致整个 Web 服务响应卡死，系统在 `src/resilience.py` 中实现了进程内的“三态熔断器（LLM_BREAKER）”。

熔断器包含三种内部状态：
1. **CLOSED（关闭状态）**：正常转发所有 LLM 调用请求。当连续失败次数达到阈值 `5` 次时，触发熔断，状态自动切换至 OPEN。
2. **OPEN（开启状态）**：直接拒绝所有 LLM 调用请求，立即抛出 `LLMBreakerOpenError`，绝不向第三方 API 发起任何网络连接。经过冷却时间 `30` 秒后，状态自动切换至 HALF-OPEN。
3. **HALF-OPEN（半开状态）**：允许试探性地放行 `1` 次 LLM 请求。若该请求成功，则熔断器恢复至 CLOSED 状态并清空失败计数器；若该请求依然失败，则重新切回 OPEN 状态并重新开始 30 秒冷却。

## 3.2 错误类型重试与映射规范
* **429 Rate Limit (Too Many Requests)**：自动触发指数退避重试（Exponential Backoff），最大重试次数为 `3` 次，基础等待时间为 `2` 秒。
* **402 Payment Required (欠费)**：不可重试错误，直接映射为致命业务异常 `LLMPaymentRequiredError`，终止当前 Agent 执行流。
* **400 Context Length Exceeded (上下文超限)**：自动触发 `ainvoke_with_context_recovery`，自动裁剪历史对话的最早 30% 消息，并进行单次重试。

### 熔断器配置参数规范
* `LLM_BREAKER_FAILURE_THRESHOLD` = 5 (连续失败阈值)
* `LLM_BREAKER_COOL_DOWN_SECONDS` = 30 (OPEN 状态冷却秒数)
* `ERR_LLM_BREAKER_OPEN_503`: 熔断器处于开启状态，请求被拦截。
* `ERR_LLM_CONTEXT_OVERFLOW_400`: 上下文长度超出大模型 Token 容限上限。


*(数据版本代号: V-REF-02)*


---


# 第四章：LangGraph 状态持久化与 PostgreSQL Checkpointer 架构

## 4.1 LazyAsyncPostgresSaver 设计原理
LangGraph 1.2.4 使用 Checkpointer 机制在每个 Graph Node 执行完毕后自动将 `State` 状态快照持久化至数据库。在主流程中，由于应用启动阶段事件循环（Event Loop）可能尚未完全就绪，直接实例化 `AsyncPostgresSaver` 会触发底层事件循环绑定异常。

为此，系统自研了 `LazyAsyncPostgresSaver` 类，继承自 `AsyncPostgresSaver`。它采用延迟初始化（Lazy Initialization）设计模式，在首次触发 `get_tuple`、`put` 或 `setup` 方法时，才在运行中的事件循环上下文中安全激活底层连接池。

## 4.2 状态快照与中断恢复（HITL）
当 Agent 推理遇到敏感操作（如删除数据库记录、执行高危 Shell 命令）时，图会在 Tool 节点前触发 `interrupt_before=["tools"]`，将图执行挂起。

系统通过 `thread_id`（通常与 `conversation_id` 保持一致）隔离不同会话的状态。当用户在前端点击“同意”或“拒绝”后，路由层通过 `/agent/resume` 接口向图发送 `Command(resume="continue")` 或拒绝 Command，驱动图继续向下流转。

### 状态配置参数规范
* `LANGGRAPH_RECURSION_LIMIT` = 25 (主图节点最大递归深度阀值)
* `LANGGRAPH_RESEARCH_RECURSION_LIMIT` = 50 (深度研究子图最大递归深度)
* `ERR_GRAPH_RECURSION_EXCEEDED_429`: 图触发无限递归死循环安全阀。
* `ERR_CHECKPOINT_NOT_FOUND_404`: 传入的 thread_id 在数据库中未找到任何历史状态快照。


*(数据版本代号: V-REF-02)*


---


# 第五章：Agent 容错机制：工具异常分类（ToolRetryableError/ToolFatalError/ToolDangerousError）

## 5.1 三级工具异常分类体系
当 Agent 调用外部 Tool（如 Tavily 搜索、网页抓取、向量检索）发生故障时，系统将工具异常严格划分为三级，防止工具失败拖垮整个 Agent 执行链：

1. **`ToolRetryableError`（可重试工具错误）**：
   * 触发场景：Tavily 网络超时、HTTP 502/503 瞬时错误、解析 HTML 临时失败。
   * 处理逻辑：由 `error_handler` 节点捕获，自动重试调用该工具，最大重试次数为 `3` 次。
2. **`ToolFatalError`（致命工具错误）**：
   * 触发场景：传入参数格式完全错误、数据库连接彻底中断、请求无权限。
   * 处理逻辑：不再重试，由 `error_summary` 节点将其转化为结构化中文错误提示返回给 LLM，提示大模型更改策略或告知用户。
3. **`ToolDangerousError`（危险工具操作）**：
   * 触发场景：工具检测到即将修改系统配置文件、删除全局数据或执行危险命令。
   * 处理逻辑：立刻中断图执行，强制进入人机协同（HITL）审批流。

## 5.2 错误结构化 JSON 规范
工具在抛出异常时，必须返回规范的 JSON 结构给 LLM 节点：
```json
{
  "status": "error",
  "error_type": "retryable",
  "error_code": "ERR_TOOL_TAVILY_TIMEOUT_504",
  "message": "Tavily Web Search API 超时",
  "suggestion": "请更换更具体的关键词重试"
}
```

### 工具配置参数规范
* `TOOL_MAX_RETRY_ATTEMPTS` = 3 (可重试工具的最大重试次数)
* `TOOL_TIMEOUT_SECONDS` = 10 (单个工具调用的硬超时时间)


*(数据版本代号: V-REF-02)*


---


# 第六章：Redis 分布式便签补偿机制（need_sync）与数据一致性降级

## 6.1 PostgreSQL 写入失败与 asyncio.shield 保护
在流式对话（`chat_stream`）和恢复执行（`resume`）流程中，大模型生成的回答片段已经成功通过 SSE（Server-Sent Events）推送给了前端用户。如果在收尾阶段写入 PostgreSQL 数据库（如消息落库、Embedding 存储）发生突发故障（如 DB 暂时锁死），系统绝对不能向前端发送 Error 帧破坏用户体验。

为此，落库异步任务使用 `asyncio.shield` 进行保护。当 DB 写入异常被捕获后，系统触发降级机制——向 Redis 中写入一张“分布式补偿便签”。

## 6.2 Redis 补偿便签规范
* **Key 格式**：`need_sync:{conversation_id}`
* **TTL（过期时间）**：86400 秒 (24 小时)
* **Value 内容**：存储包含 `conversation_id`、失败来源（`chat_stream` 或 `resume`）及时间戳的 JSON 字符串。
* **补偿 Worker 逻辑**：后台的定时数据补偿 Worker 轮询扫描 `need_sync:*` 键，根据 `conversation_id` 从 LangGraph Checkpointer (`app.aget_state`) 中重新提取状态真相，重新补写入 PostgreSQL。

### 补偿参数规范
* `REDIS_COMPENSATION_TTL_SECONDS` = 86400
* `ERR_REDIS_SYNC_LABEL_FAILED_500`: 向 Redis 写入补偿便签时发生连接故障。


*(数据版本代号: V-REF-02)*


---


# 第七章：网络安全规范：SSRF 防御与私有 IP (is_safe_url) 过滤算法

## 7.1 服务器端请求伪造（SSRF）风险
Agent 具备 `fetch_url` 工具，允许根据用户要求抓取任意外部网页内容。若攻击者诱导 Agent 抓取内部网络地址（如 `http://127.0.0.1:8000/admin` 或 `http://169.254.169.254/latest/meta-data/` 云服务器元数据），将造成极大的内部资产泄露风险。

## 7.2 `is_safe_url` 防御校验算法
在 `src/tools.py` 中，`fetch_url` 工具在发起真正的 HTTP 请求前，必须调用 `is_safe_url(url)` 函数进行三级拦截：

1. **协议校验**：仅允许 `http` 和 `https` 协议，拒绝 `file://`、`gopher://`、`dict://` 等非法 Scheme。
2. **域名解析校验**：通过 `socket.getaddrinfo` 将目标域名解析为具体 IP 地址。
3. **私有 IP 段拦截**：使用 Python `ipaddress` 模块，校验解析后的 IP 是否属于以下私有/保留网段：
   * `127.0.0.0/8` (环回地址)
   * `10.0.0.0/8` (A 类私有网段)
   * `172.16.0.0/12` (B 类私有网段)
   * `192.168.0.0/16` (C 类私有网段)
   * `169.254.0.0/16` (本地链路地址/云元数据地址)
   * `::1/128` (IPv6 环回地址)

### SSRF 错误码规范
* `ERR_SSRF_BLOCKED_PRIVATE_IP_403`: 目标 URL 解析为内部私有 IP，已被安全防御拦截。
* `ERR_SSRF_UNSUPPORTED_SCHEME_400`: 目标 URL 使用了不受支持的协议 Scheme。


*(数据版本代号: V-REF-02)*


---


# 第八章：前端 Vue3 虚拟滚动与大列表 SSE 渲染性能优化

## 8.1 频繁 SSE 消息与 Vue 响应式开销
在深度研究与长文本生成场景中，后端 SSE 流每秒可能推送数十个 `text` 或 `tool_run` 帧。如果直接将这些帧不断 `push` 到 Vue 3 的 `reactive` 数组中，频繁触发 DOM 重新渲染会导致浏览器 CPU 飙升甚至卡死。

## 8.2 渲染优化策略
1. **节流与缓冲队列（Buffer & Throttle）**：前端建立一个离屏缓冲区，将每 50ms 内接收到的文本帧拼接合并后，再一次性更新到 Vue 的 `shallowRef` 状态中，避免深度响应式监听。
2. **虚拟滚动（Virtual Scrolling）**：对于包含成百上千条历史消息或长文档报告的视口，使用 `vue-virtual-scroller` 仅渲染当前可见区域及上下缓冲区（O(1) 复杂度），极大降低 DOM 节点总数。

### 前端参数规范
* `FRONTEND_SSE_BUFFER_FLUSH_MS` = 50 (SSE 消息合并渲染节流间隔)
* `FRONTEND_VIRTUAL_SCROLL_ITEM_SIZE` = 60 (默认消息卡片预估高度)


*(数据版本代号: V-REF-02)*


---


# 第九章：RAG 混合召回（BM25 与 Vector）及 Reciprocal Rank Fusion (RRF) 算法

## 9.1 多路召回的必要性
纯语义向量检索（Vector Search）擅长抓取概念相似度，但对于专有名词、错误代码、函数名等精确字符极易漏召或排名靠后；纯全文检索（BM25）擅长精确字符匹配，但无法理解近义词与语义延伸。

混合召回将两者的优势结合，形成“粗筛双路 -> RRF 融合 -> CrossEncoder 重排”的三阶段完整流水线。

## 9.2 RRF 评分公式与精排
Reciprocal Rank Fusion（互惠名次融合）算法通过以下公式对来自 BM25 和 Vector 两个通道的候选集进行去重与融合重新打分：

$$RRF\_Score(d) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$

其中：
* $M$ 为召回通道集合（本系统 $M = \{\text{BM25}, \text{Vector}\}$）；
* $r_m(d)$ 为文档片段 $d$ 在通道 $m$ 中的排名位置（从 1 开始）；
* $k$ 为常数常取值 `60`，用以降低靠后排名的分值权重悬殊。

经过 RRF 融合打分后，取出 Top 20 的候选集，最后送入 `bge-reranker-base` 交叉编码器进行深度精准打分，挑选出 Top 5 喂给 LLM。

### RRF 参数规范
* `RRF_K_CONSTANT` = 60
* `RAG_HYBRID_TOP_K` = 20
* `RAG_FINAL_TOP_K` = 5


*(数据版本代号: V-REF-02)*


---


# 第十章：全链路结构化日志（structlog）与 Correlation ID 上下文透传

## 10.1 结构化 JSON 日志规范
在分布式与异步微服务体系中，传统的文本日志极难被 ELK 或 Grafana Loki 检索分析。系统全面采用 `structlog` 库，在生产环境下输出单行标准的 JSON 格式日志。

所有的日志输出必须包含以下基础键：
* `timestamp`: ISO8601 格式的标准 UTC 时间戳
* `level`: 日志级别 (`info`, `warning`, `error`, `exception`)
* `event`: 简短、大蛇形命名法（snake_case）的事件说明文本（如 `llm_invoke_start`, `db_save_failed`）
* `request_id`: 从 `contextvars` 中提取的 Correlation ID

## 10.2 日志上下文绑定示例
```python
import structlog
logger = structlog.get_logger(__name__)

# 在业务逻辑中绑定上下文参数
logger.info("vector_search_completed", hits_count=15, duration_ms=120, user_id=str(user_id))
```

### 日志配置规范
* `LOG_FORMAT` = "json" (生产环境) / "console" (本地开发环境)
* `ERR_LOGGING_CONTEXT_MISSING_500`: 日志上下文上下文中缺少必要的基础元数据。


*(数据版本代号: V-REF-02)*


---


# 第十一章：基于 Taskiq 的后台 Worker 任务队列与崩溃守卫（Task Guard）

## 11.1 Taskiq 异步任务调度
深度文档研究、向量批量生成及 Ragas 评估打分属于耗时较长的后台任务，不能在 API 线程中同步等待。系统引入 `Taskiq` 配合 Redis 消息 Broker 进行任务派发与消费。

定义任务示例：
```python
@redis_broker.task
async def evaluate_trace_task(trace_id: str, user_id: str) -> None:
    ...
```

## 11.2 Task 强引用防垃圾回收 Guard
在异步 Python 编程中，使用 `asyncio.create_task` 创建的后台 Task，若没有显式保留强引用，可能会在事件循环运行期间被垃圾回收器（GC）意外回收，导致任务无故中断且不报任何报错。

系统在 `src/tools.py` 和后台 Service 中实现了全局强引用集合 `background_tasks = set()`：
* 任务创建后：`task = asyncio.create_task(...)` -> `background_tasks.add(task)`
* 挂载回调：`task.add_done_callback(background_tasks.discard)`
* 异常捕获回调：在 `done_callback` 中显式调用 `task.exception()`，记录未捕获的致命异常。

### 任务参数规范
* `TASKIQ_WORKER_CONCURRENCY` = 4 (Worker 进程最大并发任务数)
* `ERR_TASK_GC_RECLAIMED_500`: 后台 Task 被垃圾回收器意外回收。


*(数据版本代号: V-REF-02)*


---


# 第十二章：系统限流与真实 IP 提取（Slowapi & X-Forwarded-For 安全处理）

## 12.1 Slowapi 速率限制
为了防止恶意用户刷爆大模型 API 额度，系统在 FastAPI 接口层挂载了 `slowapi` 限流器。不同的 API 路由配置了不同的限流策略：
* 普通对话接口 (`/agent/chat/stream`)：`10/minute` (每分钟最多 10 次)
* 登录认证接口 (`/auth/login`)：`5/minute` (每分钟最多 5 次)
* 文件上传接口 (`/file/upload`)：`20/minute`

## 12.2 真实 IP 安全提取算法
在反向代理（如 Nginx、Cloudflare）后面运行服务时，客户端请求的底层 `request.client.host` 通常是反向代理服务器的内部 IP。如果直接基于 `request.client.host` 限流，会导致所有用户共用一个额度限制。

系统在 `src/limiter.py` 中实现了安全的 `get_real_ip` 函数：
1. 优先读取 `X-Forwarded-For` 请求头。
2. 由于 `X-Forwarded-For` 可能被客户端伪造，系统按照自右向左的顺序，剥离掉已知的信任代理 IP，提取最外层的真实客户端 IP。
3. 若请求头不存在，回退使用 `request.client.host`。

### 限流响应与错误码
当请求超出限制时，Slowapi 中间件会拦截并返回 429 帧：
* `ERR_RATE_LIMIT_EXCEEDED_429`: 请求频率超出安全配额限制，请稍后再试。


*(数据版本代号: V-REF-02)*


---


# 第十三章：数据库审计日志（audit_log）与防抵赖合规设计

## 13.1 审计日志防抵赖要求
为了符合网络安全等级保护与合规审计要求，系统建立了专门的 `audit_logs` 数据库表，无感记录所有的敏感增删改操作（如用户登录、删除会话、删除文件、导出报告）。

## 13.2 异步无感审计埋点
审计日志写入逻辑通过 `audit_log()` 辅助函数实现。该函数自动从 `contextvars` 执行上下文中提取当前的 `user_id`、`conversation_id`、`ip_address` 以及 `user_agent`。

写库操作采用异步非阻塞方式进行，若审计日志写入数据库发生失败，系统仅记录 warning 日志，**绝对不阻断和影响主业务流程的正常响应**。

### 审计字段规范
* `action`: 操作行为（如 `user_login`, `delete_file`, `human_approve`）
* `resource`: 操作资源（如 `user`, `file_document`, `conversation`）
* `success`: 布尔值，记录操作成功或失败
* `ERR_AUDIT_LOG_WRITE_FAILED_500`: 审计日志写库失败警报。


*(数据版本代号: V-REF-02)*


---


# 第十四章：模型路由（ModelRouter）与 Qwen/DeepSeek 回退机制

## 14.1 多模型路由架构
系统集成了 DeepSeek 和 阿里云通义千问（Qwen）两个模型提供商。根据不同的业务节点需求，系统通过 `ModelRouter` 进行智能路由派发：
* **主推理节点（Agent Core）**：默认路由至 `deepseek-v4-pro` 或 `deepseek-v4-flash`。
* **低延迟简单节点（Query Rewrite / Title Update）**：路由至轻量级模型。
* **Fallback 备用节点**：当 DeepSeek 发生服务故障时，平滑回退至 `qwen-plus`。

## 14.2 自动降级与 Saga 补偿
在 Writer（报告生成）节点中，若挂载的主模型重试耗尽，系统触发 Saga 降级机制：将所有已收集到的原始 Intelligence 情报进行文本拼接，直接产出 Markdown 报告，并将报告的 `degraded` 标识设置为 `True`，同时在报告顶部显示警告标签：“当前报告由服务降级模式产出”。

### 路由错误码规范
* `ERR_MODEL_ROUTER_NO_BACKEND_503`: 所有配置的模型后端均无法提供服务。
* `ERR_MODEL_DEGRADED_OUTPUT_200`: 模型调用失败，当前输出为降级模式产出的半成品。


*(数据版本代号: V-REF-02)*


---


# 第十五章：基于 Ragas 的离线与在线评测体系落地规范

## 15.1 离线与在线双轨评估体系
评测体系是保证 AI Agent 迭代质量的“眼睛”。系统支持离线与在线双轨评估：
* **在线实时评估**：在 `chat_stream` 结束后，`evaluate_trace_task` 异步任务从 Langfuse 拉取最新的 Trace 数据，调用 Ragas 对用户实际对话进行打分，结果回传至 Langfuse 仪表盘。
* **离线回归评估**：基于 `golden_set.json` 黄金数据集，通过 `run_offline_eval.py` 在相同的沙盒环境下批量对不同版本的代码进行 Recall、Faithfulness 及 Answer Relevancy 对比跑分。

## 15.2 核心指标考核划线
* **Recall@5**：要求 $\ge 90.0\%$。
* **Faithfulness（忠实度）**：要求 $\ge 0.85$。
* **Answer Relevancy（相关度）**：要求 $\ge 0.80$。

### 评测配置规范
* `EVAL_GOLDEN_SET_SIZE` = 15
* `ERR_EVAL_TRACE_NOT_FOUND_404`: 在 Langfuse 中未找到待评估的 Trace ID。
* `ERR_EVAL_METRIC_COMPUTE_FAILED_500`: Ragas 打分计算过程发生崩溃。


*(数据版本代号: V-REF-02)*
