# 项目评估与一个月冲刺方案

> 评估日期：2026-07-03
> 评估对象：智能文档研究 Agent（LangGraph 多 Agent RAG 对话系统）
> 评估目标：在一个月内做出"能落地 + 能通过 Agent 开发岗技术面"的项目
> 评估方法：全量本机代码静态核实 + 数据库审计交叉（见 bug.md）+ roadmap.md/question.md 一手材料交叉
> 证据标记：✅ 已亲自核实（读代码/查文件确认）／⚠️ 部分修／❌ 未修／🔍 需运行时验证

---

## 〇、先说结论（TL;DR）

| 维度 | 结论 |
|---|---|
| **项目骨架** | 选型现代、架构合理（LangGraph 双图 + FastAPI + pgvector + Vue3），方向正确 |
| **当前能落地吗** | ❌ 不能。核心演示路径有 3 个未修 bug（后台无中间过程、报告可能空白、侧边栏架构混乱），演示会翻车 |
| **当前能过技术面吗** | ⚠️ 勉强过中小厂应用岗，大厂追问易塌。**评估体系 0% 是 2026 面试红线** |
| **最大隐患** | 你把 SSRF 当简历亮点，但它有 DNS rebinding 漏洞未修——亮点变雷点 |
| **roadmap 执行偏差** | 6/20 规划的"第一阶段致命缺失修补"两周过去 **0 进度**，时间全花在修 bug |
| **一个月能到哪** | 项目竞争力从 **45-55% → 75-85%**（仅"项目作为技术面谈资"维度，不含算法/学历/HR） |
| **核心建议** | **砍掉 roadmap 第三、四阶段**（MCP/多模型路由/GraphRAG），一个月只做三件事：① 修死 demo 路径 ② 补三个致命缺失（评估/错误分层/Agentic RAG）③ 工程闭环（Docker+可观测+少量测试） |

---

## 一、评估方法与证据基线

### 1.1 证据来源（按可信度排序）

1. **本机一手代码核实**（本次亲自读代码确认，置信度 High）：
   - `backend/src/utils/security.py`（JWT 实现）
   - `backend/src/file_research/retriever.py`（检索方式）
   - `backend/src/file_research/research_graph.py`（图节点结构）
   - `backend/src/tools.py`（错误处理 + SSRF）
   - `backend/src/service/file_research.py`（后台任务流式性）
   - `frontend/src/views/ChatView.vue`（侧边栏 + XSS）
   - `pyproject.toml` / `package.json`（技术栈与版本）
   - 目录结构（Docker/evals/tests 是否存在）

2. **数据库实锤**（bug.md 第二轮已查，7-01）：
   - `file_reports` 唯一记录 `status=success` 但 `report_md` 长度=0
   - `messages` 表：user=7 / assistant=11 / tool=11 / subagent=1

3. **用户一手整理材料**：`bug.md`（60+ 缺陷 + 修复标注）、`roadmap.md`（6-20 规划）、`question.md`（6 大面试题逆向）

### 1.2 诚实声明（重要）

> **关于"成功概率"**：Agent 开发岗面试通过率 = f(项目质量, 算法/八股基础, 学历筛选, 目标公司层级, 沟通表达, 竞品强度)。
> 我**只能负责任地评估"项目作为技术面谈资的竞争力"这一维度**（基于一手代码证据）。
> 你未提供：算法刷题量、八股掌握度、目标公司层级（大厂/中厂/创业）、投递时间窗口。这些会显著影响最终通过率。
> 因此本文的概率区间是"项目竞争力"的相对评估，不是"拿到 offer 的绝对概率"。
> **岗位市场需求/最新 JD 考点**：本文基于 question.md + roadmap.md 的一手整理 + 通用行业认知，**未联网核对 2026-07 最新岗位要求**。投递前请自行对照目标公司 JD 微调。

---

## 二、项目真实画像（一手核实 vs 标称）

### 2.1 技术栈（✅ 选型合理，无过时风险）

| 层 | 实际版本 | 评价 |
|---|---|---|
| Agent 框架 | LangGraph 1.2.4 | ✅ 主流，但 roadmap 建议升最新稳定版 |
| 后端 | FastAPI ≥0.135 + Python 3.12 | ✅ |
| LLM | DeepSeek（langchain-openai 1.1.12） | ✅ 性价比 |
| 向量库 | PostgreSQL + pgvector | ✅ 减组件 |
| Embedding/Reranker | BGE-base-zh-v1.5（768d，本地 vocab 已下载） | 🟡 可升 BGE-M3 |
| 持久化 | PostgresSaver（checkpoint） | ✅ |
| 可观测 | Langfuse ≥4.6（回调） | 🟡 仅回调，trace 串扰未修 |
| 前端 | Vue 3.5 + Vite 8 + TS 6 + Pinia 3 | ✅ 很新 |
| 认证 | JWT(HS256) + bcrypt | 🟡 见安全节 |
| 部署 | **无 Docker / 无 Dockerfile** | ❌ |

### 2.2 功能完成度（一手核实后的真实值，非 roadmap 标称）

```
真实整体完成度: ~50%（roadmap 标 55%，但致命缺失项全 0）
```

| 模块 | 真实状态 | 能讲？ |
|---|---|---|
| 流式聊天 + HITL 审批 | 🟢 可跑，但 resume 边界未校验（补充-29） | ✅ 但有坑 |
| 文件上传→解析→向量化 | 🟢 可跑 | ✅ |
| 两阶段检索（向量+reranker） | 🟢 可跑，但无 BM25、无相似度阈值 | ⚠️ 缺对比数据 |
| SSE 流协议 + 打字机 | 🟢 可跑 | ✅ 强亮点 |
| SSRF 防护 | 🟡 **有 DNS rebinding 漏洞未修** | ⚠️ 亮点有洞 |
| 异步阻塞 to_thread | 🟢 已做 | ✅ 亮点 |
| 多工具协议对齐 | 🟢 已修（曾是 bug，现 Command update+goto） | ✅ 但故事要更新 |
| 深度研究 researcher+writer | 🟡 **Bug 5 致空报告**、无 Query Rewrite | ⚠️ 不完整 |
| **评估体系（Evals）** | 🔴 **0%，无 evals 目录** | ❌ **面试红线** |
| **错误分层** | 🔴 **0%，tools.py 仍 return f"错误:..."** | ❌ |
| **可观测性 tracing** | 🔴 30%，trace 串扰未修 | ❌ |
| **Docker 部署** | 🔴 0% | ❌ |
| 测试覆盖 | 🔴 仅 12 个文件解析单测 | ❌ |
| 上下文长度管理 | 🔴 0%（长会话必然 400 卡死） | ❌ |

---

## 三、致命不足分析（按"面试杀伤力"排序）

### 3.1 🔴 评估体系 0% — 2026 面试第一红线

- **现状**：`backend/tests/` 仅 4 个文件解析单测（test_file_parser/chunk_line/indexing_service/retriever），**无 evals/ 目录，无 golden set，无 Recall/Precision/Faithfulness 指标**。
- **杀伤力**：2026 年面试"不讨论如何评估 Agent 性能 = 红旗"。面试官一问"你怎么知道你的 RAG 检索效果好不好"，你答不上来 = 直接出局。
- **根因**：roadmap 第一阶段 1.3 规划了，但两周没动。

### 3.2 🔴 核心演示路径 3 个未修 bug — demo 会翻车

| Bug | 状态 | 证据 |
|---|---|---|
| **Bug 2 后台任务无中间过程** | ❌ 未修 | `file_research.py:187` 仍 `await research_app.ainvoke(...)` 非流式阻塞，`send_message` 只在 209/245/281（终态）调用。用户发起深度研究后**界面零反馈，无法判断任务是活是死** |
| **Bug 5 报告可能空白** | ⚠️ 部分修 | `research_graph.py:68` writer 已返回 report_md，但 `:81-82 if tool_count == 0: return END` 仍在——researcher 没调工具时 writer 不执行，**report_md 永远空但 task 标 success**。数据库实锤：report_md 长度=0 |
| **Bug 4 侧边栏被覆盖** | ❌ 未修 | `ChatView.vue:196` showReport = tabs.length>0，Agent 状态与报告面板是 **v-if/v-else 互斥**，不是你要的"多卡片堆叠+折叠" |

> **影响**：面试现场演示深度研究功能时，用户看不到进度→以为卡死→任务完成但点开报告是空的→侧边栏状态栏消失。**这三个 bug 叠加 = 演示灾难**。

### 3.3 🔴 SSRF 亮点有 DNS rebinding 漏洞 — 亮点变雷点

- **现状**：`tools.py:25` 仍 `socket.gethostbyname(parsed.hostname)` 同步调用 + **TOCTOU 校验时和请求时 IP 可能不同（DNS rebinding）**，且只查 IPv4，IPv6 内网漏检。
- **杀伤力**：你在 question.md/roadmap.md 都把"SSRF 防护（DNS 解析+IP 校验）"列为**简历四大亮点之一**。面试官会追问："你这个防護能防 DNS rebinding 吗？"——答不上来 = 简历亮点当场被证伪有洞，**比不写还扣分**。
- **结论**：要么修好它（getaddrinfo 全解析 + 请求时绑定已校验 IP + IPv6），要么从简历撤下别当亮点讲。

### 3.4 🔴 Agentic RAG 不完整 — 缺核心特征

- **现状**：`research_graph.py` 只有 researcher → tools → researcher 循环 → writer，**无 Query Rewrite 节点**。
- **杀伤力**：面试 Q5"Agentic RAG 和传统 RAG 区别"，Query Rewrite 是第一个要举的例子。你没有 = 无法证明这是"Agentic"。

### 3.5 🔴 工程闭环缺失（部署/可观测/测试/上下文管理）

- **Docker 0%**：无 docker-compose、无 Dockerfile。面试问"怎么部署"答不上。
- **可观测 trace 串扰**：`observability.py:16` Langfuse handler 全局单例被并发共享（补充-25 未修），trace 归属错乱，可观测数据不可信。
- **测试 12 个**：全是文件解析单测，**0 个 agent/rag/SSE/HITL 测试**。面试问"测试策略"无话可说。
- **上下文长度管理 0%**（补充-33）：长会话超模型窗口→400→会话卡死。面试问"长对话怎么处理"答不上。

### 3.6 ⚠️ 安全修复半成品（bug.md 标 Resolved 但实测部分未真修）

| 项 | bug.md 标注 | 实测 | 证据 |
|---|---|---|---|
| XSS badge.innerHTML | Resolved | ✅ 真修 | `ChatView.vue:98` 已是 `badge.textContent` |
| 拒绝不拦截 | Resolved | ✅ 真修 | `agent.py:139` Command(update+goto) |
| JWT 弱密钥 | Resolved | ⚠️ 部分 | 密钥已换高熵串，但 **HS256 未变、无 refresh、无登出/吊销**（补充-13 未修） |
| SSRF rebinding | 未标 | ❌ 未修 | `tools.py:25` gethostbyname |
| 数据库弱口令 987654 | 未标 | ❌ 仍在 `.env` | 补充-46 |

> **教训**：bug.md 的 (Resolved) 标注**不可全信**，已逐条复核。剩余安全项虽不直接影响面试谈资，但被深挖时是减分项。

### 3.7 ⚠️ 前端技术债

- `ChatView.vue` **1965 行**单文件（roadmap 写 1528，更长了），未拆组件。
- `DeepResearchView.vue` **1377 行孤儿代码**（/research 重定向到 /，0 引用），仍在 bundle 里，含同款逻辑，维护负担 + 误导。
- `window.__isDark/__userName` 全局挂载反模式（补充-49），登录时侧边栏显示空名。

---

## 四、成功概率评估

### 4.1 评估框架

用"面试官典型追问清单的覆盖度"量化项目竞争力（这是我能基于一手证据负责任评估的维度）：

**面试官追问清单（10 项，每项 10 分）**：
1. Agent 整体流程与状态恢复
2. Tool 失败处理/错误分层
3. 危险工具拦截（SSRF/HITL）
4. 上下文/记忆管理
5. RAG 指标量化（Recall/Precision）
6. Agentic RAG 特征（Query Rewrite/自适应）
7. 框架选型理由
8. 评估体系
9. 可观测性/成本
10. 部署/工程化

### 4.2 当前评分（7-03）

| 项 | 得分 | 说明 |
|---|---|---|
| 1 Agent 流程 | 6/10 | 双图架构清楚，但无失败重试、resume 边界未校验 |
| 2 错误分层 | 1/10 | 仅 catch return 字符串，无分层 |
| 3 危险工具 | 5/10 | 有 HITL+SSRF，但 SSRF 有 rebinding 洞 |
| 4 上下文/记忆 | 3/10 | 有 global_memory 开关，无分层、无窗口管理 |
| 5 RAG 指标 | 0/10 | 无任何量化数据 |
| 6 Agentic RAG | 3/10 | 有 researcher+writer，无 Query Rewrite |
| 7 框架选型 | 6/10 | 用了 LangGraph，能讲基本理由 |
| 8 评估体系 | 0/10 | 完全缺失 |
| 9 可观测性 | 2/10 | 仅回调，trace 串扰 |
| 10 部署 | 0/10 | 无 Docker |
| **合计** | **26/100** | |

> **当前项目竞争力：~45-55%**（折合区间，因为"能讲"不等于"答得好"，且有未修 bug 演示风险）。
> **能过的面试**：中小厂/创业公司 Agent 应用岗技术面（项目能跑+有亮点）。
> **过不了的**：大厂/算法平台岗（评估红线 + 追问易塌 + 演示翻车）。

### 4.3 一个月后评分（执行本文第五节方案后）

| 项 | 目标得分 | 提升点 |
|---|---|---|
| 1 Agent 流程 | 8/10 | +失败重试+resume 校验 |
| 2 错误分层 | 7/10 | +三层异常+error_handler 节点 |
| 3 危险工具 | 8/10 | +修 SSRF rebinding（亮点变真亮点） |
| 4 上下文/记忆 | 6/10 | +窗口摘要压缩（简化版分层） |
| 5 RAG 指标 | 7/10 | +golden set+Recall/Precision+BM25 对比 |
| 6 Agentic RAG | 7/10 | +Query Rewrite 节点 |
| 7 框架选型 | 7/10 | +量化对比理由 |
| 8 评估体系 | 7/10 | +CI 评估管线 |
| 9 可观测性 | 6/10 | +修 trace 串扰+cost 统计 |
| 10 部署 | 7/10 | +Docker Compose 一键起 |
| **合计** | **70/100** | |

> **一个月后项目竞争力：~75-85%**（取决于执行质量与投入时间）。
> **能过的面试**：大多数 Agent 应用岗技术面。
> **仍受限**：①深度差异化不足（无 MCP/多模型路由/GraphRAG，这些大厂加分项做不了）②算法/八股/学历筛选等**项目外因素**未计入。

### 4.4 概率提升的关键认知

> ⚠️ **概率从 50% 涨到 80% 的关键不是"做多少新功能"，而是三件事：**
> 1. **演示不翻车**（修 Bug 2/4/5）——demo 翻车 = 面试直接结束，再多功能也白搭
> 2. **致命题答全**（评估/错误分层/Query Rewrite）——这是"有没有"问题，没有就是红线
> 3. **亮点补成无洞**（修 SSRF）——有洞的亮点比没亮点更扣分

**反面警示**：如果你继续过去两周的模式（边修 bug 边欠新债、roadmap 致命缺失 0 推进），一个月后概率仍是 50%，因为致命缺失不会自己消失。

---

## 五、一个月落地方案（聚焦，已砍掉低 ROI 项）

### 5.1 砍掉什么（明确不做）

| 砍掉项 | 理由 |
|---|---|
| MCP 协议集成 | 2026 考点，但**包装成 MCP Server 工作量大、收益边际**。能口头讲清 MCP vs A2A 区别即可，不必实现 |
| 多模型路由+Fallback | 代码量小但**调试成本高**（要配多 key/降级链），一个月不值得 |
| GraphRAG / 结构感知切块 | 第四阶段锦上添花，**ROI 最低** |
| 前端大重构（拆 1965 行） | 时间黑洞，**只做最小清理**（删孤儿 DeepResearchView + 修 401） |
| 分层记忆完整版 | 只做**简化版**（窗口摘要），不做 UserPreference 表 |
| LangGraph 版本升级 | 1.2.4 够用，升级有 breaking change 风险，不碰 |

### 5.2 保留并做透什么（按周排期）

> 假设每周能投入 ~25-30 小时。若投入不足，按优先级从上往下砍。

#### Week 1：修死核心 demo 路径（最高优先，演示不翻车）

| 任务 | 改哪里 | 验收 |
|---|---|---|
| **修 Bug 5 空报告** | `research_graph.py:81-82` 删除 `tool_count==0 → END`，改为"无工具调用时 writer 仍执行并生成说明"或直接标 failed | 数据库 `report_md` 长度>0 |
| **修 Bug 2 后台无中间过程** | `file_research.py` 改 `ainvoke`→`astream`，在 researcher/tools/writer 各节点发 `progress/tool_call/thinking` 中间事件（notifier 已支持，只是没人调） | 前端能看到"正在检索/正在生成" |
| **修 Bug 4 侧边栏架构** | `ChatView.vue:196` 改 showReport 逻辑为"多卡片纵向堆叠"，Agent 状态作为常驻卡片，报告卡片叠加在上 | 状态栏与报告共存 |
| **修 SSRF rebinding** | `tools.py:25` 改 `getaddrinfo` 全解析 + 请求时用 `httpx` transport 绑定已校验 IP + IPv6 检查 | 能讲清 rebinding 防护 |
| **修 Bug 6 关联** | 补 `MessageOut.associated_task_id`（补充-17），前端去重不再重复刷屏 | 历史加载不重复 push |

#### Week 2：补三个致命缺失（面试红线）

| 任务 | 改哪里 | 验收 |
|---|---|---|
| **评估体系** | 新建 `backend/tests/evals/`：golden_set（20-30 条 Q&A）+ `eval_rag.py`（Recall@5/Precision@5/Faithfulness）+ `eval_tool_selection.py` | `pytest evals/` 跑出指标报告 |
| **错误分层** | `tools.py` 引入 `ToolRetryableError/ToolFatalError`；`research_graph.py` 加 `error_handler` 节点（可重试→retry≤3，致命→error_summary→END） | 工具失败有结构化 ToolMessage |
| **Query Rewrite** | `research_graph.py` researcher 前加 `query_rewriter` 节点（拆子问题+路由 vector/grep/hybrid） | 能讲 Adaptive RAG |

#### Week 3：工程闭环 + BM25

| 任务 | 改哪里 | 验收 |
|---|---|---|
| **BM25 混合检索** | `retriever.py` 加 tsvector+GIN 通道，RRF 融合向量+BM25，reranker 精排 | golden set 上 Recall@5 提升，有对比数据 |
| **Docker Compose** | 根目录 `docker-compose.yml`（pgvector + backend + frontend）+ Dockerfile | `docker compose up` 一键起 |
| **可观测性修** | `observability.py` 改每请求新建 Langfuse handler；加 cost/token 统计 span | trace 不串扰 |
| **上下文管理** | `graph.py` agent_node 前加 token 计数，超 0.8 窗口→摘要压缩 | 长会话不 400 |

#### Week 4：测试加固 + 简历话术 + 面试演练

| 任务 | 说明 |
|---|---|
| **关键路径测试** | 给 SSE 流式/HITL resume/检索召回 各补 3-5 个测试（不必追求覆盖率，追求"能讲测试策略"） |
| **删孤儿代码** | 删 `DeepResearchView.vue`/`ResearchSidebar.vue`/`stores/research.ts`，清理 `window.__` 反模式 |
| **简历三段式话术** | 每个亮点写成"为什么做→怎么做→效果数据"。**特别更新 SSRF 故事**（从"我做了防护"→"我发现初版有 rebinding 漏洞，改用 getaddrinfo+IP 绑定修复"，这反而是更好的故事） |
| **面试模拟** | 对着 question.md 6 大题 + 10 项追问清单自测，卡壳的回去补 |

### 5.3 优先级铁律

> 如果时间不够，**按此顺序保底**（砍后面的保前面的）：
> 1. 修 Bug 2/4/5 + SSRF（demo 不翻车）
> 2. 评估体系（红线）
> 3. 错误分层 + Query Rewrite（致命题）
> 4. Docker（工程化）
> 5. BM25 + 可观测 + 测试（锦上添花）
>
> **宁可少做做透，不要多做做浅。** 面试官追问"你最大的技术难点"时，只有亲手踩坑的功能你才答得好。

---

## 六、项目修改意见（具体到文件）

### 6.1 必改（影响演示/安全/面试红线）

| # | 文件:行 | 问题 | 改法 |
|---|---|---|---|
| 1 | `backend/src/file_research/research_graph.py:81-82` | tool_count==0 跳 writer 致空报告 | 删除该分支，或无工具时让 writer 生成"未检索到相关信息" |
| 2 | `backend/src/service/file_research.py:187` | ainvoke 非流式，无中间过程 | 改 astream，节点内发 progress 事件 |
| 3 | `frontend/src/views/ChatView.vue:196` | showReport v-if/v-else 互斥 | 改为多卡片堆叠，状态栏常驻 |
| 4 | `backend/src/tools.py:25` | SSRF gethostbyname + rebinding | getaddrinfo 全解析 + 请求绑定 IP + IPv6 |
| 5 | `backend/src/file_research/retriever.py` | 无 BM25、无相似度阈值、LIKE 大小写敏感 | 加 tsvector+GIN，RRF 融合，加 WHERE similarity>阈值，LIKE→ILIKE |
| 6 | `backend/src/observability.py:16` | Langfuse 单例 trace 串扰 | 改每请求新建 handler |
| 7 | `backend/src/tools.py` 全文 | 错误 return 字符串无分层 | 引入异常体系 + error_handler 节点 |
| 8 | `backend/src/graph.py` | 无上下文长度管理 | agent_node 前 token 计数+摘要 |
| 9 | `backend/src/schemas.py` | MessageOut 缺 associated_task_id/id | 补字段，对齐前后端契约 |
| 10 | 新建 `backend/tests/evals/` | 评估体系 0 | golden set + 指标脚本 |
| 11 | 新建 `docker-compose.yml` | 无部署 | pgvector+backend+frontend |

### 6.2 应改（工程质量）

| # | 文件 | 问题 | 改法 |
|---|---|---|---|
| 12 | `backend/src/utils/security.py:14-15` | HS256+7天无refresh | 至少缩短 access token 有效期 + 加 refresh token |
| 13 | `backend/main.py` | 全局异常 str(exc) 泄露 + 无限流 | 异常分层返回通用信息 + slowapi 限流 |
| 14 | `backend/.env` | DB 弱口令 987654 | 改强口令（即便本地） |
| 15 | `frontend/src/views/DeepResearchView.vue` 等 | 孤儿代码 1377 行 | 删除 |
| 16 | `frontend/src/stores/chat.ts` | 401 不跳转、500 不判 ok、console.log | 统一错误处理 + 删调试日志 |
| 17 | `frontend/src/views/ChatView.vue:486` | v-for 用 index 作 key | 用消息稳定 id |
| 18 | `backend/src/service/agent.py` | 流式断开 AIMessage 丢失（补充-06） | 落库移到 finally 或流式增量提交 |

### 6.3 可改（有余力再做）

- BGE-base-zh → BGE-M3（迁移成本高，vector 维度变了要重建索引）
- `interrupt_before=["tools"]` 对所有工具一视同仁 → 区分危险工具
- checkpoint TTL 清理（补充-32）
- 向量列 HNSW 索引（补充-19）

---

## 七、风险与需你确认的事项

### 7.1 风险

1. **最大风险：执行纪律**。过去两周 roadmap 致命缺失 0 推进，说明你容易陷在修 bug 里。**建议每天开工先做本周最高优先级任务，bug 只修阻塞 demo 的**。
2. **演示依赖运行环境**：bug.md 提到 postgres 容器曾停 3 周。面试演示前必须确保 `docker compose up` 能起、核心路径跑通。**建议 Week 4 用一台干净环境验证演示**。
3. **概率估算不含项目外因素**：算法刷题、八股、目标公司层级会显著影响最终结果。如需更精确的"拿到 offer 概率"，请补充：目标公司层级、算法基础、投递时间。

### 7.2 需你确认（影响方案调整）

1. **目标公司层级**：大厂（字节/阿里 AI 平台）/ 中厂 / 创业公司？层级越高，评估体系和系统设计追问越深，需投入越多。
2. **每周可投入小时数**：本方案按 25-30h/周估，不足则按 5.3 铁律砍。
3. **是否已开始投递/面试**：若已投递，需优先准备"现有 4 个亮点怎么讲"，而非补新功能。
4. **算法/八股基础**：若薄弱，项目投入要压缩给刷题让路（项目过线即可，靠算法拉开差距）。

### 7.3 你可能还不知道

- **"演示翻车"比"功能少"更致命**：面试官对一个跑不起来的项目印象极差。Bug 2/4/5 不修，其它都白做。
- **简历亮点要能扛追问**：SSRF、协议对齐这些你列的亮点，背后都有真实 bug 故事（rebinding 漏洞、Command resume 语义错误）。**讲"我发现了什么坑、怎么修的"比讲"我做了什么"更有说服力**——前提是真修了。
- **评估体系是性价比最高的投入**：代码量不大（一个 golden set + 两个脚本），但面试杀伤力最大。Week 2 第一件事就做它。

---

## 附：本文证据可信度

- ✅ 已核实项（亲自读代码/查文件）：技术栈版本、Docker 缺失、evals 缺失、测试数量、JWT 实现、retriever 方式、research_graph 节点、tools 错误处理、Bug 2/4/5 状态、XSS 已修、SSRF 未修
- ⚠️ 基于 bug.md 标注未逐一复核的：其余 (Resolved) 安全项（建议按 6.2 逐条复核）
- 🔍 需运行时验证：Bug 1"第二次能正常显示"的竞态现象（bug.md 已标注 Medium 置信度）
- ❌ 未联网核对：2026-07 最新 Agent 岗 JD 考点、LangGraph 最新版本特性（建议投递前自行核对官方文档与目标 JD）

> 本文所有"不足"结论均有一手代码行号支撑，所有"概率"均明确标注为"项目竞争力维度"且声明不含项目外因素。如对任何结论有异议，可指出具体条目，我重新核实代码。
