# RAG/Agent 评估体系（Evals）精雕细琢版落地方案

> 方案目标：遵循“本地逻辑先测透，容器部署最后做”的敏捷研发原则。我们将先在本地环境深化开发 **Taskiq Worker** 评估逻辑，引入 Agent 核心评测指标与离线回归测试脚本；随后优化检索召回算法并用评测体系验证指标提升；最后完成容器化封装与 Docker Compose 一键部署。

---

## 一、 系统整体架构 (本地调试态)

在当前阶段，所有进程运行在本地 WSL 终端中以保证极速修改与热重载：

```
                 ┌────────────────────────────────────────────────────────┐
                 │                  WSL 本地开发与调试环境                │
                 └───────────────────────────┬────────────────────────────┘
                                             │
      ┌──────────────────────────────────────┼──────────────────────────────────────┐
      ▼                                      ▼                                      ▼
[ FastAPI 主后端进程 ]                [ Redis Docker 容器 ]                  [ Taskiq Worker 进程 ]
(uvicorn main:app)                    (6379 端口做任务中介)                  (taskiq worker 任务消费)
      │                                      ▲                                      │
      │──> 1. 流式回答                       │──> 2. 获取任务 (BLPOP)               │── 3. 拉取 Trace 数据
      ▼                                      │                                      ▼
   [ 用户 ]                                  │                                [ Langfuse 云平台 ]
      │                                      │                                      ▲
      │──> (触发对话 API)                    │                                      │── 4. 回传打分结果
      └──────────────────────────────────────┘                                      │
                                             │                                      │
                                             └──────────────────────────────────────┘
```

---

## 二、 阶段一：本地精雕细琢阶段 (当前阶段)

在此阶段，我们完全在本地进行 Worker 功能的深度增强。

### 任务 1：升级 Worker 评估指标 (增加 Agent 维度评估)
在 [task.py](file:///home/wsyc1/projects/langchain/backend/src/eval_service/task.py) 中，不仅评估 RAG 质量，更增加对 Agent 推理表现的评估：
1.  **评估推理路径效率（`trajectory_steps`）**：
    统计该 Trace 下 `observations` 的节点总数。如果步骤数超标（例如大于 8 步），说明 Agent 的规划能力出现偏差，并将其作为负向指标上传至 Langfuse。
2.  **评估工具选择准确率（`tool_call_accuracy`）**：
    在深度研究任务中，核验 `observations` 列表内是否包含 `"search_document_by_vector"` 工具的调用。包含则得 `1.0` 分，未触发则得 `0.0` 分，判定 Agent 决策失误。

### 任务 2：编写「离线回归评测脚本（`run_offline_eval.py`）」
在 `backend/tests/evals/` 下编写一个批量跑分脚本，用于系统代码修改后的效果验证：
*   **输入**：读取黄金测试集 [golden_set.json](file:///home/wsyc1/projects/langchain/backend/tests/evals/golden_set.json)。
*   **运行**：自动对这 15 条评测用例并发或轮流发起 FastAPI 对话请求。
*   **汇总**：等待 Taskiq 评测完成后，利用 Langfuse SDK 批量拉取这 15 条 Trace 的分数值，计算出当前版本的平均 `Faithfulness`（忠实度）和 `Answer Relevance`（相关度），在控制台输出版本评测报告。

### 任务 3：优化 RAG 检索算法并进行对比验证 (评测闭环)
1.  修改 [retriever.py](file:///home/wsyc1/projects/langchain/backend/src/file_research/retriever.py) 算法：
    *   在 PostgreSQL 中创建 `tsvector` 全文检索索引。
    *   在 Python 代码中实现向量检索与 BM25 全文检索的混合双路召回。
    *   使用 **RRF (Reciprocal Rank Fusion)** 算法对两路候选集进行融合精排。
2.  运行 `run_offline_eval.py` 离线评测脚本，对比算法修改前后的平均得分，用数据证明检索优化成功。

---

## 三、 阶段二：生产部署容器化阶段 (后续阶段)

当本地的评测逻辑、回归测试以及检索优化全部完成后，我们正式开始进行容器化封装。

### 1. 目录结构规范
```
/projects/langchain/
├── backend/
│   ├── src/
│   │   ├── service/
│   │   │   ├── agent.py
│   │   │   └── task_queue.py
│   │   └── eval_service/
│   │       └── task.py          <-- 包含升级后指标的评测任务
│   ├── Dockerfile               <-- 多阶段构建的轻量级 Python 镜像
│   └── pyproject.toml
└── docker-compose.yml           <-- 根目录下编排 Postgres, Redis, API, Worker
```

### 2. 编写 `Dockerfile` 与 `docker-compose.yml`
使用 Docker 卷挂载（Volume Mounts）实现容器内代码与本地热同步，彻底打通一键部署与持续开发。
