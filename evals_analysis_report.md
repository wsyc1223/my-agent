# RAG/Agent 评估体系（Evals）源码阅读与方案优化分析报告

> **目标**：本文档基于对项目源码（后端 `FastAPI`、`LangGraph` 工作流、`Taskiq Worker` 评估任务及测试集等）的深度分析，对 [evals_design_plan.md](file:///home/wsyc1/projects/langchain/evals_design_plan.md) 计划书进行架构合理性评估，指出潜在工程隐患与过时方案，并给出高含金量的可执行改进方案。

---

## 🔍 项目源码阅读结论与对齐

在仔细阅读了项目整体代码后，目前系统的核心逻辑对齐如下：
1. **主对话流 (chat_stream)**：在 [agent.py](file:///home/wsyc1/projects/langchain/backend/src/service/agent.py#L16-L137) 中，使用编译好的 `app` (含有 checkpointer，且在 `tools` 节点前触发 `interrupt_before`)。对话结束后强制向 Langfuse 推送并触发评估任务。
2. **后台深度研究 (run_research_in_background)**：在 [file_research.py](file:///home/wsyc1/projects/langchain/backend/src/service/file_research.py#L141-L328) 中，利用 `research_app` 完成长耗时的调研并生成 `report_md`。任务结束后同样把 Trace ID 回传至 Taskiq Worker。
3. **评测任务 (evaluate_trace_task)**：在 [task.py](file:///home/wsyc1/projects/langchain/backend/src/eval_service/task.py#L29-L166) 中，利用 Ragas v0.4 对 `Faithfulness`（忠实度）和 `AnswerRelevancy`（相关度）两个指标打分并回传给 Langfuse。
4. **现有检索 (retriever.py)**：在 [retriever.py](file:///home/wsyc1/projects/langchain/backend/src/file_research/retriever.py) 中，提供 `vector_search_chunks` (向量粗筛 + bge-reranker 重排) 和 `grep_search_chunks` (ILIKE 精确子串检索) 两种手段。

---

## 🛠️ 计划报告深度评审与隐患警示

针对 [evals_design_plan.md](file:///home/wsyc1/projects/langchain/evals_design_plan.md) 提出的三个本地精雕细琢任务，我们从可验证性、稳定性和现代架构角度进行深度评审：

### 1. 任务 1：升级 Worker 评估指标 (增加 Agent 维度评估)
*   **【隐患一】未作 Trace 类型区分（严重缺陷）**：
    普通 RAG 会话（`chat_stream`，主要是闲聊或非文档研读）并不需要调用 `search_document_by_vector`。如果在 `task.py` 评估工具选择准确率时一概而论，普通对话会被误判为“未触发向量检索工具，工具选择准确率：0.0分”，造成大规模误报。
    *   *方案*：根据 Trace 的 `tags`（如 `"deep_research"`）或 Metadata 标识，仅对深度研究任务激活 `tool_call_accuracy` 评估，普通会话只进行 RAG 核心指标打分。
*   **【隐患二】`trajectory_steps` 的计算方式不够严谨**：
    在 Ragas/Langfuse 的数据模型中，`trace_data.observations` 代表所有的 tool 节点调用次数。但更稳健的指标是统计整个推理轨迹中的 `tool_calls` 总步数或 `AIMessage` 的 tool_calls 列表。此外，仅上传“负向指标”无法直观反映在仪表盘中。
    *   *方案*：我们可以在 Langfuse 中创建一个自定义分数值 `agent_trajectory_efficiency`：如果步骤数 $\le 8$，则记为 $1.0$（满分）；若 $> 8$，则扣分或记为 $0.0$。

### 2. 任务 2：编写「离线回归评测脚本（`run_offline_eval.py`）」
*   **【难点】异步评估带来的“时序脱节”**：
    由于 `evaluate_trace_task` 是放入 Redis 队列由 Taskiq 异步跑分的，`run_offline_eval.py` 在并发调用 FastAPI 发送 15 个对话后，并不能立马拿到分数。
    *   *优化妙招（UUID 锚定法）*：在 `run_offline_eval.py` 中，**主动本地生成 15 个 UUID 作为 `conversation_id`**，并通过 `ChatRequest` 传给后端。由于后端会把 `conversation_id` 直接用作 Trace ID，我们可以直接确定这 15 个 Trace ID，随后通过 Langfuse SDK 配合指数退避（Exponential Backoff）进行轮询拉取分数。
*   **【性能】并发限流与裁判 LLM 耗时**：
    并发调用 15 个测试用例，在 Taskiq 侧会被打散为 15 个 Ragas evaluate 任务。如果并发太高，会导致 DeepSeek API 报错 Rate Limit 或本地 CPU 跑满（sentence-transformers 在做 local embedding 时需要 CPU/GPU 算力）。
    *   *方案*：在 Taskiq 侧控制并发度，或在回归测试脚本中合理控制吞吐。

### 3. 任务 3：优化 RAG 检索算法
*   **【技术债警示】PostgreSQL 中文全文检索的局限性**：
    计划中提到“在 PostgreSQL 中创建 `tsvector` 全文检索索引”。但在实际的 PostgreSQL Docker 容器中（尤其是标准的 pgvector 镜像），默认并不包含中文分词器 `zhparser`。
    如果强行使用 `to_tsvector('simple', content)`，Postgres 会把整个中文句子看成一整个词或按单个汉字切分，检索效果甚至差于 `LIKE` / `ILIKE` 检索。
    *   *破局方案（双路召回最佳实践）*：
        *   **路一（语义向量检索）**：pgvector 语义检索。
        *   **路二（精准文本召回）**：利用 Postgres 自带的 `pg_trgm`（三元组）GIN 索引，加速 ILIKE 匹配。这在中文环境中，针对专有名词、类名、配置参数的召回效果**远超没有分词器的 tsvector**，且无需破坏已有的表结构。
        *   **在 Python 端引入真正的 BM25 检索**：如果确实需要高精度的中文词级全文检索，可在 Python 端使用 `jieba` 分词 + `rank_bm25`（如果允许引入该依赖），或者利用 `pg_trgm` 配合 GIN 索引。
*   **RRF (Reciprocal Rank Fusion) 融合排序实现**：
    RRF 评分公式如下：
    $$RRF\_Score(d) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$
    $k$ 取常规值 60，两路排序好的候选集通过该公式完成去重与精排评分，再进行 BGE Reranker 二次精排。这构成了业界最规范的 **多路粗筛 -> RRF融合 -> 深度重排** 三阶段架构。

---

## 🚀 下一步可执行动作

1. **第一步（指标与回归闭环）**：优先升级 `task.py` 中的 Worker 评测指标（添加 Trace 类型感知与轨迹效率打分），并在 `tests/evals/` 下开发离线回归测试脚本 `run_offline_eval.py`。
2. **第一步（检索优化）**：运行回归测试脚本，记录下当前版本的 Baseline 分数。随后着手优化 `retriever.py` 的检索部分（引入 GIN 索引多路召回 + RRF 融合精排），再次跑分以验证指标是否得到真正提升。
