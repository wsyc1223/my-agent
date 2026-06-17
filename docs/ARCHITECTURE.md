# LangChain 项目核心架构图志 (Architecture)

本文档采用 **Docs-as-Code** 的方式管理项目架构。
请通过能渲染 Mermaid 语法的工具（如 GitHub、VSCode 预览插件、Neovim 的 `markdown-preview.nvim`）来阅读本文档。

## 1. 核心实体关系图 (ER Diagram)

数据库层面，我们将业务划分为三个核心域：**认证与基础域**、**知识库域**、**研究与聊天域**。

```mermaid
erDiagram
    %% 核心认证与用户域
    User ||--o{ UserCredential : "拥有认证方式"
    User ||--o{ Conversation : "拥有普通会话"
    User ||--o{ FileDocument : "上传文件"
    User ||--o{ ResearchSession : "发起深度调研"

    %% 知识库体系 (RAG 核心)
    FileDocument ||--o{ FileChunk : "切片入库 (pgvector)"

    %% 简单聊天体系
    Conversation ||--o{ Message : "包含普通消息"

    %% 深度调研体系 (Workspace 与资产化设计)
    ResearchSession ||--o{ ResearchMessage : "包含对话流"
    ResearchSession ||--o{ FileReport : "产出调研报告"
    
    %% 消息与资产的锚定关系
    ResearchMessage }o--o| FileReport : "外键: generated_report_id"
    ResearchMessage }o--o| FileDocument : "JSON: attached_file_ids"
```

---

## 2. 核心业务时序图 (Sequence Diagrams)

### 2.1 文档入库与切片处理流程
当用户上传文档时，系统如何将文档转化为支持向量检索的知识库资产。

```mermaid
sequenceDiagram
    autonumber
    participant Client as 客户端 (前端)
    participant Router as 路由层 (file_handler)
    participant DB as 关系型数据库 (PostgreSQL)
    participant BGTask as 异步后台任务 (Indexer)
    participant VectorDB as 向量数据库 (PGVector)

    Client->>Router: 上传 PDF/文档
    Router->>DB: 创建 FileDocument 记录<br/>(status="processing")
    Router-->>Client: 立即返回文件 ID (避免前端超时)
    
    %% 异步任务阶段
    Router-)BGTask: 触发后台解析任务 (async)
    activate BGTask
    BGTask->>BGTask: 提取全文 (PyMuPDF等)
    BGTask->>BGTask: 文档分块 (TextSplitter)
    BGTask->>BGTask: 调用大模型计算 Embedding (768维)
    BGTask->>VectorDB: 批量插入 FileChunk (bulk_create)
    BGTask->>DB: 更新 FileDocument <br/>(status="indexed", 记录 full_content)
    deactivate BGTask
```

### 2.2 深度调研流式图工作流 (LangGraph + SSE)
这也是即将实施的 Task 7 的完整业务闭环逻辑。

```mermaid
sequenceDiagram
    autonumber
    participant Client as 客户端 (前端)
    participant Router as 路由层 (file_research)
    participant Repo as 仓储层 (Repository)
    participant Graph as 调研图节点 (LangGraph)
    participant LLM as 大语言模型

    Client->>Router: POST /stream <br/>带上 query, file_ids, session_id
    
    %% 数据库落库：初始化 Workspace 状态
    Router->>Repo: [获取/新建] ResearchSession
    Router->>Repo: [新增] ResearchMessage <br/>(role="user", 关联 attached_file_ids)
    Router->>Repo: [新建] FileReport <br/>(status="running", 记录 session_id)
    
    %% 图节点流式执行
    Router->>Graph: research_app.astream() 启动图推演
    activate Graph
    
    loop 多步推理与工具调用
        Graph->>LLM: 思考当前状态需要调什么工具
        LLM-->>Graph: 返回工具调用决定
        Graph->>Graph: 节点执行：Web_Search / 本地文件向量检索
        Graph-->>Router: yield 产生当前思考步骤数据块
        Router-->>Client: SSE 推送: `data: {"status": "thinking", "content": "..."}`
    end
    
    Graph-->>Router: yield 生成最终 Markdown 报告全文
    deactivate Graph
    
    %% 数据库落库：完成工作流闭环
    Router->>Repo: [更新] FileReport <br/>(status="success", 写入 report_md全文)
    Router->>Repo: [新增] ResearchMessage <br/>(role="assistant", 关联 generated_report_id)
    
    Router-->>Client: SSE 推送: `data: {"status": "done"}` [请求结束]
```

---

## 3. 三层架构约束说明

本项目严格遵循后端分层架构，避免“意大利面条式”代码：

1. **Router 层 (路由接入)**：仅负责 HTTP 请求验证、获取用户身份 (User ID)、解析 JSON 体，以及进行 SSE 流式包装。禁止在此层写 SQL 或复杂的业务条件。
2. **Service / Graph 层 (业务逻辑与编排)**：核心心脏。负责拼装 Prompt、调用 LLM、管理状态机 (StateGraph) 以及数据校验。
3. **Repository 层 (数据仓储)**：无感情的数据库工人。只暴露针对实体 (Session, Message, Report, Document) 的 `create`, `get`, `update` 异步方法。所有 SQLAlchemy 语法（如 `select`, `commit`, `refresh`）严格限制在此层内。
