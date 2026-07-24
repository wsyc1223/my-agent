# 开发任务清单（6 周 · 每天 6h · v2）

> v2 变更：吸收对标简历（论匠）的优秀方向——多 Agent Supervisor、四层记忆、三阶段递进 RAG（Query 改写）、上下文压缩（Context Engineering）、量化 AB 对比、审计日志/RBAC——作为后续主要方向。原错误处理 v2 与范围 A 必补项保留。
> 错误处理部分对照 `error-handling-design.md`。每天留约 1h 给踩坑/回顾。
> 验收口径：写完 + 跑通 + 能在面试讲清原理，三者缺一不算完成。

---

## 第 1 周 ｜ 错误处理 v2 上半场：基础设施 + LLM 鲁棒性

- [ ] **A. 分层异常体系** `src/exceptions.py`
  - `AgentError` 基类 + `LLMError`/`ToolError`/`InfraError`/`BusinessError` 及子类（402 余额、429 限流、上下文超限等）
  - `code`/`recoverable` 类属性；`to_sse_frame()`/`to_http_response()`
  - 验收：单测字段正确、`detail` 不外泄、`recoverable` 取值对

- [ ] **F1. structlog 配置** `src/logging_config.py`（开发 console / 生产 JSON，统一字段含 request_id/conversation_id/trace_id/node）
- [ ] **F2. correlation id 中间件** `src/middleware.py`（request_id/conversation_id 注入 contextvars）
- [ ] **F3. 替换 `traceback.print_exc()` → `logger.exception`；`main.py` basicConfig → configure_logging**
- [ ] **B1. DeepSeek 异常映射** `src/resilience.py`（402→Balance、429→RateLimit、500/503→Server、400 上下文超限→ContextOverflow、401→Auth）
- [ ] **B2. LLM 超时 + HTTP 重试**：`ChatOpenAI(timeout=60, max_retries=2)`（graph.py / research_graph.py）
- [ ] **B3. 节点级 RetryPolicy**：agent/researcher/writer 节点 `retry=RetryPolicy(max_attempts=3, retry_on=(...))`
  - ⚠️ 以本机 LangGraph 1.2.4 源码确认参数名
  - 验收：mock 429 重试 3 次成功；mock 402 立即失败；日志按 request_id 串联

---

## 第 2 周 ｜ 错误处理 v2 下半场 + 工程治理（对标：三级容错/限流/审计）

- [ ] **B4. 上下文超限裁剪 + 单次重试** `src/resilience.py`
- [ ] **B5. 模型 fallback**：writer `.with_fallbacks([flash])`（对标：默认参数降级）
- [ ] **B6. writer saga 补偿降级**：`error_handler` 重试耗尽→返回 raw 情报 + `degraded=True`
- [ ] **J. 轻量熔断器** closed/open/half-open（对标：三态熔断器；单实例用进程内即可，不上 Redis Lua）
- [ ] **E. 三层超时 + config 参数化**（LLM_TIMEOUT / RESEARCH_TASK_TIMEOUT / TOOL_DEADLINE）
- [ ] **限流**：slowapi 给关键 API 加 rate limit（对标：Redis 滑动窗口限流；单实例 slowapi 够）
- [ ] **审计日志**：记录每次工具调用/Agent 决策/工具确认入 DB（对标：全量审计日志；搭 structlog 几乎免费）✨新增
- [ ] **C1. SSE 统一错误帧** `{type,code,message,recoverable,partial}`
- [ ] **C2. save_data_to_db 剥离主 except + 补偿入队**
- [ ] **C3. resume 路径补 `asyncio.shield`**
- [ ] **H1. state 加 `errors` 列表**；**H2. GraphRecursionError 捕获 + 显式 recursion_limit**
- [ ] **G. 全局 handler 脱敏**（Exception handler 不返回 str(e) + RequestValidationError + AgentError handler）
- [ ] **I. 工具规范**：`ToolNode(handle_tool_errors=format_tool_error)` + tools 节点 RetryPolicy + search_web 精细分类
- [ ] **D. 后台任务加固**：create_task 持引用+done_callback；gather return_exceptions；文件失败通知前端
  - 验收：熔断 open 快速失败；SSE 中断 partial 帧；500 脱敏；审计日志可查

---

## 第 3 周 ｜ RAG 与记忆进阶（对标：三阶段递进 RAG / 四层记忆 / 上下文压缩）

- [ ] **评测基线**：用 ragas 跑当前 RAG 的 faithfulness/answer_relevancy + 自建 Recall@5 评测集，记录"改造前"基线数据 ✨新增
- [ ] **Query 改写**（对标：三阶段递进检索第一阶段）：LLM 把用户问题改写成多个子查询（多查询 / HyDE），合并检索结果再 rerank
  - 验收：多轮/指代类问题的召升
- [ ] **上下文压缩 / Context Engineering**（对标：四级压缩至 30%）：用 `trim_messages` 窗口截断 + 冗余去重 + LLM 摘要长对话
  - 验收：10+ 轮对话状态 token 量化压缩比（目标 ≤50%，简历可写真实数）
- [ ] **四层记忆**（对标：短期对话/项目结构化/长期向量召回/用户偏好）：在现有长期向量召回基础上，加"项目结构化记忆"（研究任务结果结构化存）+ "用户偏好"
  - 验收：跨会话能召回项目级结构化信息
- [ ] **RAG AB 对比评测**：对比 有/无 Query 改写、有/无 rerank 的 Recall@5（对标：AB 测试对比 3 组检索策略）
  - 验收：产出 AB 数据表，可填简历

---

## 第 4 周 ｜ 多 Agent 协作架构（对标：多 Agent 主从架构 / 流式时序治理 / RBAC）

- [ ] **Supervisor 多 Agent 重构**（对标：主控 Agent 调度专项 Agent）：把深度研究从 fire-and-forget 重构为 Supervisor + 手下 agent（如 检索 Agent / 撰写 Agent）的小型 handoff 架构
  - ⚠️ Anthropic 警告别过早引入多 Agent——做小而真，不为凑数造 6 个
  - 验收：Supervisor 能按任务分派给子 Agent 并汇总
- [ ] **意图分类路由**（对标：三层轻量意图分类器）：在 Supervisor 前加一个轻量意图分类（可用小模型/规则），降成本提速
  - 验收：意图分类正确率量化
- [ ] **流式时序治理**（对标：asyncio.Queue 解决 token 流与节点事件时序错乱）：若你的 SSE 出现过字符/事件乱序，用 asyncio.Queue 缓冲统一推送
  - ⚠️ 只在真有该问题时做，别硬造
- [ ] **RBAC 权限**（对标：YAML 驱动 RBAC）：在 JWT 基础上加角色-权限矩阵
  - 验收：不同角色工具/接口权限不同
- [ ] **分布式锁（可选）**：仅当部署多实例时做 Redis 锁保障任务互斥（对标：分布式锁）；单实例跳过

---

## 第 5 周 ｜ 协议化与部署（范围 A 必补）

- [ ] **MCP Server 改造**（独立攻坚 3–5 天）：把 search_web/fetch_url/文件检索封装为 MCP Server，Agent 经 MCP client 调用
  - ⚠️ 最大不确定项，卡住就先只封装 1 个工具跑通
  - 验收：Agent 经 MCP 调用工具；面试能讲 MCP vs Function Call vs A2A
- [ ] **结构化输出**：writer 用 `with_structured_output`（报告 schema）
- [ ] **Dockerfile**（后端）+ **docker-compose.yml**（PG+pgvector+Redis+后端+前端）
  - 验收：`docker-compose up` 一键起全栈
- [ ] **README + 架构图**：项目介绍/架构图/技术栈/RAG 与 Agent 流程图/启动方式/评测结果
  - 验收：陌生人能照 README 跑起来

---

## 第 6 周 ｜ 可观测 / 安全 / 量化收尾

- [ ] **成本/Token 监控**：聚合 Langfuse token usage，按会话/模型统计成本
- [ ] **输出 guardrails**：prompt injection 检测 + PII 过滤 + 输出安全过滤（与输入侧 SSRF 对称）
- [ ] **CI/CD**：GitHub Actions 跑 `backend/tests` + ragas 评测作回归门禁
- [ ] **量化指标终评**：跑全量评测，产出 Recall@5 / faithfulness / answer_relevancy / 压缩比 / 耗时对比 真实数据
- [ ] **更新简历**：去掉所有"进行中"标注；用真实评测 + AB 数据替换 `[待填]`；对标论匠密度，但只写你能演示的
  - 验收：每条 bullet 都能演示 + 讲清原理；CI 绿

---

## 优先级与取舍

- **不可砍**（简历核心卖点）：错误处理 v2（第 1–2 周）、多 Agent Supervisor + RAG 进阶 + 量化 AB（第 3–4 周）、Docker+README、MCP。
- **可砍**（时间不够优先砍，边际贡献最小）：CI/CD、输出 guardrails、结构化输出、分布式锁、流式时序治理（若无该问题）。
- **量化是贯穿动作**：第 3 周建基线 → 第 3 周末 AB 对比 → 第 6 周终评。没有真实数字的 bullet 不要写。
- **别抄话术**：对方"三级降级存储""三层轻量意图分类器"等措辞不要照搬；做了对应的事就用你能讲清的朴素语言写。
- **每周末整体回归**：对话/深度研究/文件上传/断网恢复，别堆到最后测。

## 现实提醒

- 范围已从 4 周扩到 6 周（每天 6h）。若某周明显超时，优先保"错误处理 + 多 Agent + RAG 进阶 + 量化 + Docker/README"，砍第 6 周的 guardrails/CI。
- 第 4 周多 Agent 重构有把现有稳定架构改乱的风险——先在分支上做，跑通再合并。
