## 一、本周做了什么（总览）

围绕"让 Agent 在外部服务抖动、流量异常、长任务中断下仍能优雅降级与恢复"这一目标，完成了错误处理体系的**基础设施层 + LLM 鲁棒性层**，共 7 个子任务，全部通过本机验证。

| 编号 | 任务 | 产出文件 | 验证方式 | 状态 |
|---|---|---|---|---|
| A | 分层异常体系 | `backend/src/exceptions.py`（新建） | 字段/继承单测 | ✓ |
| F1 | structlog 配置 | `backend/src/logging_config.py`（新建） | 内联脚本输出结构化日志 | ✓ |
| F2 | correlation id 中间件 | `backend/src/middleware.py`（新建） | 端到端：日志同时带 request_id + conversation_id | ✓ |
| F3 | print_exc → logger.exception | `eval_service/task.py`、`service/file_research.py`（改） | 残留扫描 + 导入验证 | ✓ |
| B1 | DeepSeek 异常映射 | `backend/src/resilience.py`（新建） | 11 个 case 单测全过 | ✓ |
| B2 | LLM 超时 + HTTP 重试 | `config.py`、`graph.py`、`research_graph.py`（改） | 导入验证 | ✓ |
| B3 | 节点级 RetryPolicy | `resilience.py`、`graph.py`、`research_graph.py`（改） | mock 429/402/500 三 case 全过 | ✓ |

---

## 二、设计原则（贯穿本周）

1. **可重试 vs 不可重试显式区分**：瞬时错误（429/5xx/timeout）退避重试，确定性错误（上下文超限/鉴权失败/余额不足）不重试、走降级。体现在异常类的 `recoverable` 字段与 `retry_on` 的精确过滤。
2. **分层重试、各司其职、不重叠**：HTTP 层（openai SDK `max_retries`）挡瞬时抖动 → 异常映射成类型化自定义异常 → 节点层（LangGraph `RetryPolicy`）按 `recoverable` 精确重试。两层重试的不是"同一次调用"。
3. **对外脱敏、对内可观测**：客户端只收错误码 + 通用中文（`message`）；原始异常进 `detail` + 结构化日志 + Langfuse，绝不进 SSE 帧。
4. **可验证优先**：每个子任务都有本机验证证据（单测、内联脚本、端到端日志），不靠"看起来对"。

---

## 三、各项详解

### A. 分层异常体系 `src/exceptions.py`

**做了什么**：建立 `AgentError` 基类 + 四大类子类（LLM/Tool/Infra/Business），LLM 类下再按 HTTP 语义细分。

```
AgentError(Exception)                    # code / recoverable / message / detail
├── LLMError                             # code = LLM_ERROR
│   ├── LLMRateLimitError        (429, recoverable=True)
│   ├── LLMTimeoutError          (recoverable=True)
│   ├── LLMServerError           (5xx, recoverable=True)
│   ├── LLMContextOverflowError  (400 上下文超限, recoverable=False)
│   ├── LLMBalanceError          (402 余额, recoverable=False)
│   └── LLMAuthError             (401 鉴权, recoverable=False)
├── ToolError
├── InfraError
└── BusinessError
```

**关键设计**：
- `code: str` 机器可读错误码（如 `LLM_RATE_LIMIT`），`message: str` 用户安全中文，`recoverable: bool` 控制前端是否提示重试，`detail: str` 原始异常只进日志。
- `to_sse_frame(*, partial)` 统一对外格式 `{type, code, message, recoverable, partial}`，避免散落各处手拼。
- `recoverable` 字段是 B3 `retry_on` 精确过滤的依据——不可重试的（Balance/Auth/ContextOverflow）立即失败。

**踩过的坑（已修复）**：
- `to_see_frame` 拼写 → `to_sse_frame`
- 缺 `super().__init__(message)` 导致 `str(e)` 为空
- `code = "LLM_Error"` 大小写不一致 → `LLM_ERROR`

---

### F1. structlog 配置 `src/logging_config.py`

**做了什么**：配置 structlog 并与标准库 logging 打通，使第三方库（langchain/openai/uvicorn）日志也经过同一套处理器、带上 correlation id。

**关键设计**：
- `shared_processors` 共用处理器链：`merge_contextvars`（合入 contextvars 里的 request_id/conversation_id）→ `add_log_level` → `add_logger_name` → `TimeStamper(iso)` → `StackInfoRenderer` → `format_exc_info`。
- `foreign_pre_chain=shared_processors`：让第三方库的 stdlib 日志也走这套链——这是"请求级链路追踪能贯穿第三方库"的关键。
- `json_logs` 开关：开发态 `ConsoleRenderer`（彩色可读），生产态 `JSONRenderer`。
- `main.py` 的 `logging.basicConfig` 替换为 `configure_logging()`，二选一避免重复 handler。

**验证证据**：
```
$ uv run python -c "...configure_logging(); structlog.get_logger().info('hello_structlog', who='yc')"
2026-07-16T07:16:29.460807Z [info     ] hello_structlog                [__main__] who=yc
```

**踩过的坑（已修复）**：5 处拼写——`strctlog`/`structlgo`/`json_logs`（参数名 `json_log`）/`StreamingHandler`（应为 `StreamHandler`）。

---

### F2. correlation id 中间件 `src/middleware.py`

**做了什么**：FastAPI 中间件，每个请求生成 `request_id` 写入 `structlog.contextvars`，使该请求生命周期内所有日志自动带 `request_id`；`conversation_id` 在业务函数（`chat_stream`/`resume`）入口补绑。

**方案选型（重要决策）**：
- 评估了"中间件读 body 抓 conversation_id"（方案 b）vs"中间件只管 request_id、conversation_id 下沉业务函数"（方案 a）。
- 方案 b 有 Starlette `BaseHTTPMiddleware` 读 body 的经典坑（body 流被消费后下游路由拿空 body / 卡住 / 422），且文件上传 multipart 场景 `json.loads` 会异常。
- **最终选方案 a**：`request_id` 是每请求通用字段放中间件；`conversation_id` 是业务字段下沉 `chat_stream`/`resume` 用 `bind_contextvars` 补绑（用 `bind` 不 `clear`，避免冲掉 request_id）。职责清晰，不碰 body 雷区。

**contextvars 传播链**（已验证）：中间件 `bind_contextvars(request_id)` → `BaseHTTPMiddleware` 子任务拷贝 contextvars → `StreamingResponse` generator 继承 → 整条 SSE 链路日志都带 id。

**验证证据**（端到端）：
```
2026-07-16T08:52:56.435383Z [info] conversation_resolved [src.service.agent]
  conversation_id=cecfad87-9e38-4a62-b3f6-eed6116a5afa
  request_id=51d71e66-a850-42a7-a27b-3799ddf705fd
```
一条日志同时带两个 id，证明从中间件 → SSE generator 全程串通。

**踩过的坑（已修复）**：`reponse`/`retrun` 拼写。

---

### F3. print_exc → logger.exception

**做了什么**：全项目把 `traceback.print_exc()` 换成 `logger.exception(...)`，把 `print()` 当日志用的地方换成结构化 `logger.xxx(event, **kv)`。

**改动点**：
- `service/file_research.py:136` `traceback.print_exc()` → `logger.exception("file_index_failed", document_id=document_id)`
- `eval_service/task.py:74-76` `print + traceback.print_exc()` → `logger.exception("ragas_eval_failed", trace_id=trace_id)`
- `eval_service/task.py` 5 处 `print()` → `logger.info/warning/error` 结构化日志
- 两个文件补 `import logging` + `logger = logging.getLogger(__name__)`，删除内联 `import traceback`

**关键点**：`logger.exception()` 等价 `logger.error(..., exc_info=True)`，必须在 except 块内调用，自动带栈并经 structlog `format_exc_info` 渲染，且自动带 contextvars 的 request_id/conversation_id。

**验证证据**：`rg "traceback"` 两文件为空；`rg "^\s*print\("` 为空；导入通过。

**踩过的坑（已修复）**：`attempt+1` 漏写 key（应为 `attempt=attempt+1`）。

---

### B1. DeepSeek 异常映射 `src/resilience.py`

**做了什么**：`map_openai_error(exc)` 纯函数，把 openai SDK 异常映射到 A 阶段自定义异常。重试逻辑不在此层（重试在 B2/B3）。

**前置本机调研（关键）**：本机 `openai==2.31.0`，异常类层次确认。三个影响映射代码的事实：
1. **402 余额无专属异常类**——openai 只为 401/400/404/409/422/429/5xx 提供专属类，402 以通用 `APIStatusError` 抛出，只能靠 `exc.status_code == 402` 判断。
2. **继承关系决定匹配顺序**：`APITimeoutError ← APIConnectionError ← APIError`（超时必须先判）；专属状态类 `← APIStatusError`（专属必须先判）。顺序错则子类被父类分支接走。
3. **上下文超限（400）无专属类**，靠错误消息关键词（`context length`/`context_window` 等）判断——非 100% 可靠，已知不确定性，B4 依赖此映射，需实测 DeepSeek 实际文案补关键词。

**映射顺序**：超时 → 鉴权(401) → 限流(429) → 400(含上下文超限) → 5xx(专属) → 网络连接 → 通用 APIStatusError(402/5xx 兜底) → 兜底 LLMError。

**验证证据**（11 个 case 全过）：
```
402 余额         LLMBalanceError            ✓
429 限流         LLMRateLimitError          ✓
401 鉴权         LLMAuthError               ✓
400 上下文超限   LLMContextOverflowError    ✓
400 普通参数     LLMError                   ✓
500 服务端       LLMServerError             ✓
503 服务端       LLMServerError             ✓
超时             LLMTimeoutError            ✓
网络连接         LLMServerError             ✓
asyncio 超时     LLMTimeoutError            ✓
兜底             LLMError                   ✓
```

**踩过的坑（已修复）**：import 拼写 `LLMBalanceeError`/`LLLMAuthError`；`detailj=` 拼写；第 5 步 message 误写"网络连接失败"（应为"服务端错误"）。

---

### B2. LLM 超时 + HTTP 重试

**做了什么**：两处 `ChatOpenAI` 实例化加 `timeout` + `max_retries`，参数进 `config.py` 可环境变量覆盖。

**改动点**：
- `config.py` 加 `LLM_TIMEOUT: float = 60.0`、`LLM_MAX_ATTEMPTS: int = 2`
- `graph.py:25`（deepseek-v4-flash）、`research_graph.py:48`（deepseek-v4-pro）两处 `ChatOpenAI` 加 `timeout=settings.LLM_TIMEOUT, max_retries=settings.LLM_MAX_ATTEMPTS`

**关键设计**：
- `timeout=60`：openai SDK 默认超时 600s，DeepSeek 卡住会拖死整个任务，60s 是单次 HTTP 调用硬上限。
- `max_retries=2`：HTTP 层重试（含首次共 3 次），openai SDK 内置，**会解析响应头 `Retry-After`** 按服务端要求等——比自己写重试强。
- v1 设计曾想 `max_retries=0` 全交 tenacity，v2 纠正：SDK 内置 HTTP 重试质量高（Retry-After 解析、连接池复用），自造不划算，保留 `max_retries=2` 挡瞬时抖动。
- 参数进 config：超时/重试是运维高频调参项，改 `.env` 即可，不必改代码重发布。

**踩过的坑（已修复）**：两处 `ChatOpenAI` 漏加参数（一处改了另一处漏），用 `rg "timeout=|max_retries="` 自检抓出。

---

### B3. 节点级 RetryPolicy（核心）

**做了什么**：三个 LLM 节点（agent/researcher/writer）加节点级重试，`retry_on` 精确过滤可重试异常。

**前置本机调研（关键，checklist 标注"以本机源码确认参数名"）**：本机 `langgraph==1.2.4`，从源码确认 API 与设计文档假设有出入：

| 设计文档假设 | langgraph 1.2.4 实际 |
|---|---|
| `add_node(retry=RetryPolicy(...))` | **`add_node(retry_policy=RetryPolicy(...))`** |
| `RetryPolicy` 在 `langgraph.pregel` | **在 `langgraph.types`** |
| — | NamedTuple，字段 `initial_interval=0.5 / backoff_factor=2.0 / max_interval=128 / max_attempts=3 / jitter=True / retry_on=default_retry_on` |
| — | `retry_on` 接受异常类元组或 `Callable[[Exception], bool]`；`max_attempts` 含首次 |

> 若照设计文档的 `retry=` 写，`add_node` 会走 `**kwargs` 静默忽略——不报错但不生效，最坑的 bug 类型。所以参数名必须以源码为准。

**改动点**：
- `resilience.py` 加 `safe_ainvoke(llm, *args, **kwargs)`：薄包装，调 `llm.ainvoke`，捕获 `openai.OpenAIError`/`asyncio.TimeoutError` → `map_openai_error` → 抛自定义异常。**只做映射、不做重试**（重试交 RetryPolicy）。这不是 v1 那个带 tenacity 的 safe_llm_invoke（v2 已弃）。
- `resilience.py` 加共享 `LLM_RETRY_POLICY = RetryPolicy(max_attempts=3, retry_on=(LLMRateLimitError, LLMTimeoutError, LLMServerError))`。
- 三节点 LLM 调用改用 `safe_ainvoke`，`add_node` 加 `retry_policy=LLM_RETRY_POLICY`。

**`retry_on` 只列三个的原因**：它们 `recoverable=True`。Balance/Auth/ContextOverflow 是确定性错误（余额不会因多重试变多），不列 = 不重试 = 快速失败走降级。这正是 A 阶段 `recoverable` 字段发挥作用处。

**分层重试完整链路**：
```
agent_node → safe_ainvoke(llm)
  → llm.ainvoke: openai SDK HTTP 层重试 (max_retries=2, 含 Retry-After)   ← B2 第 1 层
    → 仍失败，抛 openai.RateLimitError
  → safe_ainvoke 捕获 → map_openai_error → 抛 LLMRateLimitError           ← B1 映射
  → RetryPolicy 看到 LLMRateLimitError，retry_on 命中 → 重试整个节点       ← B3 第 2 层
    → 节点重试又走一遍 safe_ainvoke → 又一轮 HTTP 重试
  → max_attempts=3 耗尽 → 异常逃逸出图 → SSE error 帧
```

**乘法效应**：最坏 `3 节点尝试 × 3 HTTP 尝试 = 9 次 LLM 调用`。节点层间有指数退避（initial_interval=0.5, backoff_factor=2.0），非紧密 hammer，对持续限流是额外韧性。个人项目可接受；若担心可调 `max_attempts=2`。

**验证证据**（mock 三 case 全过）：
```
429 重试成功   success=True  calls=3   ✓   （两次限流后第三次成功）
402 立即失败   success=False calls=1   ✓   （抛 LLMBalanceError，不重试）
500 重试成功   success=True  calls=2   ✓   （一次 5xx 后第二次成功）
```
精确命中 checklist 验收：可重试的退避重试、确定性错误立即失败、异常正确映射成自定义类型。

**踩过的坑（已修复）**：`retrun` 拼写；`RetryPolicy` 未 import（模块加载即 NameError）。

---

## 四、文件清单

**新建（4 个）**：
- `backend/src/exceptions.py` — 分层异常体系
- `backend/src/logging_config.py` — structlog 配置
- `backend/src/middleware.py` — correlation id 中间件
- `backend/src/resilience.py` — 异常映射 + safe_ainvoke + LLM_RETRY_POLICY

**修改（5 个）**：
- `backend/main.py` — configure_logging + 注册中间件
- `backend/src/config.py` — LLM_TIMEOUT / LLM_MAX_ATTEMPTS
- `backend/src/graph.py` — ChatOpenAI 参数 + agent_node safe_ainvoke + retry_policy
- `backend/src/file_research/research_graph.py` — 同上（researcher/writer 两节点）
- `backend/src/service/agent.py` — conversation_id 补绑
- `backend/src/eval_service/task.py`、`backend/src/service/file_research.py` — logger.exception 替换

**新增依赖**：`structlog`、`tenacity`（tenacity 暂未实际使用，见待办）

---

## 五、待办与已知不确定性

1. **简历技能区写"tenacity 重试"与实现不符**：实际用 LangGraph RetryPolicy。第 6 周更新简历时，要么改成"LangGraph RetryPolicy 节点级重试 + openai SDK HTTP 层重试"，要么真在工具层用上 tenacity。
2. **上下文超限关键词非 100% 可靠**：B1 靠错误消息关键词判断 400 上下文超限，需实测 DeepSeek 实际返回文案，补充 `_CONTEXT_OVERFLOW_MARKERS`。B4（上下文裁剪降级）依赖此映射。
3. **后台任务日志无 request_id**：`eval_service/task.py` 是 taskiq worker，不在 HTTP 请求内，日志无 request_id（正常）。若要关联需在任务入口 `bind_contextvars(trace_id=...)`，超出本周范围。
4. **`recursion_limit` 未显式设置**（设计阶段识别的潜在 bug）：图默认 recursion_limit=25，但 `should_continue` 允许 100/20 次工具调用循环，极端情况会 `GraphRecursionError`。留待第 2 周 H2 处理。

---

## 六、面试可讲点（一句话版）

> HTTP 层（openai SDK max_retries，含 Retry-After 解析）挡瞬时抖动 → openai 异常经 `map_openai_error` 映射成类型化自定义异常（402 无专属类按 status_code 补判、继承顺序决定匹配）→ 节点层（LangGraph RetryPolicy retry_on）按 `recoverable` 精确重试，确定性错误（余额/鉴权/上下文超限）立即失败走降级。两层各司其职、不重叠。日志用 structlog + contextvars 注入 request_id/conversation_id 贯穿中间件到 SSE generator，实现请求级链路追踪。

可深挖的追问点：
- 为什么不用 tenacity 全包？→ SDK 内置 HTTP 重试质量高（Retry-After），自造不划算；节点级用 RetryPolicy 更 idiomatic。
- 402 怎么识别？→ openai SDK 无 402 专属异常类，按 `APIStatusError.status_code` 补判。
- 9 次重试会不会打爆限流？→ 节点层间指数退避，非紧密 hammer；可调 max_attempts。
- 中间件读 body 有什么坑？→ BaseHTTPMiddleware body 流消费后下游拿空 body；故 request_id 放中间件、conversation_id 下沉业务函数。
- contextvars 怎么传进 SSE generator？→ BaseHTTPMiddleware 子任务拷贝 contextvars，generator 继承。

---

## 七、过程反思（写给自己）

本周反复出现同一类问题：**标识符手敲拼写错误**（`strctlog`/`reponse`/`retrun`/`LLMBalanceeError`/`detailj`/`json_logs`）。根因是手敲速度超过准确度，凭记忆多按/少按字母。改进措施：
- 用编辑器自动补全/LSP，不手敲全名。
- 装拼写检查（VS Code Code Spell Checker / JetBrains 自带）。
- 改完立刻跑导入验证（`uv run python -c "import ..."`）或 `rg` 自检，不靠肉眼。
- 跑一次 > 看十遍。

这套习惯比任何架构优化都更能提升后续 5 周的效率。
