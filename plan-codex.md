2. backend/src/tools.py:82 的 fetch_url 没有 SSRF 防护。你计划里已经识别到了，这是对的。能访问任意 URL 的工具，在后端 Agent 项目里属于高危点。
  3. frontend/src/views/ChatView.vue:17 直接 marked.parse，然后 frontend/src/views/ChatView.vue:205 用 v-html 渲染，没有 DOMPurify。LLM 输出可控 HTML 时有 XSS 风险。
  4. Task 5 的 grep 方案用 ILIKE "%keyword%"，能用但不够专业。pgvector 官方建议 hybrid search 可以结合 PostgreSQL full-text search，再用 RRF 或 cross-encoder
     融合。(github.com (https://github.com/pgvector/pgvector)) 你现在计划里的“vector + grep”是合格 MVP，不是最佳实践。

  5. 计划里没有检索评测。没有 recall@k、MRR、citation precision、答案忠实性测试，这个项目在面试里会被问穿：“你怎么证明检索效果变好了？”
  6. BackgroundTasks + ThreadPoolExecutor 适合 MVP，不适合可靠任务系统。索引失败重试、任务状态、并发限流、取消、死信队列都没有。后端岗位会更认可 Redis/RQ、Celery、Arq、
     Dramatiq 或自建任务表 + worker。

  Task 5-7 建议
  Task 5 可以做，但要改成“三路混合检索”：

  - vector_search: pgvector cosine + reranker。
  - keyword_search: 不要只靠 ILIKE，优先用 PostgreSQL full-text search；代码符号可以保留 trigram/ILIKE fallback。
  - fusion: 用 RRF 合并 vector 和 keyword，再 rerank。

  pgvector 官方支持 cosine distance、HNSW 索引，并说明 HNSW 在速度/召回折中上优于 IVFFlat，但构建更慢、内存更多。(github.com (https://github.com/pgvector/pgvector)) 你的
  file_chunks.embedding 应该补 HNSW index，不然数据量一上来性能会崩。

  Task 6 的 Research Graph 方向正确，但不要只做一个 agent loop。建议拆成：

  - planner: 判断需要 vector、keyword、web、还是全文读取。
  - retrieve: 多路召回。
  - rerank: 统一重排。
  - write_report: 生成报告。
  - verify_citations: 检查报告引用的 chunk_id 是否真实存在且属于当前用户。

  LangGraph 官方对 interrupt 的推荐是用 interrupt() 动态暂停，并通过相同 thread_id + Command(resume=...) 恢复；静态 interrupt_before 更偏调试/断点，不推荐作为完整 HITL
  工作流核心。(docs.langchain.com (https://docs.langchain.com/oss/python/langgraph/interrupts)) 你现在能跑，但后续应该迁移到 tool 内部 interrupt 或审批节点。

  Task 7 的 SSE 报告闭环应该加 3 个接口，否则不像完整产品：

  - GET /file-research/reports/{id}：查看报告状态和内容。
  - GET /file-research/reports/{id}/sources：返回引用 chunk、文件名、行号、原文。
  - POST /file-research/eval/run：跑固定评测集，输出检索和引用指标。

  GraphRAG 要不要做
  不要现在就上完整 Neo4j GraphRAG。Neo4j 已经有官方 GraphRAG Python 包，覆盖 RAG、知识图谱构建、pipeline、retriever 等能力。(neo4j.com
  (https://neo4j.com/docs/neo4j-graphrag-python/current/)) 但你当前项目最缺的是基础闭环和评测，不是图数据库。
更适合你的路径是：

  1. 先做“结构化索引 Lite”：对代码文件提取函数、类、import、标题层级，存到 PostgreSQL JSONB 或单独表。
  2. 报告生成时支持“符号级引用”：例如 foo.py#L12-L40 function parse_xxx。
  3. 等这个稳定后，再考虑 Neo4j/GraphRAG。

  这比直接上图数据库更适合求职，因为面试官能看出你知道边界和成本。

  最终路线
  按求职价值排序：

  1. 先修 P0：resume_input 拼写、SSRF、Markdown XSS。
  2. 做 Task 5，但升级为 vector + full-text/trigram + RRF + reranker。
  3. 给 file_chunks.embedding 加 HNSW index。
  4. 做可重复评测集：至少 20 个问题，覆盖语义问题、代码符号、跨文件问题、无答案问题。
  5. 做 Research Graph，但加 citation verifier。
  6. 把后台索引从 BackgroundTasks 升级为可靠 worker。
  7. 最后再做 GraphRAG Lite，而不是先引 Neo4j。

  你这个项目最适合在简历上包装成：

  > 基于 LangGraph 的可审计文档研究 Agent：支持多租户文件索引、混合检索、BGE rerank、PostgreSQL checkpoint、人类审批、SSE 流式报告、引用行号追溯与检索评测。

  这比“做了一个 LangChain 聊天机器人”强很多，也更贴近后端 Agent 开发岗位。
