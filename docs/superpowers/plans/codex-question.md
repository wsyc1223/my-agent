# question.md 面试题复核与项目建议

> 创建日期：2026-06-06
> 依据：当前仓库源码、`question.md`、旧 deep research 计划、当前依赖配置。

## 1. 总体判断

`question.md` 的表达能力不错，很多概念适合面试讲，比如 LangGraph、Human-in-the-loop、RAG、Context Window、SSRF、SSE。

但它最大的问题是：很多答案把“计划中准备做的能力”写成了“项目已经实现的能力”。如果你在面试中照着说，面试官一旦追问代码细节，很容易露馅。

当前项目真实已经实现的是：

- FastAPI + Vue 登录和聊天。
- LangGraph 单图聊天 Agent。
- 工具调用前的人工审批 interrupt。
- PostgreSQL checkpoint。
- 消息级 RAG：用户消息和 AI 回复 embedding 入库，用 pgvector + reranker 检索历史消息。
- Tavily 搜索和网页抓取工具。
- SSE 文本流式返回。

当前项目尚未实现的是：

- 深度研究独立模式。
- 文件上传和文件检索。
- ResearchTask / FileTask 类任务表。
- 提纲审批、来源审批。
- SSRF 防护。
- 当前会话 RAG 排除。
- 异步 embedding 线程池卸载。
- 多工具拒绝时的 ToolMessage 数量对齐。
- 报告下载。
- 完整测试体系。

所以 `question.md` 不是不能用，而是要改成“当前实现 + 我识别出的改进点 + 正在做的文件检索 Agent”。

## 2. 逐题复核

### 题 1：这个 Agent 的整体流程是什么？

原答案问题：

- 它描述的是旧 deep research 计划中的 `planner -> researcher -> writer`，不是当前已实现项目。
- 当前项目的真实图是 `agent -> tools -> agent`，并在 `tools` 前 interrupt。
- “提纲审批”和“来源审批”当前不存在。

更稳的回答：

> 当前已实现的是一个带工具审批的聊天 Agent。用户消息进入 FastAPI SSE 接口后，后端先创建或获取 conversation，将用户消息写入数据库并生成 embedding，然后用历史消息 RAG 增强 prompt。LangGraph 的 `agent` 节点调用 DeepSeek 模型，如果模型产生 tool_calls，图会在 `tools` 节点前中断，前端显示审批卡片。用户批准后，后端用 `Command(resume="continue")` 恢复图执行；拒绝则注入 ToolMessage。最终 AI 回复通过 SSE 返回，并写入数据库。

如果讲“文件检索 Agent”，应该说：

> 我下一阶段做的是独立文件检索报告模式：上传文件后切块入库，用户输入检索目标，系统从当前用户文件 chunk 中召回和重排相关片段，再由 LLM 生成带来源引用的 Markdown 报告，并支持下载。

### 题 2：如何设计 tool calling？

原答案优点：

- 讲到了 schema、异常兜底、危险工具防护。

原答案问题：

- 当前 `fetch_url` 没有 SSRF 防护。
- 当前 `search_web` 返回文本摘要，没有返回 URL，不适合后续网页深度阅读。
- 当前拒绝多工具调用只处理了第一个 tool_call。

更稳的回答：

> 我现在的工具是通过 LangChain `@tool` 包装的函数，LangGraph 使用 `ToolNode(tools)` 统一执行。工具调用前通过 `interrupt_before=["tools"]` 加了人机审批，避免模型直接执行高权限操作。当前还需要补三类工程防护：第一，`fetch_url` 要加 URL scheme、DNS 解析、私网 IP、重定向后的目标地址校验；第二，拒绝工具调用时必须为每个 `tool_call_id` 返回一条 ToolMessage；第三，工具返回结构要稳定，比如 `search_web` 应返回 title、url、snippet，而不是只有拼接文本。

面试时不要说“我已经实现了 SSRF 防护”，应该说：

> 我已经识别到 `fetch_url` 是 SSRF 风险点，下一步会加 `is_safe_url` 和重定向校验。

### 题 3：Context Window 与记忆机制怎么设计？

原答案优点：

- “不要把所有网页源码放进 messages”这个方向是对的。

原答案问题：

- 当前项目的聊天 Agent 仍然使用 `messages` 作为 LangGraph state。
- 当前 RAG 是历史消息检索，不是项目文件检索，也不是深度研究结构化 state。

更稳的回答：

> 当前项目有两层记忆：第一层是 LangGraph checkpoint，它保存当前 thread 的图状态，用于工具审批后的恢复；第二层是 PostgreSQL messages 表，它保存用户和 AI 消息，并用 pgvector 做长期语义检索。后续做文件检索 Agent 时，我不会把文件全文塞进 messages，而是单独建 `file_documents` 和 `file_chunks`，只把 top-k chunk 交给 LLM。这样可以避免 Context Window 爆炸，并且能做到来源引用。

### 题 4：RAG 需要做哪些优化？

原答案优点：

- Recall/Precision、BM25、向量检索、当前会话污染都讲到了。

原答案问题：

- 当前项目没有 BM25。
- 当前项目还没有 `exclude_conversation_id`。
- 当前 `embed_text()` 在异步接口里同步执行，会阻塞事件循环。

更稳的回答：

> 当前项目的 RAG 是“向量召回 + reranker 精排”：先用 BGE embedding 写入 `messages.embedding`，查询时用 pgvector 按距离召回，再用 BGE reranker 对候选消息重排。下一步我会做三件事：第一，给 `search_messages` 增加 `exclude_conversation_id`，避免当前对话污染；第二，把 embedding 调用放进 `asyncio.to_thread`，避免阻塞 FastAPI event loop；第三，在文件检索场景中把 RAG 数据从 messages 拆到 file_chunks，保证会话记忆和文件知识库隔离。

### 题 5：Agentic RAG 和传统 RAG 有什么区别？

原答案基本可用，但要落到你的项目上。

更稳的回答：

> 传统 RAG 是一次性“检索 -> 生成”，检索失败通常就回答不知道。Agentic RAG 会把检索过程变成可规划、可调整的流程，比如先拆解 query、判断是否需要改写、检索不足时换关键词或扩大范围。在我当前项目里，聊天 Agent 已经具备工具调用和审批恢复能力；下一步文件检索 Agent 会先做可控版本：query -> 文件 chunk 检索 -> rerank -> 报告生成。等这个闭环稳定后，再加入 query rewrite 或多轮检索。

### 题 6：为什么选 LangGraph？

原答案方向正确，但要注意不要夸大。

更稳的回答：

> 我选 LangGraph 是因为它适合有状态、多步骤、可中断恢复的 Agent。我的项目里已经用 `AsyncPostgresSaver` 把 checkpoint 存到 PostgreSQL，并用 `interrupt_before=["tools"]` 实现工具调用前的人机审批。相比简单 LangChain chain，LangGraph 更适合表达“模型 -> 工具 -> 模型”的循环和中断恢复。相比 CrewAI/AutoGen 这类更上层框架，LangGraph 更可控，也更适合我这种需要展示工程细节的项目。

## 3. question.md 里需要降级或删除的说法

这些说法如果还没实现，面试时不要用“已经做了”的语气。

| 原说法 | 问题 | 建议改法 |
|---|---|---|
| 已实现 planner/researcher/writer 深度研究图 | 当前没有 `research_graph.py` | 改成“计划做独立文件检索报告图/流程” |
| 已有两个人机审批点 | 当前只有工具调用审批 | 改成“已有 tool interrupt，文件检索第一版不做审批” |
| 已有 SSRF 防护 | 当前 `fetch_url` 没有校验 | 改成“识别到风险，计划修复” |
| 已修复 async embedding 阻塞 | 当前仍同步调用 | 改成“这是当前待修复性能问题” |
| 已修复多工具拒绝协议 | 当前只取第一个 tool_call | 改成“这是待修复协议对齐问题” |
| 已有 `report_chunk` SSE | 当前只有聊天 `text` SSE | 改成“文件报告会新增 report SSE 协议” |
| 当前有完整测试 | 当前没有 `backend/tests/` | 改成“下一步补测试体系” |

## 4. 当前项目最值得优先改的点

### P0：必须先修

1. `embed_text()` 在 FastAPI async 流程里同步执行。
2. 拒绝多工具调用时只返回一条 ToolMessage。
3. `fetch_url` 缺少 SSRF 防护。
4. 前端 `v-html` 直接渲染 `marked` 输出，缺少 HTML sanitize。
5. `start-dev.sh` 的前端路径写成了 `frontend/my-vue-project`，但当前真实前端目录是 `frontend`。

### P1：做文件检索 Agent 必须补

1. 文件上传依赖 `python-multipart`。
2. 单独建 `file_documents`、`file_chunks`、`file_reports`。
3. 文件检索必须按 `user_id` 隔离。
4. 报告下载必须校验 report 属于当前用户。
5. 文件解析只支持白名单后缀，限制大小，不能信任用户上传的文件名路径。

### P2：面试加分但可以后做

1. PDF/Word 解析。
2. Query rewrite。
3. Hybrid Search。
4. 文件级引用高亮。
5. Langfuse trace 里记录 report_id、file_id、chunk_id。

## 5. 简历/面试推荐表述

可以这样写：

> Agentic OS：基于 FastAPI、Vue 3、LangGraph、PostgreSQL + pgvector 的多租户 Agent 平台。已实现 JWT 登录、SSE 流式对话、LangGraph 工具调用审批、PostgreSQL checkpoint、历史消息向量检索与 reranker 精排。正在扩展文件检索报告 Agent：支持用户上传文本文件，系统自动切块向量化、检索相关片段，并生成带来源引用的 Markdown 报告下载。

这句话比较稳，因为它区分了“已实现”和“正在扩展”。

## 6. 你可以这样回答面试官追问

### 追问：你这个项目最核心的工程难点是什么？

回答：

> 核心难点不是简单调模型，而是把 Agent 的长流程变成可恢复、可观测、可控的工程系统。我用了 LangGraph checkpoint 解决工具审批后的状态恢复，用 SSE 解决长任务反馈，用 pgvector + reranker 解决长期记忆检索。现在做文件检索报告时，我会把文件 chunk 和聊天 messages 分表，避免上下文污染，并通过 user_id 保证多租户隔离。

### 追问：你怎么避免 RAG 幻觉？

回答：

> 我会从三层控制：第一，检索阶段用向量召回加 reranker 精排，提高输入片段相关性；第二，prompt 要求模型只基于检索片段回答，不足时明确说证据不足；第三，报告里每个关键结论必须标注来源文件和 chunk id。这样即使答案不完整，也能追溯证据来源。

### 追问：为什么不用一个超长 prompt 直接把文件塞进去？

回答：

> 这样会遇到 Context Window 和 Lost in the Middle 问题，也无法扩展到多文件。我的做法是上传后预处理成 chunks 并向量化，查询时只取 top-k 相关片段。这是更可扩展、更可追踪的方案。

### 追问：你的系统现在还有哪些不足？

回答：

> 目前不足我很清楚：文件检索还在扩展阶段；`fetch_url` 需要补 SSRF 防护；embedding 推理要从 async 路径卸载到线程池；测试体系还不完整。我现在的优先级是先把文件检索报告闭环跑通，再补安全、测试和多格式解析。

## 7. 对你的项目路线建议

你的目标是大三结束前做一个真正有竞争力的项目。不要再把方向扩成“万能 Agent”。建议聚焦成：

> 面向个人知识库的文件检索报告 Agent。

最小闭环：

1. 上传资料。
2. 自动索引。
3. 输入研究问题。
4. 检索证据。
5. 生成 Markdown 报告。
6. 下载报告。

这个闭环比“聊天机器人会调用工具”更像一个可展示产品，也更适合面试讲系统设计、RAG、Agent、数据库、安全和前端体验。

## 8. 下一步行动

直接执行 `codex-2026-deep-research.md` 的顺序：

1. 修基础 bug。
2. 加文件表和迁移。
3. 做上传索引。
4. 做检索。
5. 做报告生成和下载。
6. 做前端页面。
7. 补测试。

不要先做复杂 UI，也不要先做 PDF/Word。先把 `question.md` 上传进去，让系统能自动生成“面试题复核报告”，这就是你自己的项目第一条真实用例。
