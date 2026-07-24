# Agent 错误处理工业级体系设计文档（v2 · 联网修订版）

> 范围：全套工业级体系。新依赖：`tenacity` + `structlog`。本文件是**设计文档**，供审阅；实施由 yc 本人执行。
> v2 变更：基于 LangGraph/LangChain/DeepSeek 官方文档与大厂生产实践联网调研后修订。文末有【修订记录】与来源。

## Context（为什么做）

当前项目的错误处理是"局部有亮点、整体无体系"：

- `agent_node` / `researcher_node` / `writer_node` 对 LLM 调用**零容错**，DeepSeek 的 429/5xx/timeout 会直接抛穿；研究图靠外层兜底标 failed，**一次瞬时抖动就判整个研究任务死刑**。
- 全项目**无重试机制**、无显式 LLM 超时、无自定义异常体系、无错误码。
- `chat_stream` 中 `save_data_to_db` 在 `except` 之前，LLM 中途失败会导致"用户消息已入库、AI 回复未入库"的**状态断裂**；流式到一半抛错时前端收到"半句话 + error"。
- 异常信息裸奔：全局 handler 和 SSE error 帧直接 `str(e)` 给前端，可能泄露栈/SQL/内部细节。
- 日志只有 `main.py` 一行 `basicConfig`，无 correlation id，多处 `traceback.print_exc()` 直打 stderr。
- **潜在 bug**：`graph.py` / `research_graph.py` 编译时未设 `recursion_limit`（LangGraph 默认 25 超步），而 `should_continue` 允许主图 100 次、研究图 20 次工具循环（每轮 agent→tools = 2 超步），高工具调用率时会撞 `GraphRecursionError` 直接崩。

目标：建立错误分类 + 分层重试 + 模型/工具 fallback + 熔断 + 流式边界 + 结构化日志 + 对外脱敏 + 状态一致性，使 Agent 在外部服务抖动下优雅降级与恢复。

---

## 设计原则

1. **先分类，再处理**。采用 LangGraph 官方【Thinking in LangGraph】的错误四分类（见下），不同类用不同手段。
2. **分层重试，不重叠**。HTTP 层（`ChatOpenAI.max_retries`）与节点层（LangGraph `RetryPolicy`）各管各的，**禁止对同一错误类双重重试**，避免 2×3=6 的重试风暴。
3. **可重试 vs 不可重试显式区分**：瞬时错误（429 限流 / 5xx / timeout / 网络抖动）退避重试；确定性错误（402 余额不足 / 401 鉴权 / 422 参数 / 上下文超限）不重试、走降级。
4. **幂等性决定重试策略**：幂等操作（只读检索、search_web）可放心重试；非幂等操作（`spawn_deep_research` 触发后台任务、写库）不盲目重试，靠幂等键去重。
5. **checkpointer 是 source of truth，业务库是投影**：失败后以图状态为准做补偿（saga），不强行写半成品。
6. **对外脱敏、对内可观测**：客户端只收错误码 + 通用中文；详情进结构化日志 + Langfuse。
7. **工具错误优先"返回字符串让 LLM 决策"**（LangGraph `ToolNode(handle_tool_errors=...)` 范式），仅不可恢复才向上抛。

---

## 0. 错误四分类（先于一切处理）

采用 LangGraph 官方分类（来源：docs.langchain.com Thinking in LangGraph）：

| 类别 | 例子 | 处理手段 |
|---|---|---|
| **Transient（瞬时）** | 429 限流、500/503、timeout、网络抖动 | 退避重试（`RetryPolicy` + `max_retries`） |
| **LLM-recoverable（模型可自纠）** | 工具参数错、工具抛错、结构化输出不符 | 错误回灌成 `ToolMessage` 让 LLM 换思路；`with_structured_output` 重试 |
| **User-fixable（用户可修）** | 输入超长、权限不足、文件未上传 | `interrupt()` 或返回明确错误码让用户改 |
| **Unexpected（意外）** | 未预期异常、DB 连接断 | 兜底捕获 + `error_handler` saga 补偿 + 告警 |

> 注意：DeepSeek 的 429 **不一定是限流**——必须看响应体/错误码区分。见 B 节 DeepSeek 映射。

---

## A. 分层异常体系

新建 `backend/src/exceptions.py`：

```
AgentError(Exception)                  # 基类，持有 code:str、message:str、recoverable:bool
├── InfraError                          # 基础设施
│   ├── DatabaseError
│   └── RedisError
├── LLMError                            # LLM provider
│   ├── LLMRateLimitError        (429 限流, 可重试)
│   ├── LLMTimeoutError          (可重试)
│   ├── LLMServerError           (500/503, 可重试)
│   ├── LLMContextOverflowError  (400 context length, 不可重试 → 裁剪降级)
│   ├── LLMBalanceError          (402 余额不足, 不可重试 → 告警)
│   └── LLMAuthError             (401, 不可重试)
├── ToolError
│   ├── ToolTimeoutError
│   └── ToolExecutionError
└── BusinessError                       # 业务校验（权限/参数/状态）
```

- 错误码前缀分类：`LLM_*` / `TOOL_*` / `DB_*` / `BIZ_*`，机器可读。
- 基类提供 `to_sse_frame()` 与 `to_http_response()`，统一对外格式。
- `message` 为用户安全中文；`detail` 只进日志。

---

## B. LLM 调用鲁棒性（核心，已按官方机制重写）

### B.1 三层重试分工（关键修订）

| 层 | 机制 | 负责的错误 | 配置 |
|---|---|---|---|
| HTTP 层 | `ChatOpenAI(max_retries=2, timeout=60)` | 429 限流 / 500 / 503 / 连接错 | langchain_openai 内置，指数退避 |
| 节点层 | `add_node(..., retry=RetryPolicy(...))` | 节点执行中的瞬时异常 | LangGraph 原生（基于 tenacity） |
| 自定义层 | `resilience.py` 的薄封装 | 上下文超限裁剪、余额检测、熔断 | 仅做 RetryPolicy 做不了的事 |

**v1 错误纠正**：v1 说"设 `max_retries=0` 全交 tenacity"——不采纳。官方/社区共识是两层不同职责、配合使用最强；但要保证**同一错误只在一层重试**（HTTP 层吃掉的 429 不再触发节点层 RetryPolicy 的同类重试）。

### B.2 主用 LangGraph RetryPolicy（官方地道写法）

来源：reference.langchain.com RetryPolicy + docs.langchain.com Thinking in LangGraph。

```python
from langgraph.types import RetryPolicy

# graph.py / research_graph.py
workflow.add_node("agent", agent_node, retry=RetryPolicy(
    max_attempts=3, initial_interval=1.0, backoff_factor=2.0,
    max_interval=8, jitter=True,
    retry_on=(LLMRateLimitError, LLMTimeoutError, LLMServerError),
))
```

`RetryPolicy` 属性：`initial_interval` / `backoff_factor` / `max_interval` / `max_attempts` / `jitter` / `retry_on`。默认 `retry_on=default_retry_on`（仅瞬时错误），建议显式指定 `retry_on` 为自定义异常类，**把 402 余额、401 鉴权、上下文超限排除在重试外**。

> 已知坑（来源：langgraph issue #6027）：`RetryPolicy` **不会重试 Pydantic `ValidationError`**。若用 `with_structured_output` 期望重试校验失败，需在节点内自行 try/except 重试，不要依赖 RetryPolicy。

### B.3 节点级 `error_handler`（saga 补偿，官方机制）

来源：docs.langchain.com Thinking in LangGraph（NodeError / error_handler）。

```python
from langgraph.errors import NodeError

def writer_error_handler(state, error: NodeError):
    logger.exception("writer failed, degrade to raw intel", error=error)
    return Command(update={"report_md": <researcher 原始情报>, "degraded": True}, goto=END)

workflow.add_node("writer", writer_node,
                  retry=RetryPolicy(max_attempts=3, retry_on=(LLMRateLimitError,)),
                  error_handler=writer_error_handler)
```

writer 重试耗尽 → `error_handler` 退化为返回 researcher 原始情报作为 `report_md`，标记 `degraded=True`，而非整个任务 failed。这是官方 saga/compensation 范式。

### B.4 模型 fallback（LangChain 原生 `.with_fallbacks`）

来源：agnxi langchain-rate-limits（`.with_fallbacks` 是 LangChain 内置模型降级）。

```python
# research_graph.py：writer 用 pro，flash 作 fallback
writer_llm = ChatOpenAI(model="deepseek-v4-pro", ...).with_fallbacks([
    ChatOpenAI(model="deepseek-v4-flash", ...)
])
```

pro 限流/失败 → 自动切 flash。比手写降级链更省事，且与 RetryPolicy 不冲突（fallback 是换模型，retry 是同模型重试）。

### B.5 DeepSeek 错误映射（官方错误码，关键修订）

来源：api-docs.deepseek.com/quick_start/error_codes（官方）+ 第三方实测（Retry-After）。

| HTTP | DeepSeek 含义 | 可重试 | 映射到 |
|---|---|---|---|
| 402 | Insufficient Balance 余额不足 | ❌ | `LLMBalanceError` → 告警，不重试 |
| 401 | Authentication Failed | ❌ | `LLMAuthError` |
| 422 | Invalid Parameters | ❌ | `BusinessError` |
| 400 | （含 context length exceeded） | ❌ | `LLMContextOverflowError` → 裁剪降级 |
| 429 | Rate Limit Reached（账号级并发超限） | ✅ | `LLMRateLimitError` |
| 500 | Server Error | ✅ | `LLMServerError` |
| 503 | Server Overloaded | ✅ | `LLMServerError` |

**关键**：429 必须看响应体。DeepSeek 限流是**账号级并发上限**（第三方 2026-07 数据：v4-pro 并发 500、v4-flash 2500，非官方固定值），不是 RPM/TPM 表。`Retry-After` 头官方未明确文档化，但第三方实测 429 响应会带 → **若存在则作为退避下限**（`wait` 取 `max(Retry-After, 指数退避值)`）。

> 项目实测待办：记录一段时间 DeepSeek 429 响应头，确认 `Retry-After` 是否稳定返回。若不稳定，退化为纯指数退避 + jitter。

### B.6 上下文超限降级

捕获 `LLMContextOverflowError` → 按"保留 SystemMessage + 最近 N 条"裁剪 → 重试一次（仅一次，防循环）。放在 `resilience.py` 的薄封装里，因为这是消息变换、不是简单重试，RetryPolicy 做不了。

### B.7 `resilience.py` 职责重定义（v1 的 `safe_llm_invoke` 降级）

v1 把所有重试塞进 `safe_llm_invoke` —— 改为**薄封装**，只做 RetryPolicy 做不了的三件事：
1. DeepSeek openai 异常 → 自定义异常映射（含 402 余额检测）。
2. 上下文超限裁剪 + 单次重试。
3. 轻量熔断（见 J）。

重试本身交给 `RetryPolicy` + `max_retries`，`safe_llm_invoke` 不再持有重试逻辑。

---

## C. SSE 流式边界处理

`service/agent.py` 的 `chat_stream` / `resume` 重构：

1. **统一错误帧格式**：`{type:'error', code, message, recoverable, partial}`，替换现有 `{type:'error', message:str(e)}`。
2. **流式中途异常**：已 yield 的 text 无法收回 → error 帧带 `partial:true`，前端标记"生成中断，可重试"。
3. **`save_data_to_db` 失败独立处理**：从主 `except` 剥离。LLM 已成功回复时，落库失败只 `logger.exception` + 告警，**不影响已成功的回复**，`done` 帧照常发；入队补偿任务（见 H）。
4. **resume 路径补 `asyncio.shield`**：与 `chat_stream` 对称。
5. **generator 顶部统一 try/except**：任何未预期异常转 error 帧，不泄露 `str(e)`。
6. **`GraphRecursionError` 单独捕获**：转 `{code:'RECURSION_LIMIT', message:'对话过长，请新开会话或精简历史'}`，并落库标记会话需压缩。

---

## D. 后台任务鲁棒性

`service/file_research.py`：

1. `process_file_in_background`（line 134）：失败时除标 `failed` 外，**通过 `notifier_manager` 通知前端**（当前缺失，前端会一直等）。
2. `asyncio.gather`（line 110，embedding 计算）加 `return_exceptions=True` + 过滤失败项，单 chunk 失败不全盘失败。
3. `spawn_deep_research`（`tools.py:159`）的 `asyncio.create_task`：**非幂等**（重复触发会起多个研究任务），不盲目重试；持有 task 引用至模块级 `set` + `done_callback` 记录未处理异常，防 GC 静默丢失。
4. 研究图整体用 `asyncio.wait_for(research_app.ainvoke(...), timeout=RESEARCH_TASK_TIMEOUT)` 包裹（见 E）。

---

## E. 超时控制（deadline 预算模型，已修订）

来源：medium "7 Retry + Timeout Rules for LangChain Tools"（用 deadline 不只是 timeout）。

1. **per-attempt 超时**：`ChatOpenAI(timeout=60, max_retries=2)`。
2. **整体 deadline 预算**：工具步骤用"per-attempt timeout + overall deadline"双层，例如工具单次 2s、整步 6s 预算，防止"永不失败只卡死"。
3. **图任务级 deadline**：`asyncio.wait_for(research_app.ainvoke(...), timeout=300)`，超时转 `LLMTimeoutError` 走失败通知。
4. **工具层**：`search_web`/`fetch_url` 已有 10s（保留），纳入 deadline 预算。
5. 参数全部进 `config.py`：`LLM_TIMEOUT` / `LLM_MAX_ATTEMPTS` / `RESEARCH_TASK_TIMEOUT` / `TOOL_DEADLINE`，可环境变量覆盖。

---

## F. 日志与可观测性（structlog + correlation id）

新建 `backend/src/logging_config.py` 与 `backend/src/middleware.py`：

1. **structlog 配置**：开发态 console 渲染，生产态 JSON；统一字段 `timestamp / level / event / request_id / conversation_id / user_id / trace_id / node`。
2. **correlation id 中间件**：FastAPI middleware 生成 `request_id`，提取 `conversation_id`，注入 `contextvars`，structlog 自动带入。一条请求所有日志可串。
3. **替换 `traceback.print_exc()`**：全项目改 `logger.exception(...)`，自动带栈与 contextvars。
4. **错误上报 Langfuse**：已有 `get_langfuse_handler` 追 LLM trace；应用级异常也上报 Langfuse event。
5. `main.py:14` 的 `basicConfig` 替换为 `logging_config.configure_logging()`。

---

## G. 全局异常处理 + 对外脱敏

`main.py`：

1. 现有 `@app.exception_handler(Exception)`（line 27）：不再返回 `str(exc)`，改为 `{code:'INTERNAL_ERROR', message:'服务内部错误，请稍后重试'}`，detail 只进日志。
2. 新增 `RequestValidationError` handler：返回 422 标准 `{code:'VALIDATION_ERROR', errors:[...]}`。
3. 新增 `AgentError` 专属 handler：按 `to_http_response()` 返回对应状态码与错误码。
4. 注意：全局 handler **只对普通 HTTP 请求生效**；SSE 流式中途异常已在 generator 内处理（见 C），不走全局 handler。

---

## H. 状态一致性（已补充 state-driven errors + saga）

1. **state 加 `errors` 列表**（来源：machinelearningplus、focused.io 的 LangGraph 生产范式）：`ResearchState` / `State` 增加 `errors: Annotated[list, operator.add]`，节点失败时 append，下游节点检查后再决定是否继续。让错误在图内可被感知与路由，而非只靠外层 try/except。
2. **`error_handler` saga 补偿**：见 B.3，重试耗尽走补偿节点而非整图失败。
3. **LLM 失败时会话状态**：以 checkpointer 为准——失败时不强行写半成品 AI 消息，标记 `conversation` 需"补偿同步"，由后台任务从 `app.aget_state(config)` 重建 DB 落库；幂等（按 message 已存在跳过）。
4. **`save_data_to_db` 失败补偿**：落库失败入队补偿任务（`asyncio.create_task` + 引用持有），从 checkpointer 取最终状态重放落库。
5. **`evaluate_trace_task.kiq` 幂等**：带 `trace_id` 幂等键，重复入队不重复评测。
6. **`recursion_limit` 显式设置**：`graph.py` / `research_graph.py` compile 时或 invoke 时设 `recursion_limit`（主图建议 200、研究图按 20 工具循环设 50），并在外层捕获 `GraphRecursionError`。

---

## I. 工具层错误规范（已补充 RetryPolicy + 自定义 formatter）

1. 原则：工具内部异常优先转成"错误字符串返回"（让 LLM 决策），仅不可恢复才抛。
2. `ToolNode` 配置 `handle_tool_errors=True`（来源：focused.io、machinelearningplus）。**进阶**：传自定义 `format_tool_error` 函数，给 LLM 更可操作的纠错提示：
   ```python
   def format_tool_error(e: Exception) -> str:
       return f"工具失败: {e}\n请检查参数后重试，参考工具 docstring。"
   tool_node = ToolNode(tools, handle_tool_errors=format_tool_error)
   ```
3. **tools 节点也加 `RetryPolicy`**（来源：focused.io "Put RetryPolicy on every node that touches a network"）：`search_web`/`fetch_url` 这类网络工具的节点级重试，`retry_on=(httpx.TimeoutException, httpx.NetworkError)`。
4. `search_web`（`tools.py:88`）：`except Exception` catch-all 改精细分类（对齐 `fetch_url`）。
5. `calculator` 除零/非法 op 校验保留。

---

## J. 熔断与降级链（v1"暂不做"→ v2 纳入，因选了全套工业级）

来源：anthropic-sdk-python discussion #1341（大厂生产 tiered 模式）+ medium 7-retry-rules。

### J.1 三层降级（大厂范式）

| Tier | 触发 | 动作 |
|---|---|---|
| Tier 1 重试 | 瞬时错误 | 指数退避 + jitter，max 3 次 |
| Tier 2 fallback | 重试耗尽 / 模型不可用 | 模型 fallback（pro→flash，`.with_fallbacks`）；工具 fallback（search_web 失败→fetch_url） |
| Tier 3 熔断 | 错误率 >30% / 连续失败 N 次 | 熔断器 open，停一段时间，告警，切手动/降级回复 |

### J.2 轻量熔断器（自研，不引 pybreaker）

`resilience.py` 内实现一个进程内熔断器（closed/open/half-open）：
- `closed`：正常调用，连续失败计数；达阈值（如 5 次）→ `open`。
- `open`：直接快速失败（抛 `LLMServiceUnavailable`），持续冷却期（如 30s）→ `half-open`。
- `half-open`：放一个试探请求，成功→`closed`，失败→`open`。
- 仅对 DeepSeek、Tavily 这类外部依赖启用；DB/Redis 暂不熔断（靠连接池重连）。

> 权衡：个人项目流量小，熔断主要防"重试风暴放大 429"（DeepSeek 429 会因重试并发飙升而恶化）。轻量自研足够，不必引 pybreaker。

---

## 改造文件清单

**新建：**
- `backend/src/exceptions.py` — 分层异常体系 + 错误码
- `backend/src/resilience.py` — DeepSeek 异常映射 + 上下文裁剪 + 轻量熔断（**不再含重试主逻辑**，重试交 RetryPolicy）
- `backend/src/logging_config.py` — structlog 配置
- `backend/src/middleware.py` — correlation id 中间件

**修改：**
- `backend/src/graph.py` — `ChatOpenAI(timeout/max_retries)` + `RetryPolicy` + `error_handler` + `recursion_limit` + state 加 `errors`
- `backend/src/file_research/research_graph.py` — 同上 + writer `.with_fallbacks` + writer `error_handler` 降级
- `backend/src/service/agent.py` — SSE 错误帧重构、`save_data_to_db` 剥离、resume shield、`GraphRecursionError` 捕获、补偿入队
- `backend/src/service/file_research.py` — gather 容错、文件失败通知、create_task 引用
- `backend/src/tools.py` — `search_web` 精细分类、`spawn_deep_research` task 引用、`ToolNode(handle_tool_errors=format_tool_error)`
- `backend/src/main.py` — structlog 初始化、全局 handler 脱敏、validation handler、中间件注册
- `backend/src/config.py` — 超时/重试/熔断参数可配置
- `backend/pyproject.toml` — 加 `tenacity`、`structlog`

---

## 验证方式

1. **重试单测**：mock `openai.RateLimitError`，验证 `RetryPolicy` 重试 3 次后退避成功；mock 402 余额验证立即失败不重试 + 告警。
2. **上下文超限**：构造超长 messages，验证裁剪后重试一次成功，标记降级。
3. **writer 降级**：mock writer 持续失败，验证 `error_handler` 返回 raw 情报 + `degraded=True`，任务不 failed。
4. **模型 fallback**：mock pro 抛 429，验证自动切 flash。
5. **熔断**：mock DeepSeek 连续失败 5 次，验证熔断 open、后续请求快速失败、冷却后半开试探。
6. **SSE 中断**：`astream` 中途 mock 抛错，验证前端收到 `partial:true` error 帧且会话状态可恢复。
7. **`GraphRecursionError`**：构造超长工具循环，验证捕获并返回友好错误而非裸崩溃。
8. **后台任务**：mock embedding 部分失败，验证 `return_exceptions` 容错；杀进程验证 task 状态与前端通知。
9. **日志**：发一条 chat 请求，grep `request_id` 验证 correlation id 贯穿所有日志行。
10. **脱敏**：触发 500，验证前端只收到 `code + 通用 message`，不含栈/SQL。
11. **手动 e2e**：`uv run uvicorn main:app`，前端发起对话/深度研究/文件上传，断网测恢复路径。

---

## 实施顺序建议（供参考，由 yc 本人执行）

1. **F（structlog + correlation id）+ A（异常体系）**：基础设施，后续都依赖。
2. **B（LLM 鲁棒性）**：收益最大。先接 `RetryPolicy` + DeepSeek 错误映射，再加 `.with_fallbacks` 与 `error_handler`。
3. **C（SSE 边界）+ H（状态一致性）**：一起改 `service/agent.py`，含 `GraphRecursionError` 与 `recursion_limit`。
4. **E（超时）+ I（工具规范）+ J（熔断）**。
5. **G（全局脱敏）** 收口。
6. 每步做完跑对应验证项，不要堆到最后一起测。

---

## 修订记录（v2，2026-07-15，联网调研后）

相对 v1 的主要修订：
1. **引入 LangGraph 官方 `RetryPolicy`** 作为节点级重试主机制，取代 v1 手写的 `safe_llm_invoke` 重试逻辑；`resilience.py` 降级为薄封装（映射/裁剪/熔断）。来源：[RetryPolicy 参考](https://reference.langchain.com/python/langgraph/types/RetryPolicy)、[Thinking in LangGraph](https://docs.langchain.com/oss/python/langgraph/thinking-in-langgraph)。
2. **纠正"max_retries=0"**：改为 HTTP 层 `max_retries` 与节点层 `RetryPolicy` 分层配合、不重叠重试。来源：[machinelearningplus](https://machinelearningplus.com/gen-ai/langgraph-error-handling-retries-fallback-strategies)。
3. **新增错误四分类**（Transient / LLM-recoverable / User-fixable / Unexpected）。来源：[Thinking in LangGraph](https://docs.langchain.com/oss/python/langgraph/thinking-in-langgraph)。
4. **新增 `error_handler` saga 补偿** + writer 降级。来源：同上（NodeError / error_handler）。
5. **新增模型 fallback** `.with_fallbacks`。来源：[agnxi langchain-rate-limits](https://agnxi.com/jeremylongshore/skills/langchain-rate-limits)。
6. **DeepSeek 错误码澄清**：402 余额（不重试）、429 限流（重试）、500/503（重试）、400 上下文超限（裁剪）；`Retry-After` 第三方实测会带、官方未文档化。来源：[DeepSeek 官方 error_codes](https://api-docs.deepseek.com/quick_start/error_codes)、[deepseek-usa](https://deepseek-usa.ai/docs/deepseek-api-rate-limits)、[chat-deep.ai](https://chat-deep.ai/docs/api-rate-limits)。
7. **新增三层降级 + 轻量熔断**（v1 的"暂不做"改为纳入）。来源：[anthropic-sdk-python discussion #1341](https://github.com/anthropics/anthropic-sdk-python/discussions/1341)、[7 retry+timeout rules](https://medium.com/@Praxen/7-retry-timeout-rules-for-langchain-tools-760d1a4dd69d)。
8. **新增 deadline 预算模型**（不只 per-attempt timeout）。来源：同上。
9. **新增 state-driven `errors` 列表**。来源：[machinelearningplus](https://machinelearningplus.com/gen-ai/langgraph-error-handling-retries-fallback-strategies)、[focused.io](https://focused.io/lab/langgraph-agent-error-handling-production)。
10. **新增 `GraphRecursionError` 处理 + `recursion_limit` 显式设置**（发现项目潜在 bug）。
11. **新增幂等性原则**（`spawn_deep_research` 非幂等不盲目重试）。
12. **ToolNode 自定义 `format_tool_error`** + tools 节点加 `RetryPolicy`。来源：[focused.io](https://focused.io/lab/langgraph-agent-error-handling-production)。

### 参考的大厂 / 生产实践
- **OpenAI Agents SDK**：`AgentsError` 异常基类、input/output guardrails、`GuardrailExecutionError` 用 saved state 重试不重调模型。来源：[OpenAI Agents SDK – Running Agents](https://openai.github.io/openai-agents-js/guides/running-agents)。
- **Anthropic 生产讨论**：三层（重试→fallback→熔断）、幂等/非幂等分配置、工具失败回滚 hook、checkpoint 每 N 条消息。来源：[anthropic-sdk-python #1341](https://github.com/anthropics/anthropic-sdk-python/discussions/1341)。
- **LangGraph 生产清单**：每个触网节点加 `RetryPolicy`、`ToolNode(handle_tool_errors=True)`、校验失败用 `interrupt()`、上线前跑 `recovery_efficiency` eval。来源：[focused.io](https://focused.io/lab/langgraph-agent-error-handling-production)。

### 仍需项目实测确认
- DeepSeek 429 响应是否稳定带 `Retry-After`（记录一段时间响应头）。
- `RetryPolicy` / `error_handler` 在本机 LangGraph 1.2.4 的精确参数名（以本机安装版本源码为准；v0.2+ 文档与 1.2.4 可能有差异）。
- 补偿同步任务是否复用 taskiq 队列（确认 `service/task_queue.py` 结构后决定）。
